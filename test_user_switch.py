import asyncio
import os
import time
import random
from playwright.async_api import async_playwright

# 再次尝试：修改为同步函数，不再处理锁
import re # Add import for re used below
def load_user_pool(user_pool_path):
    """
    (同步) 从 user_pool.md 读取账户池，返回 [{'username':..., 'password':..., 'last_login':...}, ...] 列表。
    若无 last_login 字段，则自动补为 0 并写回文件 (假定调用者持有锁)。
    返回排序后的列表。
    """
    users = []
    lines_to_write_back = [] # 用于可能的回写
    needs_write_back = False

    if not os.path.exists(user_pool_path):
        print(f"Warning: {user_pool_path} not found, creating an empty one.")
        try:
            with open(user_pool_path, 'w', encoding="utf-8") as f:
                pass # Create empty file
        except Exception as e:
             print(f"Error creating empty {user_pool_path}: {e}")
             raise # Re-raise error if file cannot be created
        return [] # Return empty list

    try:
        with open(user_pool_path, 'r', encoding="utf-8") as f:
            original_lines = f.readlines()
    except Exception as e:
        print(f"Error reading {user_pool_path}: {e}")
        raise # Re-raise error if file cannot be read

    for line in original_lines:
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith('#'):
            lines_to_write_back.append(line.strip()) # 保留注释和空行
            continue

        # 去除序号前缀（如 '1. '） - 仅用于解析，不修改原始行
        parse_line = stripped_line
        match = re.match(r"^\s*\d+\.\s*", parse_line)
        if match:
            parse_line = parse_line[match.end():].strip()

        parts = [x.strip() for x in parse_line.split(',')]

        # 账户,密码,备注,时间戳
        username = parts[0] if len(parts) > 0 else ""
        password = parts[1] if len(parts) > 1 else ""
        note = parts[2] if len(parts) > 2 else ""
        last_login_str = parts[3] if len(parts) > 3 else "0" # Default to "0" if missing

        # Check if timestamp needs to be added/corrected
        if len(parts) < 4:
            needs_write_back = True
            corrected_parts = [username, password, note, "0"]
            lines_to_write_back.append(','.join(corrected_parts))
        else:
            lines_to_write_back.append(stripped_line) # Use the original stripped line

        try:
            last_login_float = float(last_login_str)
        except ValueError:
            print(f"Warning: Invalid last_login value '{last_login_str}' for user '{username}'. Using 0.")
            last_login_float = 0.0
            # If conversion failed, we might need to update lines_to_write_back again
            # For simplicity, let's assume the initial correction or original line is sufficient
            # and rely on the needs_write_back flag.
            needs_write_back = True

        if username: # Only add if username is not empty
             users.append({'username': username, 'password': password, 'note': note, 'last_login': last_login_float})

    if needs_write_back:
        print(f"Rewriting {user_pool_path} to ensure all entries have a valid timestamp.")
        # 写回带完整字段的内容 - 确保此操作在持有 file_lock 时执行
        try:
            with open(user_pool_path, 'w', encoding="utf-8") as f:
                for line_to_write in lines_to_write_back:
                    f.write(line_to_write + '\n')
        except Exception as e:
             print(f"Error writing back to {user_pool_path}: {e}")
             # Decide how to handle write error, maybe raise it?

    users.sort(key=lambda x: x['last_login'])
    return users

# 修改为同步函数，接收用户列表，更新后写回文件，不再处理锁
def update_user_login_time(user_pool_path, users: list, username_to_update: str):
    """
    (同步) 更新内存中用户列表指定用户的 last_login 时间，并将整个列表写回 user_pool.md。
    假定调用者持有文件锁。
    """
    now = time.time()
    found = False
    for user in users:
        if user['username'] == username_to_update:
            user['last_login'] = now
            found = True
            break

    if not found:
        print(f"Warning: User '{username_to_update}' not found in the list for timestamp update.")
        # Optionally, reload the file here if strict consistency is needed,
        # but assuming the caller manages the list correctly.

    # 写回整个更新后的列表 (确保格式正确)
    try:
        with open(user_pool_path, 'w', encoding="utf-8") as f:
            # It's safer to reconstruct lines from the 'users' list
            # to ensure consistency, rather than trying to modify original lines.
            for u in users:
                 # Write in the format: username,password,note,timestamp
                 f.write(f"{u['username']},{u['password']},{u['note']},{int(u['last_login'])}\n")
        print(f"Updated login time for {username_to_update} in {user_pool_path}")
    except Exception as e:
        print(f"Error writing updated user list to {user_pool_path}: {e}")
        # Consider raising the exception

