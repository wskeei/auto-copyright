import asyncio
from playwright.async_api import async_playwright
import os
import re
import random
import shutil # Import shutil here as it might be needed if we re-introduce cleaning later, but not currently used in main logic
from test_user_switch import switch_user

async def random_human_delay(min_sec=1, max_sec=3):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# 工具函数：自动查找并点击"重新生成"按钮
async def refresh_retry_click(page):
    btns = await page.query_selector_all('.ds-icon-button')
    for btn in btns:
        rect = await btn.query_selector('rect[id="重新生成"]')
        if rect is not None:
            print("找到带有 id=重新生成 的 rect，点击父按钮！")
            await btn.click()
            return
    raise Exception('未找到"重新生成"按钮，无法自动重试！')

# 工具函数：自动点击"继续生成"直到无按钮
async def auto_continue_generate(page, max_loops=10):
    """
    检查并自动点击"继续生成"按钮，直到按钮消失或达到最大次数。
    """
    btn_selector = 'div[role="button"].ds-button--secondary:has-text("继续生成")'
    for i in range(max_loops):
        btns = await page.query_selector_all(btn_selector)
        if btns:
            print(f"检测到'继续生成'按钮，第{i+1}次点击...")
            await btns[0].click()
            await asyncio.sleep(2)  # 等待AI继续生成
            # 可适当等待内容变化或按钮消失
            await page.wait_for_timeout(2000)
        else:
            break
    print("已无'继续生成'按钮，继续后续流程。")

# 解析 AI_prompt.md，获取两个角色设定内容
# 返回 (ai_role_content, ai_doc_content)
def get_ai_prompts(ai_prompt_path):
    with open(ai_prompt_path, encoding="utf-8") as f:
        text = f.read()
    # AI角色设定
    match1 = re.search(r"# AI角色设定[\s\n]+([\s\S]+?)(?=^#|\Z)", text, re.MULTILINE)
    ai_role = match1.group(1).strip() if match1 else ""
    # 02 AI 角色设定
    match2 = re.search(r"# 02 AI 角色设定[\s\n]+([\s\S]+?)(?=^#|\Z)", text, re.MULTILINE)
    ai_doc = match2.group(1).strip() if match2 else ""
    return ai_role, ai_doc

# 解析 user_prompt.md（实际为 uer_prompt.md），获取所有一级标题和内容
# 返回 [(标题, 内容), ...]
def get_user_prompts(user_prompt_path):
    with open(user_prompt_path, encoding="utf-8") as f:
        text = f.read()
    blocks = re.split(r"^# +", text, flags=re.MULTILINE)
    prompts = []
    for block in blocks[1:]:  # 第一个为空
        lines = block.splitlines()
        title = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        prompts.append((title, content))
    return prompts

# 文件名安全处理
def safe_filename(title):
    name = re.sub(r"[^\u4e00-\u9fa5\w]+", "_", title)  # 只保留中英文、数字、下划线
    name = name.strip("_")
    return name

