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
    :param headless: 是否无头运行
    :return: None
    """
    user_pool_path = 'user_pool.md'
    user_data_dir = './user_data_chromium'
    # 1. 清除用户登录信息
    if os.path.exists(user_data_dir):
        import shutil
        shutil.rmtree(user_data_dir)
        print(f"已清理 {user_data_dir}")
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(user_data_dir, headless=headless)
        page = browser.pages[0] if browser.pages else await browser.new_page()
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
        # 3. 选取最久未登录的账户
        users = load_user_pool(user_pool_path)
        user = users[0]
        print(f"使用账户: {user['username']}")
        # 4. 输入账户
        inputs = await page.query_selector_all('input.ds-input__input[type="text"]')
        if not inputs:
            raise Exception('未找到用户名输入框')
        await inputs[0].fill(user['username'])
        await asyncio.sleep(random.uniform(1,2))
        # 5. 输入密码
        pw_inputs = await page.query_selector_all('input.ds-input__input[type="password"]')
        if not pw_inputs:
            raise Exception('未找到密码输入框')
        await pw_inputs[0].fill(user['password'])
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
        await asyncio.sleep(5)
        # 7. 更新登录时间
        update_user_login_time(user_pool_path, user['username'])
        print(f"已更新 {user['username']} 的登录时间")
        await browser.close()

# 兼容原有测试入口
def test_switch_user():
    asyncio.run(switch_user(headless=False))

if __name__ == "__main__":
    test_switch_user()