async def switch_user(user_data_dir: str, file_lock: asyncio.Lock, active_users_lock: asyncio.Lock, active_users: set, headless=False):
    """
    (修正死锁 v2) 切换到最久未用且当前未被其他并发任务使用的账户并完成登录。
    确保使用传入的唯一 user_data_dir。锁的获取/释放已调整。
    load_user_pool 和 update_user_login_time 已改为同步。
    :param user_data_dir: 此任务应使用的唯一用户数据目录路径
    :param file_lock: 用于保护 user_pool.md 文件读写的锁
    :param active_users_lock: 用于保护 active_users 集合访问的锁
    :param active_users: 当前正在使用的账户用户名集合
    :param headless: 是否无头运行
    :return: 成功登录的用户名 (str)
    :raises: Exception 如果没有可用的账户或浏览器启动/登录失败
    """
    user_pool_path = 'user_pool.md'
    selected_user = None
    users = [] # Define users list in the broader scope

    # --- Select User ---
    async with file_lock: # Acquire file_lock (Lock A)
        # Load users synchronously while holding the lock
        users = load_user_pool(user_pool_path) # Synchronous call

        async with active_users_lock: # Acquire active_users_lock (Lock B)
            if not users:
                 # Still holding file_lock here, but okay for exception
                 raise Exception("账户池为空，无法切换用户！")

            for user_candidate in users:
                if user_candidate['username'] not in active_users:
                    selected_user = user_candidate
                    active_users.add(selected_user['username']) # Mark as active
                    print(f"[账户选择] 选中账户: {selected_user['username']} (上次登录: {selected_user['last_login']})")
                    break
        # Release active_users_lock (Lock B) implicitly
    # Release file_lock (Lock A) implicitly

    if selected_user is None:
        # No lock held here, safe to raise
        raise Exception(f"无法找到可用账户，当前活跃账户: {active_users}")
    # --- User Selected ---

    # --- Browser Login ---
    # 1. 清除指定的用户登录信息目录 (Do this *after* selecting user and releasing file lock)
    if os.path.exists(user_data_dir):
        import shutil
        try:
            shutil.rmtree(user_data_dir)
            print(f"已清理 {user_data_dir}")
        except OSError as e:
            print(f"清理 {user_data_dir} 时出错 (可能被占用): {e}")
            # Consider releasing the user if cleanup fails critically? For now, proceed.
    else:
        # Ensure parent directory exists if cleaning didn't happen
        parent_dir = os.path.dirname(user_data_dir)
        if parent_dir and not os.path.exists(parent_dir):
             os.makedirs(parent_dir, exist_ok=True)

    browser = None # Define browser for finally block
    try:
        async with async_playwright() as p:
            # 使用传入的 user_data_dir 启动浏览器
            browser = await p.chromium.launch_persistent_context(user_data_dir, headless=headless)
            page = browser.pages[0] if browser.pages else await browser.new_page()

            print(f"使用账户: {selected_user['username']}")
            await page.goto("https://chat.deepseek.com/")
            await asyncio.sleep(random.uniform(1,2))
            # 2. 点击“切换到密码登录”
            await page.wait_for_selector('div.ds-tab__content', timeout=20000)
            tab_btns = await page.query_selector_all('div.ds-tab__content')
            for btn in tab_btns:
                text = await btn.inner_text()
                if '密码登录' in text:
                    await btn.click()
                    break
            await asyncio.sleep(random.uniform(1,2))

            # 4. 输入账户
            inputs = await page.query_selector_all('input.ds-input__input[type="text"]')
            if not inputs:
                raise Exception('未找到用户名输入框')
            await inputs[0].fill(selected_user['username'])
            await asyncio.sleep(random.uniform(1,2))
            # 5. 输入密码
            pw_inputs = await page.query_selector_all('input.ds-input__input[type="password"]')
            if not pw_inputs:
                raise Exception('未找到密码输入框')
            await pw_inputs[0].fill(selected_user['password'])
            await asyncio.sleep(random.uniform(1,2))
            # 6. 点击登录按钮
            login_btns = await page.query_selector_all('div[role="button"].ds-button--primary')
            found = False
            for btn in login_btns:
                text = await btn.inner_text()
                if '登录' in text:
                    await btn.click()
                    found = True
                    break
            if not found:
                raise Exception('未找到登录按钮')
            print('已点击登录')
            await asyncio.sleep(5) # Wait for login to potentially complete
            # --- Login Attempted ---

            # --- Update Login Time (Only after successful login attempt phase) ---
            async with file_lock: # Acquire file_lock again (Lock C)
                # Update time and write back synchronously while holding the lock
                # Pass the 'users' list loaded earlier
                update_user_login_time(user_pool_path, users, selected_user['username']) # Synchronous call
            # Release file_lock (Lock C) implicitly
            # --- Login Time Updated ---

            await browser.close() # Close browser *before* returning success
            browser = None # Mark as closed
            return selected_user['username'] # Return username only on successful login & timestamp update

    except Exception as login_err:
         print(f"Login process failed for user {selected_user['username']}: {login_err}")
         # Important: Need to release the user from active_users if login fails *after* selection
         async with active_users_lock:
             if selected_user['username'] in active_users:
                 active_users.remove(selected_user['username'])
                 print(f"[账户释放][失败] 释放账户: {selected_user['username']}")
         raise login_err # Re-raise the exception after releasing user
    finally:
        # Ensure browser is closed if an error occurred after launch but before explicit close
        if browser:
            try:
                await browser.close()
                print(f"Browser context closed in finally block for {selected_user['username']}")
            except Exception as close_err:
                 print(f"Error closing browser in finally block for {selected_user['username']}: {close_err}")

