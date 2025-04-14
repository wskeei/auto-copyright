import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # 使用自定义 user_data_dir 保存 Chromium 登录信息
        user_data_dir = "./user_data_chromium"
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled"
            ]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://chat.deepseek.com/")
        print("已打开 https://chat.deepseek.com/")

        # 等待输入框出现并输入内容
        await page.wait_for_selector("textarea")
        await page.fill("textarea", "你好，DeepSeek！")

        # 等待发送按钮出现并点击
        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
        await page.click('div._7436101[role="button"][aria-disabled="false"]')

        await asyncio.Event().wait()
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())