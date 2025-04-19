import asyncio
import os
import time
import random
import re # Ensure re is imported
from playwright.async_api import async_playwright, Browser, Page, BrowserContext # Import necessary types

# --- load_user_pool remains synchronous ---
def load_user_pool(user_pool_path):
    """
    (同步) 从 user_pool.md 读取账户池，返回 [{'username':..., 'password':..., 'last_login':...}, ...] 列表。
    若无 last_login 字段，则自动补为 0 并写回文件 (假定调用者持有锁)。
    返回排序后的列表。
    """
    users = []
    lines_to_write_back = []
    needs_write_back = False

    if not os.path.exists(user_pool_path):
        print(f"Warning: {user_pool_path} not found, creating an empty one.")
        try:
            with open(user_pool_path, 'w', encoding="utf-8") as f: pass
        except Exception as e:
             print(f"Error creating empty {user_pool_path}: {e}")
             raise
        return []

    try:
        with open(user_pool_path, 'r', encoding="utf-8") as f:
            original_lines = f.readlines()
    except Exception as e:
        print(f"Error reading {user_pool_path}: {e}")
        raise

    for line in original_lines:
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith('#'):
            lines_to_write_back.append(line.strip())
            continue

        parse_line = stripped_line
        match = re.match(r"^\s*\d+\.\s*", parse_line)
        if match:
            parse_line = parse_line[match.end():].strip()

        parts = [x.strip() for x in parse_line.split(',')]
        username = parts[0] if len(parts) > 0 else ""
        password = parts[1] if len(parts) > 1 else ""
        note = parts[2] if len(parts) > 2 else ""
        last_login_str = parts[3] if len(parts) > 3 else "0"

        if len(parts) < 4:
            needs_write_back = True
            corrected_parts = [username, password, note, "0"]
            lines_to_write_back.append(','.join(corrected_parts))
        else:
            lines_to_write_back.append(stripped_line)

        try:
            last_login_float = float(last_login_str)
        except ValueError:
            print(f"Warning: Invalid last_login value '{last_login_str}' for user '{username}'. Using 0.")
            last_login_float = 0.0
            needs_write_back = True

        if username:
             users.append({'username': username, 'password': password, 'note': note, 'last_login': last_login_float})

    if needs_write_back:
        print(f"Rewriting {user_pool_path} to ensure all entries have a valid timestamp.")
        try:
            with open(user_pool_path, 'w', encoding="utf-8") as f:
                for line_to_write in lines_to_write_back:
                    f.write(line_to_write + '\n')
        except Exception as e:
             print(f"Error writing back to {user_pool_path}: {e}")

    users.sort(key=lambda x: x['last_login'])
    return users

# --- update_user_login_time remains synchronous ---
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

    try:
        with open(user_pool_path, 'w', encoding="utf-8") as f:
            for u in users:
                 f.write(f"{u['username']},{u['password']},{u['note']},{int(u['last_login'])}\n")
        print(f"Updated login time for {username_to_update} in {user_pool_path}")
    except Exception as e:
        print(f"Error writing updated user list to {user_pool_path}: {e}")