async def process_prompt(page, ai_role, ai_doc, user_title, user_content, save_dir):
    """处理单个用户提示，使用传入的 Page 对象"""
    # context and page are now passed in.

    # Ensure page is usable (optional check)
    if page.is_closed():
        raise Exception("Page object is closed at the start of process_prompt.")
    if "chat.deepseek.com" not in page.url:
         print(f"[WARN] Page URL is '{page.url}', expected 'chat.deepseek.com'. Navigating...")
         try:
             await page.goto("https://chat.deepseek.com/")
             await page.wait_for_load_state('networkidle') # Wait for navigation
         except Exception as nav_e:
             raise Exception(f"Failed to navigate page to chat.deepseek.com: {nav_e}")

    print(f"使用页面处理：{user_title}")
    await random_human_delay()
    await page.wait_for_selector("textarea") # Ensure input area is ready

    # 1. Combine and send the first prompt
    prompt_code = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
    await random_human_delay()
    await page.fill("textarea", prompt_code)
    send_button_selector = 'div._7436101[role="button"]' # Define send button selector once
    await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]')
    await random_human_delay()
    await page.click(f'{send_button_selector}[aria-disabled="false"]')
    copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
    print("等待 AI 代码回复生成完毕...")

    # --- Wait for first response and save HTML ---
    try:
        await page.wait_for_selector(copy_button_selector, timeout=600000)
        await random_human_delay()
        print("检测到复制按钮，AI 代码已生成。")
        content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
        retry_busy = 0
        while True:
            await random_human_delay()
            # Get the latest response block's content
            response_blocks = await page.query_selector_all(content_selector)
            if not response_blocks:
                 raise Exception("无法找到 AI 回复内容块。")
            content = await response_blocks[-1].inner_text() # Get text from the last block

            if '服务器繁忙，请稍后再试' in content:
                retry_busy += 1
                if retry_busy > 2:
                    print('检测到服务器繁忙且刷新2次无效，将抛出异常由主循环处理...')
                    raise Exception("服务器持续繁忙，无法完成处理。")
                print('检测到"服务器繁忙"，自动点击刷新按钮重试...')
                await refresh_retry_click(page)
                await asyncio.sleep(5) # Longer wait after refresh
                await page.wait_for_selector(copy_button_selector, timeout=600000) # Wait for response again
                continue
            break # Exit loop if not busy

        await random_human_delay()
        await auto_continue_generate(page) # Click "Continue generating" if present
        print("AI 代码内容已获取。")

        # Re-fetch content after potential continuation
        response_blocks = await page.query_selector_all(content_selector)
        if not response_blocks:
             raise Exception("无法找到 AI 回复内容块 (继续生成后)。")
        final_content = await response_blocks[-1].inner_text()

        file_base = safe_filename(user_title)
        html_dir = os.path.join(save_dir, "html")
        os.makedirs(html_dir, exist_ok=True)
        await random_human_delay()
        html_path = os.path.join(html_dir, f"{file_base}.html")
        html_match = re.search(r'(<!DOCTYPE html[\s\S]*?</html>)', final_content, re.IGNORECASE)
        with open(html_path, "w", encoding="utf-8") as f:
            if html_match:
                f.write(html_match.group(1))
            else:
                f.write(final_content) # Save full content if no doctype found
        await random_human_delay()
        print(f"AI 代码已保存到 {html_path}")

        # --- Handle "Run HTML" and second prompt ---
        run_html_selector = 'div.md-code-block-footer span:has-text("运行 HTML")'
        clicked_run_html = False
        try:
            print("检测是否存在 '运行 HTML' 按钮...")
            run_html_button = page.locator(run_html_selector).last # Target the last button if multiple
            if await run_html_button.count() > 0 and await run_html_button.is_visible(timeout=5000):
                await run_html_button.click()
                print("已点击 '运行 HTML' 按钮。")
                clicked_run_html = True
                await asyncio.sleep(2) # Wait after clicking run
            else:
                print("'运行 HTML' 按钮未找到或不可见。")
        except Exception as e:
            print(f"检测或点击 '运行 HTML' 按钮时出错: {e}")

        # If "Run HTML" was clicked, reload and prepare for the second prompt
        if clicked_run_html:
            try:
                print("点击 '运行 HTML' 后刷新页面，重置状态...")
                await page.reload()
                await page.wait_for_selector("#chat-input", timeout=60000)
                await asyncio.sleep(1)
                # Ensure input is ready and clear
                await page.focus("#chat-input")
                await page.fill("#chat-input", "")
                await asyncio.sleep(0.2)
                # Type the second prompt carefully
                for c in ai_doc:
                    if c == '\n':
                        await page.keyboard.down('Shift')
                        await page.keyboard.press('Enter')
                        await page.keyboard.up('Shift')
                    else:
                        await page.keyboard.type(c)
                    await asyncio.sleep(0.01) # Small delay between chars
                # Verify input
                current_text = await page.input_value("#chat-input")
                if current_text.strip() != ai_doc.strip():
                     print(f"[WARN] 输入框内容 ('{current_text[:50]}...') 与预期 ('{ai_doc[:50]}...') 不符，尝试重新输入。")
                     await page.fill("#chat-input", ai_doc) # Force fill as fallback
                     await asyncio.sleep(0.5)
                print("准备发送 02 AI 角色设定 prompt")
            except Exception as e:
                print(f"刷新页面或准备第二个 prompt 时出错: {e}")
                # Decide if we should continue or raise
                raise Exception(f"无法准备第二个 prompt: {e}") # Raise by default
        else:
             # If "Run HTML" not clicked, directly input the second prompt
             try:
                 await page.focus("#chat-input")
                 await page.fill("#chat-input", "") # Clear first
                 await asyncio.sleep(0.2)
                 await page.fill("#chat-input", ai_doc) # Fill directly
                 await asyncio.sleep(0.5)
                 print("准备发送 02 AI 角色设定 prompt (未点击运行HTML)")
             except Exception as e:
                 raise Exception(f"无法输入第二个 prompt (未点击运行HTML): {e}")

    except Exception as e:
        print(f"处理第一个 prompt 或保存 HTML 时出错: {e}")
        raise # Re-raise the exception to be caught by the main loop

    # --- Send second prompt and save description ---
    print("发送 02 AI 角色设定 prompt...")
    try:
        # AI生成过程中为false，空的就是为true，输入内容后为flase
        # Ensure send button is enabled before clicking
        await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]', timeout=10000)
        await page.click(f'{send_button_selector}[aria-disabled="false"]')
        print("已点击发送按钮，等待 AI 说明生成...")
        await asyncio.sleep(10) 
        # 增加10S延迟，严重怀疑是因为发送过程中卡住了，导致判断失败
        print("10S延迟结束")
        # Wait for the response to complete (e.g., wait for send button to be enabled again)
        await page.wait_for_selector(f'{send_button_selector}[aria-disabled="true"]', timeout=600000) # Wait up to 10 mins
        print("检测到发送按钮再次可用，AI 说明可能已生成。")
        await asyncio.sleep(2) # Extra wait for content to settle

        # Check for busy server in the latest response
        retry_busy = 0
        while True:
            await random_human_delay()
            response_blocks = await page.query_selector_all(content_selector)
            if not response_blocks:
                 raise Exception("无法找到 AI 说明回复块。")
            doc_content = await response_blocks[-1].inner_text() # Get text from the last block

            if '服务器繁忙，请稍后再试' in doc_content:
                retry_busy += 1
                if retry_busy > 2:
                    print('说明生成遇到服务器繁忙且刷新2次无效，跳过本次说明生成。')
                    doc_content = "[说明生成失败：服务器持续繁忙]" # Mark as failed
                    break # Exit loop, save failure message
                print('说明生成遇到"服务器繁忙"，自动点击刷新按钮重试...')
                await refresh_retry_click(page)
                await asyncio.sleep(5)
                # Wait for send button to be enabled again after refresh
                await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]', timeout=600000)
                await asyncio.sleep(2)
                continue # Retry getting content
            break # Exit loop if not busy

        await auto_continue_generate(page) # Click "Continue generating" for description if present
        print("AI 说明内容已获取。")

        # Re-fetch final description content after potential continuation
        response_blocks = await page.query_selector_all(content_selector)
        if not response_blocks:
             final_doc_content = "[说明获取失败：未找到内容块]"
        else:
             final_doc_content = await response_blocks[-1].inner_text()


        doc_path = os.path.join(save_dir, "软件说明.md")
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write(f"\n# {user_title}\n\n{final_doc_content.strip()}\n")
        print(f"AI 说明已追加到 {doc_path}")

    except Exception as e:
        print(f"处理第二个 prompt 或保存说明时出错: {e}")
        # Save error to the description file
        doc_path = os.path.join(save_dir, "软件说明.md")
        with open(doc_path, "a", encoding="utf-8") as f:
             f.write(f"\n# {user_title}\n\n[处理第二个 prompt 时出错: {e}]\n")
        # Don't raise here, allow the main loop to continue to the next prompt/file if desired

