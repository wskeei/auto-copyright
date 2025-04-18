import asyncio
import os
import time
import random
from playwright.async_api import async_playwright, Browser # Import Browser type hint

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

async def switch_user(browser: Browser, headless=False): # Accept Browser instance
    """
    使用给定的 Browser 实例创建一个新的、干净的上下文，并切换到最久未用账户完成登录。
    :param browser: Playwright Browser 实例
    :param headless: (此参数在此模型下可能不再直接需要，因为 browser 已启动)
    :return: tuple(BrowserContext, Page) 登录成功后的上下文和页面
    """
    user_pool_path = 'user_pool.md'
    context = None # Initialize context variable

    try:
        # Create a new isolated context for each login attempt
        print("[LOG] 创建新的浏览器上下文...")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36", # Example User Agent
            java_script_enabled=True,
            accept_downloads=True,
            # viewport={'width': 1920, 'height': 1080} # Optional: set viewport
        )
        page = await context.new_page()
        print("[LOG] 新上下文和页面已创建。")

        await page.goto("https://chat.deepseek.com/")
        await asyncio.sleep(random.uniform(2, 4)) # Wait for page load

        # --- Start login process in the new context ---
        # 2. Attempt to switch to password login tab if needed
        try:
            password_tab_locator = page.locator('div.ds-tab:has-text("密码登录")')
            # Wait briefly for the tab to potentially appear
            await password_tab_locator.wait_for(state="visible", timeout=5000)

            is_active = await password_tab_locator.evaluate("node => node.classList.contains('ds-tab--active')")

            if not is_active:
                print("检测到'密码登录'标签页非激活状态，尝试点击...")
                await password_tab_locator.click()
                print("已点击'密码登录'标签页。")
                await asyncio.sleep(random.uniform(1, 2)) # Wait for potential page changes
            else:
                print("[INFO] '密码登录'标签页已激活，无需点击。")

        except Exception as e:
            # Handles timeout (element not found) or other errors during check/click
            print(f"[INFO] 查找或点击'密码登录'标签页时出错或超时 (可能已在密码登录页): {e}。继续登录流程。")

        # 3. Select the least recently used account
        users = load_user_pool(user_pool_path)
        if not users:
            if context: await context.close() # Close context before raising
            raise Exception("user_pool.md 为空或无法加载。")
        user = users[0]
        print(f"使用账户: {user['username']}")

        # 4. Input account
        # Use the exact placeholder text from the HTML
        username_input = page.locator('input[placeholder="请输入手机号/邮箱地址"]')
        await username_input.wait_for(state="visible", timeout=10000)
        await username_input.fill(user['username'])
        await asyncio.sleep(random.uniform(0.5, 1))

        # 5. Input password
        # Use the exact placeholder text from the HTML
        password_input = page.locator('input[placeholder="请输入密码"]')
        await password_input.wait_for(state="visible", timeout=10000)
        await password_input.fill(user['password'])
        await asyncio.sleep(random.uniform(0.5, 1))

        # 6. Click login button
        login_button = page.locator('div[role="button"].ds-button--primary:has-text("登录")')
        await login_button.wait_for(state="visible", timeout=10000)
        await login_button.click()
        print('已点击登录')

        # 7. Wait for successful login
        await page.wait_for_selector("textarea", timeout=30000, state="visible")
        print("登录成功，已跳转到聊天页面。")

        # 8. Update login time
        update_user_login_time(user_pool_path, user['username'])
        print(f"已更新 {user['username']} 的登录时间")

    except Exception as e:
        print(f"登录过程中发生错误: {e}")
        # Attempt screenshot
        if 'page' in locals() and page and not page.is_closed():
             try:
                 await page.screenshot(path="login_error.png")
                 print("已保存登录错误截图: login_error.png")
             except Exception as screenshot_e:
                 print(f"保存截图失败: {screenshot_e}")
        # Close context if it was created before raising
        if context:
            await context.close()
        # Re-raise the exception for the caller
        raise e

    # If the try block succeeded, return context and page
    if context is None:
        raise Exception("未能成功创建浏览器上下文。")

    # Do NOT close context here, let the caller manage it
    return context, page

# Compatibility entry point (Needs modification to work)
def test_switch_user():
    print("警告：test_switch_user() 现在需要一个运行中的 Browser 实例来测试。")
    # Example of how to test if needed:
    # async def run_test():
    #     async with async_playwright() as p:
    #         browser = await p.chromium.launch(headless=False)
    #         try:
    #             context, page = await switch_user(browser, headless=False)
    #             print("Test switch_user successful.")
    #             # Add assertions or further interactions here if needed
    #         except Exception as e:
    #             print(f"Test switch_user failed: {e}")
    #         finally:
    #             if 'context' in locals() and context: await context.close()
    #             if browser: await browser.close()
    # asyncio.run(run_test())

if __name__ == "__main__":
    test_switch_user()
