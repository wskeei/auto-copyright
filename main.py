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
        await page.fill("textarea", "生成一个炫酷的前端界面！")

        # 等待发送按钮出现并点击
        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
        await page.click('div._7436101[role="button"][aria-disabled="false"]')

        # 等待 AI 回复生成完毕（通过检测复制按钮出现），增加超时时间
        copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
        print("等待 AI 回复生成完毕...")
        try:
            await page.wait_for_selector(copy_button_selector, timeout=600000) # 超时时间设为 600 秒
            print("检测到复制按钮，AI 回复已生成。")
        except Exception as e:
            print(f"等待复制按钮超时或出错: {e}")
            await context.close()
            return # 超时则退出

        # 获取 AI 回复内容
        content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
        content = await page.inner_text(content_selector)
        print("AI 回复内容：", content)

        # 保存到本地 markdown 文件
        with open("deepseek_reply.md", "w", encoding="utf-8") as f:
            f.write(content)

        await asyncio.Event().wait()
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())