async def main():
    import glob
    import time
    # 日志：开始批量处理
    print("[LOG] 扫描所有 user_prompt.md 文件...")
    # 查找所有形如 '?? xxx.md' 的文件，按数字顺序排列
    user_prompt_dir = "user_prompt.md"
    user_prompt_files = sorted(
        glob.glob(os.path.join(user_prompt_dir, "[0-9][0-9] *.md")),
        key=lambda x: int(os.path.basename(x).split()[0])
    )
    print(f"[LOG] 共找到 {len(user_prompt_files)} 个 user_prompt.md 文件: {user_prompt_files}")
    ai_prompt_path = "AI_prompt.md"
    # 检查 AI_prompt.md 是否存在
    if not os.path.exists(ai_prompt_path):
        print(f"[ERROR] {ai_prompt_path} 文件不存在，退出！")
        return
    ai_role, ai_doc = get_ai_prompts(ai_prompt_path)

    async with async_playwright() as p:
        browser = None # Initialize browser variable
        try:
            print("[LOG] 启动浏览器实例...")
            # Launch a regular browser instance, not persistent context
            browser = await p.chromium.launch(headless=False)
            print("[LOG] 浏览器实例已启动。")

            # Process each user prompt file
            for idx, user_prompt_path in enumerate(user_prompt_files):
                basename_no_ext = os.path.splitext(os.path.basename(user_prompt_path))[0]
                save_dir = os.path.join("saved_outputs", basename_no_ext)
                os.makedirs(save_dir, exist_ok=True)
                print(f"\n[LOG] 开始处理文件 {idx+1}/{len(user_prompt_files)}: {user_prompt_path}，输出目录：{save_dir}")

                try:
                    # 1. 获取此文件的所有 prompts
                    user_prompts = get_user_prompts(user_prompt_path)
                    match = re.match(r"\d+\s*(.*)", basename_no_ext)
                    software_name = match.group(1) if match else basename_no_ext
                    ai_role_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_role)
                    ai_doc_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_doc)

                    # 2. 遍历处理每个 prompt
                    for prompt_idx, (user_title, user_content) in enumerate(user_prompts):
                        print(f"\n[LOG] 开始处理标题 {prompt_idx+1}/{len(user_prompts)}：{user_title}")
                        current_context = None # Context per prompt
                        current_page = None
                        try:
                            # 2.1 切换用户（为每个 prompt 创建新的上下文和页面）
                            print("[LOG] 切换账户并创建新的浏览器上下文...")
                            current_context, current_page = await switch_user(browser, headless=False)
                            print("[LOG] 账户切换成功，获取到新的上下文和页面。")

                            # 2.2 处理当前 prompt
                            await process_prompt(current_page, ai_role_dynamic, ai_doc_dynamic, user_title, user_content, save_dir)
                            print(f"[LOG] 标题 '{user_title}' 处理完成。")

                        except Exception as prompt_e:
                            print(f"[ERROR] 处理标题 '{user_title}' 时出错: {prompt_e}")
                            if "服务器持续繁忙" in str(prompt_e):
                                print("[WARN] 因服务器持续繁忙，可能需要稍后重试该标题或文件。")
                                # 根据需要决定是否跳过文件剩余部分，这里选择继续处理下一个标题
                                # break # 如果需要跳过文件剩余部分，取消注释此行
                            else:
                                print("[WARN] 发生其他错误，继续处理下一个标题（如果可能）。")
                            # 即使 prompt 处理出错，也尝试关闭 context
                        finally:
                            # 关闭为当前 prompt 创建的上下文
                            if current_context:
                                print("[LOG] 关闭当前 prompt 的浏览器上下文...")
                                try:
                                    await current_context.close()
                                    print("[LOG] 上下文已关闭。")
                                except Exception as close_e:
                                    print(f"[ERROR] 关闭上下文时出错: {close_e}")
                            # 短暂等待，避免切换过快
                            await asyncio.sleep(5) # Wait 5 seconds between prompts

                    print(f"[LOG] 文件 {user_prompt_path} 内所有标题处理尝试完毕。")

                except Exception as file_e:
                    # 捕获文件级别的错误（例如 get_user_prompts 失败）
                    print(f"[ERROR] 处理文件 {user_prompt_path} 时发生错误: {file_e}")
                    # 这里不需要关闭 context，因为 context 是在内层循环管理的

                # 外层循环的 finally 块不再需要，因为 context 在内层管理
                # finally:
                #     pass # No context closing needed here anymore

                # Wait between files if not the last one
                if idx < len(user_prompt_files) - 1:
                    print("[LOG] 等待半小时后继续处理下一个 user_prompt.md ...")
                    wait_seconds = 30 * 60 # 1 minutes
                    for remain in range(wait_seconds, 0, -60):
                        print(f"[LOG] 剩余等待时间: {remain//60} 分钟...")
                        await asyncio.sleep(60)

        finally:
            # Ensure the main browser instance is closed after the loop finishes or if an error occurs
            if browser:
                print("[LOG] 关闭浏览器实例...")
                await browser.close()
                print("[LOG] 浏览器实例已关闭。")

    print("[LOG] 全部 user_prompt.md 文件处理完成！")

if __name__ == "__main__":
    asyncio.run(main())