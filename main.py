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
        # 确保 AI 生成包含 "用户登录" 标题的 HTML 页面
        await page.fill("textarea", "创建一个简单的 HTML 登录页面，包含一个 h2 标题 '用户登录'、用户名、密码输入框和登录按钮")

        # 等待发送按钮出现并点击
        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
        await page.click('div._7436101[role="button"][aria-disabled="false"]')

        # 等待 AI 回复生成完毕（通过检测复制按钮出现），增加超时时间
        copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
        print("等待 AI 回复生成完毕...")
        try:
            await page.wait_for_selector(copy_button_selector, timeout=120000) # 超时时间设为 120 秒
            print("检测到复制按钮，AI 回复已生成。")
        except Exception as e:
            print(f"等待复制按钮超时或出错: {e}")
            await context.close()
            return # 超时则退出

        # 获取 AI 回复内容
        content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
        content = await page.inner_text(content_selector)
        print("AI 回复内容已获取。")

        import os
        import re
        # 新建保存文件夹
        save_dir = "saved_outputs"
        os.makedirs(save_dir, exist_ok=True)
        # 优先判断是否为完整代码（以 < 或 <!DOCTYPE 开头），如果是则全部保存
        save_path = os.path.join(save_dir, "deepseek_reply.txt")
        content_strip = content.lstrip()
        if content_strip.startswith('<') or content_strip.lower().startswith('<!doctype'):
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"AI 回复内容（完整代码）已原样保存到 {save_path}")
        else:
            # 否则尝试提取代码块（优先考虑 ``` 包裹，其次缩进块）
            code_blocks = re.findall(r"```[\w]*\n([\s\S]*?)```", content)
            if not code_blocks:
                # 如果没有 markdown 代码块，尝试用缩进（4空格或tab）提取
                code_lines = []
                in_code = False
                for line in content.splitlines():
                    if line.strip() == '':
                        if in_code:
                            code_lines.append('')
                        continue
                    if (line.startswith('    ') or line.startswith('\t')):
                        code_lines.append(line)
                        in_code = True
                    else:
                        in_code = False
                code_content = '\n'.join(code_lines).strip()
            else:
                code_content = '\n\n'.join(code_blocks).strip()
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(code_content)
            print(f"AI 回复内容（代码块）已保存到 {save_path}")

        # 检测并点击 "运行 HTML" 按钮
        run_html_selector = 'div.md-code-block-footer span:has-text("运行 HTML")'
        clicked_run_html = False
        try:
            print("检测是否存在 '运行 HTML' 按钮...")
            if await page.locator(run_html_selector).count() > 0:
                await page.wait_for_selector(run_html_selector, state="visible", timeout=5000)
                await page.click(run_html_selector)
                print("已点击 '运行 HTML' 按钮。")
                clicked_run_html = True
            else:
                print("'运行 HTML' 按钮未找到。")
        except Exception as e:
            print(f"检测或点击 '运行 HTML' 按钮时出错: {e}")

        # 如果点击了运行按钮，则截图
        if clicked_run_html:
            iframe_selector = 'iframe[src="https://cdn.deepseek.com/usercontent/usercontent.html"]'
            # 等待 iframe 内特定的、代表核心内容的元素出现
            internal_element_selector = 'h2:has-text("用户登录")'
            screenshot_target_selector = 'body' # 仍然截图 body 以获取全貌
            import shutil
            screenshot_path = os.path.join(save_dir, 'rendered_html.png')
            try:
                print(f"等待 iframe '{iframe_selector}' 出现...")
                await page.wait_for_selector(iframe_selector, state="visible", timeout=10000)
                frame = page.frame_locator(iframe_selector)
                print(f"成功定位 iframe。等待 iframe 内特定元素 '{internal_element_selector}' 加载并可见...")
                # 增加 iframe 内部等待时间，并等待特定元素
                await frame.locator(internal_element_selector).wait_for(state="visible", timeout=45000)
                print(f"iframe 内特定元素 '{internal_element_selector}' 已可见。");
                # 等待片刻确保渲染稳定
                await asyncio.sleep(1)
                await frame.locator(screenshot_target_selector).screenshot(path=screenshot_path)
                print(f"已将 iframe 内 body 截图保存到 {screenshot_path}")
            except Exception as e:
                print(f"截图失败: 无法定位 iframe '{iframe_selector}' 或无法在 iframe 内定位/等待 '{internal_element_selector}' 或截图 '{screenshot_target_selector}' 时超时/出错: {e}")


        await asyncio.Event().wait()
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())