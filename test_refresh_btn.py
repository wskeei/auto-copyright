import asyncio
from playwright.async_api import async_playwright

async def test_refresh_btn():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        # 打开你的目标页面（此处以 deepseek 为例）
        await page.goto("https://chat.deepseek.com/")
        print("请手动触发出现‘重新生成’按钮的场景，然后按回车继续...")
        input("按回车继续...")

        # 推荐的刷新按钮定位方式
        # 1. 先找到所有 .ds-icon-button
        btns = await page.query_selector_all('.ds-icon-button')
        found = False
        for btn in btns:
            # 2. 在每个按钮下找 rect[id="重新生成"]
            rect = await btn.query_selector('rect[id="重新生成"]')
            if rect is not None:
                found = True
                print("找到带有 id=重新生成 的 rect，点击父按钮！")
                await btn.click()
                break
        if not found:
            print("未找到可点击的‘重新生成’按钮！")
        await asyncio.sleep(3)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_refresh_btn())
