import asyncio
from playwright.async_api import async_playwright

async def wait_for_stable_content(page, selector, check_interval=1.0, stable_times=3, timeout=60):
    """等待 selector 内容稳定（连续 stable_times 次内容一致）"""
    last_content = None
    stable_count = 0
    elapsed = 0
    while elapsed < timeout:
        try:
            content = await page.inner_text(selector)
        except Exception:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            continue
        if content == last_content:
            stable_count += 1
        else:
            stable_count = 1
            last_content = content
        if stable_count >= stable_times:
            return content
        await asyncio.sleep(check_interval)
        elapsed += check_interval
    return last_content

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
        await page.fill("textarea", "介绍一下什么是哲学")

        # 等待发送按钮出现并点击
        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
        await page.click('div._7436101[role="button"][aria-disabled="false"]')

        # 等待 AI 回复内容出现并稳定
        await page.wait_for_selector('.ds-markdown.ds-markdown--block')
        print("等待 AI 回复生成完毕...")
        content = await wait_for_stable_content(page, '.ds-markdown.ds-markdown--block')
        print("AI 回复内容：", content)

        # 保存到本地 markdown 文件
        with open("deepseek_reply.md", "w", encoding="utf-8") as f:
            f.write(content)

        await asyncio.Event().wait()
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())