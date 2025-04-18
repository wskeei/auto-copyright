import asyncio
import os
import time
import random
from playwright.async_api import async_playwright

def load_user_pool(user_pool_path):
    """
    从 user_pool.md 读取账户池，返回 [{'username':..., 'password':..., 'last_login':...}, ...]，并按 last_login 升序排序。
    若无 last_login 字段，则自动补为 0 并写回文件。
    """
    users = []
    changed = False
    if not os.path.exists(user_pool_path):
        raise Exception(f"user_pool.md not found: {user_pool_path}")
    with open(user_pool_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            # 去除序号前缀（如 '1. '）
            if '.' in line.split(',')[0]:
                line = line[line.find('.')+1:].strip()
            parts = [x.strip() for x in line.split(',')]
            # 账户,密码,备注,时间戳
            while len(parts) < 4:
                if len(parts) == 2:
                    parts.append('')  # 备注
                elif len(parts) == 3:
                    parts.append('0')  # 时间戳
                else:
                    break
                changed = True
            if len(parts) < 4: continue
            users.append({'username': parts[0], 'password': parts[1], 'note': parts[2], 'last_login': float(parts[3])})
    if changed:
        # 写回带完整字段的内容
        with open(user_pool_path, 'w', encoding="utf-8") as f:
            for u in users:
                f.write(f"{u['username']},{u['password']},{u['note']},{int(u['last_login'])}\n")
    users.sort(key=lambda x: x['last_login'])
    return users

def update_user_login_time(user_pool_path, username):
    """更新 user_pool.md 中指定用户名的 last_login 时间为当前时间（时间戳）"""
    if not os.path.exists(user_pool_path):
        return
    lines = []
    now = str(int(time.time()))
    with open(user_pool_path, encoding="utf-8") as f:
        for line in f:
            # 忽略序号前缀
            l = line.strip()
            if '.' in l.split(',')[0]:
                l = l[l.find('.')+1:].strip()
            parts = [x.strip() for x in l.split(',')]
            while len(parts) < 4:
                if len(parts) == 2:
                    parts.append('')
                elif len(parts) == 3:
                    parts.append('0')
                else:
                    break
            if len(parts) >= 4 and parts[0] == username:
                parts[3] = now
                line = ','.join(parts)
            lines.append(line.strip())
    with open(user_pool_path, 'w', encoding="utf-8") as f:
        for line in lines:
            f.write(line + '\n')

async def switch_user(headless=False):
    """
    切换到最久未用账户并完成登录。
    如果打开页面后已是登录状态，则直接更新时间并退出。
    :param headless: 是否无头运行
    :return: None
    """
    user_pool_path = 'user_pool.md'
    user_data_dir = './user_data_chromium'
    # 1. 清除用户登录信息 (保持不变)
    if os.path.exists(user_data_dir):
        import shutil
        shutil.rmtree(user_data_dir)
        print(f"已清理 {user_data_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(user_data_dir, headless=headless)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto("https://chat.deepseek.com/")
        await asyncio.sleep(random.uniform(2, 4)) # 增加等待时间确保页面加载

        # 检查是否已经登录 (例如，检查聊天输入框是否存在且可见)
        is_logged_in = False
        try:
            # 使用一个明确的登录后元素，比如聊天输入框 textarea
            await page.wait_for_selector("textarea", timeout=5000, state="visible")
            print("检测到已登录状态 (找到 textarea)。")
            is_logged_in = True
        except Exception:
            print("未检测到登录状态，尝试进行登录流程。")
            is_logged_in = False

        if is_logged_in:
            # 如果已登录，直接选取用户并更新时间
            users = load_user_pool(user_pool_path)
            if not users:
                 print("[WARN] user_pool.md 为空或无法加载，无法更新登录时间。")
                 await browser.close()
                 return
            user = users[0] # 仍然选择最久未用的，即使是自动登录的
            print(f"已自动登录，用户视为: {user['username']}")
            update_user_login_time(user_pool_path, user['username'])
            print(f"已更新 {user['username']} 的登录时间")
        else:
            # 如果未登录，执行原有的登录流程
            try:
                # 2. 点击“切换到密码登录”
                # 等待登录表单容器出现
                login_form_selector = 'div.login_form_wrapper' # 假设登录表单有一个特定的父容器
                await page.wait_for_selector(login_form_selector, timeout=20000)
                # 在登录表单内查找密码登录tab
                password_tab_selector = f'{login_form_selector} div.ds-tab__content:has-text("密码登录")'
                password_tab = page.locator(password_tab_selector)
                if await password_tab.count() > 0:
                    await password_tab.click()
                    print("已点击'密码登录'标签页。")
                else:
                     print("[WARN] 未找到'密码登录'按钮，可能页面结构已改变或已在密码登录页。")
                     # 可以选择抛出异常或尝试其他登录方式
                     # raise Exception("未找到'密码登录'按钮") # 或者记录日志并继续

                await asyncio.sleep(random.uniform(1,2))

                # 3. 选取最久未登录的账户
                users = load_user_pool(user_pool_path)
                if not users:
                    raise Exception("user_pool.md 为空或无法加载。")
                user = users[0]
                print(f"使用账户: {user['username']}")

                # 4. 输入账户
                # 使用更精确的定位器，例如 placeholder 或 name 属性
                username_input = page.locator('input[placeholder="手机号/邮箱"], input[name="account"]') # 尝试两种可能的定位器
                await username_input.wait_for(state="visible", timeout=10000)
                await username_input.fill(user['username'])
                await asyncio.sleep(random.uniform(0.5, 1)) # 减少一点随机等待

                # 5. 输入密码
                password_input = page.locator('input[placeholder="密码"], input[name="password"]') # 尝试两种可能的定位器
                await password_input.wait_for(state="visible", timeout=10000)
                await password_input.fill(user['password'])
                await asyncio.sleep(random.uniform(0.5, 1))

                # 6. 点击登录按钮
                # 使用更精确的定位器
                login_button = page.locator('div[role="button"].ds-button--primary:has-text("登录")')
                await login_button.wait_for(state="visible", timeout=10000)
                await login_button.click()
                print('已点击登录')
                # 等待登录成功后的页面特征，而不是固定等待时间
                # 例如等待聊天输入框再次出现
                await page.wait_for_selector("textarea", timeout=30000, state="visible")
                print("登录成功，已跳转到聊天页面。")

                # 7. 更新登录时间
                update_user_login_time(user_pool_path, user['username'])
                print(f"已更新 {user['username']} 的登录时间")

            except Exception as e:
                print(f"登录过程中发生错误: {e}")
                # 可以在这里添加截图等调试信息
                try:
                    await page.screenshot(path="login_error.png")
                    print("已保存登录错误截图: login_error.png")
                except Exception as screenshot_e:
                    print(f"保存截图失败: {screenshot_e}")
                await browser.close() # 确保出错时关闭浏览器
                raise e # 将异常抛出，让上层知道出错了

        await browser.close() # 无论登录与否，最后都关闭浏览器

# 兼容原有测试入口
def test_switch_user():
    asyncio.run(switch_user(headless=False))

if __name__ == "__main__":
    test_switch_user()