# 兼容原有测试入口
# Test function needs update to reflect synchronous changes if necessary,
# but the main logic change is in switch_user itself.
# Keeping test structure similar for now.
async def _test_switch_user_async(headless=False):
    # 为测试创建一个唯一的目录
    test_user_data_dir = "./user_data_test_switch"
    file_lock = asyncio.Lock()
    active_users_lock = asyncio.Lock()
    active_users = set()
    username = None # Ensure username is defined for finally block
    try:
        # Call the modified switch_user
        username = await switch_user(test_user_data_dir, file_lock, active_users_lock, active_users, headless=headless)
        print(f"测试成功切换到用户: {username}")
        print(f"当前活跃用户集合: {active_users}")
    except Exception as e:
        print(f"测试切换用户失败: {e}")
    finally:
        # 模拟任务完成，释放用户 (Ensure lock is acquired for modification)
        if username: # Check if username was assigned
             async with active_users_lock: # Acquire lock to safely modify the set
                 if username in active_users: # Double check before removing
                     active_users.remove(username)
                     print(f"测试释放用户: {username}")
                     print(f"释放后活跃用户集合: {active_users}")
        # 清理测试目录
        if os.path.exists(test_user_data_dir):
            import shutil
            try:
                shutil.rmtree(test_user_data_dir)
                print(f"已清理测试目录: {test_user_data_dir}")
            except OSError as e:
                print(f"清理测试目录 {test_user_data_dir} 时出错: {e}")

def test_switch_user():
    # Ensure user_pool.md exists for testing, create a dummy if not
    if not os.path.exists('user_pool.md'):
        print("Creating dummy user_pool.md for testing.")
        with open('user_pool.md', 'w') as f:
            f.write("testuser1,password,note,0\n")
            f.write("testuser2,password,note,0\n")
    asyncio.run(_test_switch_user_async(headless=False))

if __name__ == "__main__":
    test_switch_user()