# --- switch_user is async, now uses browser.new_context ---
async def switch_user(browser: Browser, file_lock: asyncio.Lock, active_users_lock: asyncio.Lock, active_users: set, headless=False) -> tuple[dict, BrowserContext, Page]:
    """
    (并发安全) 选择一个可用账户，标记为活跃并更新时间戳。
    使用传入的 Browser 实例创建一个新的、隔离的上下文并登录。
    :param browser: Playwright Browser 实例
    :param file_lock: 用于保护 user_pool.md 文件读写的锁
    :param active_users_lock: 用于保护 active_users 集合访问的锁
    :param active_users: 当前正在使用的账户用户名集合
    :param headless: (不再直接使用，浏览器已启动)
    :return: tuple(dict, BrowserContext, Page) 包含选中用户信息的字典、登录成功后的新上下文和页面
    :raises: Exception 如果没有可用的账户或登录失败
    """
    user_pool_path = 'user_pool.md'
    selected_user = None
    users = []
    context = None # Initialize context for potential cleanup in error cases

    # --- Select User & Update Timestamp Immediately (Concurrency Safe) ---
    async with file_lock:
        loop = asyncio.get_running_loop()
        users = await loop.run_in_executor(None, load_user_pool, user_pool_path)

        async with active_users_lock:
            if not users:
                 raise Exception("账户池为空，无法切换用户！")

            for user_candidate in users:
                if user_candidate['username'] not in active_users:
                    selected_user = user_candidate
                    active_users.add(selected_user['username'])
                    print(f"[账户选择] 选中账户: {selected_user['username']} (上次登录: {selected_user['last_login']})")
                    # Update timestamp immediately after selection and marking active
                    print(f"立即更新账户 {selected_user['username']} 的登录时间...")
                    await loop.run_in_executor(None, update_user_login_time, user_pool_path, users, selected_user['username'])
                    break

    if selected_user is None:
        raise Exception(f"无法找到可用账户，当前活跃账户: {active_users}")
    # --- User Selected and Timestamp Updated ---

    # --- Browser Login in New Context ---
    try:
        print(f"[并发登录] 为用户 {selected_user['username']} 创建新的浏览器上下文...")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            java_script_enabled=True,
            accept_downloads=True,
        )
        page = await context.new_page()
        print(f"[并发登录] 新上下文和页面已创建 for {selected_user['username']}")

        await page.goto("https://chat.deepseek.com/")
        await asyncio.sleep(random.uniform(2, 4)) # Wait for page load

        # --- Execute Login Steps (No initial login check needed) ---
        print(f"[并发登录] 执行登录步骤 for {selected_user['username']}")

        # 1. Attempt to switch to password login tab if needed
        try:
            # Use updated locator and logic
            password_tab_locator = page.locator('div.ds-tab:has-text("密码登录")')
            await password_tab_locator.wait_for(state="visible", timeout=5000)
            is_active = await password_tab_locator.evaluate("node => node.classList.contains('ds-tab--active')")
            if not is_active:
                print(f"[并发登录] 点击'密码登录'标签页 for {selected_user['username']}")
                await password_tab_locator.click()
                await asyncio.sleep(random.uniform(1, 2))
            else:
                print(f"[并发登录] '密码登录'标签页已激活 for {selected_user['username']}")
        except Exception as e:
            print(f"[并发登录][INFO] 查找或点击'密码登录'时出错或超时 for {selected_user['username']} (可能已在密码页): {e}")

        # 2. Input username (Use updated locator)
        username_input = page.locator('input[placeholder="请输入手机号/邮箱地址"]')
        await username_input.wait_for(state="visible", timeout=10000)
        await username_input.fill(selected_user['username'])
        print(f"[并发登录] 已输入用户名 for {selected_user['username']}")
        await asyncio.sleep(random.uniform(0.5, 1))

        # 3. Input password (Use updated locator)
        password_input = page.locator('input[placeholder="请输入密码"]')
        await password_input.wait_for(state="visible", timeout=10000)
        await password_input.fill(selected_user['password'])
        print(f"[并发登录] 已输入密码 for {selected_user['username']}")
        await asyncio.sleep(random.uniform(0.5, 1))

        # 4. Click login button (Use updated locator)
        login_button = page.locator('div[role="button"].ds-button--primary:has-text("登录")')
        await login_button.wait_for(state="visible", timeout=10000)
        await login_button.click()
        print(f"[并发登录] 已点击登录按钮 for {selected_user['username']}")

        # 5. Wait for successful login
        await page.wait_for_selector("textarea", timeout=30000, state="visible") # Assuming textarea indicates login
        print(f"[并发登录] 登录成功 for {selected_user['username']} (找到 textarea)")

        # --- Login successful, return context and page ---
        print(f"[并发登录] 用户 {selected_user['username']} 登录流程完成。")
        return selected_user, context, page # Return the user dict, context, and page

    except Exception as login_err:
        print(f"[并发登录][ERROR] Login process failed for user {selected_user['username']}: {login_err}")
        # Attempt screenshot if page exists
        if 'page' in locals() and page and not page.is_closed():
             try:
                 await page.screenshot(path=f"login_error_{selected_user['username']}.png")
                 print(f"已保存登录错误截图: login_error_{selected_user['username']}.png")
             except Exception as screenshot_e:
                 print(f"保存截图失败: {screenshot_e}")
        # Close context if it was created
        if context:
            await context.close()
        # Release the user from active_users as login failed
        async with active_users_lock:
            if selected_user['username'] in active_users:
                active_users.remove(selected_user['username'])
                print(f"[账户释放][失败] 释放账户: {selected_user['username']}")
        raise login_err # Re-raise the exception

# --- Test function needs update ---
async def _test_switch_user_async(headless=False):
    file_lock = asyncio.Lock()
    active_users_lock = asyncio.Lock()
    active_users = set()
    context = None
    browser = None
    username_in_test = None # Track username used in test

    async with async_playwright() as p:
        try:
            print("[Test] Launching browser...")
            browser = await p.chromium.launch(headless=headless)
            print("[Test] Browser launched. Calling switch_user...")
            # Call the modified switch_user, passing the browser instance
            # Call the modified switch_user, expecting user_dict, context, page
            selected_user_dict, context, page = await switch_user(browser, file_lock, active_users_lock, active_users, headless=headless)
            username_in_test = selected_user_dict['username'] # Get username from the returned dict
            print(f"测试成功切换到用户: {username_in_test}")
            print(f"当前活跃用户集合: {active_users}") # Should contain username_in_test
            # Add a simple check
            await page.wait_for_selector("textarea", timeout=5000)
            print("[Test] Textarea found, login likely successful.")
            # Verify active_users set
            if username_in_test not in active_users:
                 print(f"[Test ERROR] User {username_in_test} was returned but not found in active_users set: {active_users}")


        except Exception as e:
            print(f"测试切换用户失败: {e}")
        finally:
            # Close context if created
            if context:
                print("[Test] Closing context...")
                await context.close()
            # Release user if added
            if username_in_test:
                 async with active_users_lock:
                     if username_in_test in active_users:
                         active_users.remove(username_in_test)
                         print(f"测试释放用户: {username_in_test}")
                         print(f"释放后活跃用户集合: {active_users}")
            # Close browser
            if browser:
                print("[Test] Closing browser...")
                await browser.close()

def test_switch_user():
    if not os.path.exists('user_pool.md'):
        print("Creating dummy user_pool.md for testing.")
        with open('user_pool.md', 'w') as f:
            f.write("testuser1,password,note,0\n")
            f.write("testuser2,password,note,0\n")
    asyncio.run(_test_switch_user_async(headless=False))

if __name__ == "__main__":
    test_switch_user()
