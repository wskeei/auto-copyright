import asyncio
from playwright.async_api import async_playwright, Browser, Page, BrowserContext # Import types
import os
import re
import random
import time # Import time for potential delays
# Import the modified switch_user which only returns credentials
from concurrent_test_user_switch import switch_user, load_user_pool

# --- Helper Functions (Keep as they are) ---
async def random_human_delay(min_sec=1, max_sec=3):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def refresh_retry_click(page: Page):
    btns = await page.query_selector_all('.ds-icon-button')
    for btn in btns:
        rect = await btn.query_selector('rect[id="重新生成"]')
        if rect is not None:
            print("找到带有 id=重新生成 的 rect，点击父按钮！")
            await btn.click()
            return
    # If button not found, maybe log instead of raising immediately in concurrent context
    print('[WARN] 未找到"重新生成"按钮，无法自动重试！')
    # raise Exception('未找到"重新生成"按钮，无法自动重试！')

async def auto_continue_generate(page: Page, max_loops=10):
    btn_selector = 'div[role="button"].ds-button--secondary:has-text("继续生成")'
    for i in range(max_loops):
        # Use locator for potentially more robust checking
        continue_button = page.locator(btn_selector).first
        if await continue_button.is_visible(timeout=1000): # Check visibility briefly
            print(f"检测到'继续生成'按钮，第{i+1}次点击...")
            try:
                await continue_button.click()
                await asyncio.sleep(2)  # Wait for AI to continue generating
                await page.wait_for_timeout(2000) # Additional wait
            except Exception as click_err:
                print(f"[WARN] 点击'继续生成'按钮时出错: {click_err}")
                break # Stop trying if click fails
        else:
            break
    print("已无'继续生成'按钮，继续后续流程。")

def get_ai_prompts(ai_prompt_path):
    with open(ai_prompt_path, encoding="utf-8") as f:
        text = f.read()
    match1 = re.search(r"# AI角色设定[\s\n]+([\s\S]+?)(?=^#|\Z)", text, re.MULTILINE)
    ai_role = match1.group(1).strip() if match1 else ""
    match2 = re.search(r"# 02 AI 角色设定[\s\n]+([\s\S]+?)(?=^#|\Z)", text, re.MULTILINE)
    ai_doc = match2.group(1).strip() if match2 else ""
    return ai_role, ai_doc

def get_user_prompts(user_prompt_path):
    with open(user_prompt_path, encoding="utf-8") as f:
        text = f.read()
    blocks = re.split(r"^# +", text, flags=re.MULTILINE)
    prompts = []
    for block in blocks[1:]:
        lines = block.splitlines()
        title = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        prompts.append((title, content))
    return prompts

def safe_filename(title):
    name = re.sub(r"[^\u4e00-\u9fa5\w]+", "_", title)
    name = name.strip("_")
    return name

# --- New function to handle browser tasks for a single prompt ---
async def run_browser_task(
    browser: Browser,
    selected_user: dict,
    ai_role: str,
    ai_doc: str,
    user_title: str,
    user_content: str,
    save_dir: str
):
    """
    Handles the browser interaction for a single prompt using a new isolated context.
    Logs in, sends prompts, saves results.
    """
    context: BrowserContext | None = None
    page: Page | None = None
    task_id = f"{selected_user['username']}-{safe_filename(user_title)}" # Unique ID for logging

    print(f"[{task_id}] 开始浏览器任务...")
    try:
        # 1. Create new isolated context
        print(f"[{task_id}] 创建新的浏览器上下文...")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            java_script_enabled=True,
            accept_downloads=True,
        )
        page = await context.new_page()
        print(f"[{task_id}] 新上下文和页面已创建。")

        # 2. Navigate and Login
        await page.goto("https://chat.deepseek.com/")
        await asyncio.sleep(random.uniform(2, 4))

        # --- Execute Login Steps ---
        print(f"[{task_id}] 执行登录步骤...")
        try:
            # Attempt to switch to password login tab if needed
            password_tab_locator = page.locator('div.ds-tab:has-text("密码登录")')
            await password_tab_locator.wait_for(state="visible", timeout=5000)
            is_active = await password_tab_locator.evaluate("node => node.classList.contains('ds-tab--active')")
            if not is_active:
                print(f"[{task_id}] 点击'密码登录'标签页...")
                await password_tab_locator.click()
                await asyncio.sleep(random.uniform(1, 2))
            else:
                print(f"[{task_id}] '密码登录'标签页已激活。")
        except Exception as e:
            print(f"[{task_id}][INFO] 查找或点击'密码登录'时出错或超时: {e}")

        # Input username (Use updated locator)
        username_input = page.locator('input[placeholder="请输入手机号/邮箱地址"]')
        await username_input.wait_for(state="visible", timeout=10000)
        await username_input.fill(selected_user['username'])
        await asyncio.sleep(random.uniform(0.5, 1))

        # Input password (Use updated locator)
        password_input = page.locator('input[placeholder="请输入密码"]')
        await password_input.wait_for(state="visible", timeout=10000)
        await password_input.fill(selected_user['password'])
        await asyncio.sleep(random.uniform(0.5, 1))

        # Click login button (Use updated locator)
        login_button = page.locator('div[role="button"].ds-button--primary:has-text("登录")')
        await login_button.wait_for(state="visible", timeout=10000)
        await login_button.click()
        print(f"[{task_id}] 已点击登录按钮。")

        # Wait for successful login
        await page.wait_for_selector("textarea", timeout=30000, state="visible")
        print(f"[{task_id}] 登录成功。")
        # --- Login Complete ---

        # 3. Process the actual prompt (adapted from old process_prompt)
        print(f"[{task_id}] 处理提示: {user_title}")
        await random_human_delay()
        # Ensure textarea is ready after login/navigation
        await page.wait_for_selector("textarea")

        # --- First Prompt (Code Generation) ---
        prompt_code = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
        await page.fill("textarea", prompt_code)
        send_button_selector = 'div._7436101[role="button"]'
        await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]')
        await page.click(f'{send_button_selector}[aria-disabled="false"]')
        copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
        print(f"[{task_id}] 等待 AI 代码回复...")

        try:
            await page.wait_for_selector(copy_button_selector, timeout=600000)
            print(f"[{task_id}] AI 代码已生成。")
            content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
            retry_busy = 0
            while True:
                await random_human_delay(0.5, 1.5)
                response_blocks = await page.query_selector_all(content_selector)
                if not response_blocks: raise Exception("无法找到 AI 回复内容块。")
                content = await response_blocks[-1].inner_text()

                if '服务器繁忙，请稍后再试' in content:
                    retry_busy += 1
                    if retry_busy > 2:
                        print(f'[{task_id}] 服务器持续繁忙，放弃代码生成。')
                        raise Exception("服务器持续繁忙，无法完成代码生成。")
                    print(f'[{task_id}] 检测到"服务器繁忙"，尝试刷新重试...')
                    await refresh_retry_click(page)
                    await asyncio.sleep(5)
                    await page.wait_for_selector(copy_button_selector, timeout=600000)
                    continue
                break

            await auto_continue_generate(page)
            print(f"[{task_id}] AI 代码内容已获取。")
            response_blocks = await page.query_selector_all(content_selector) # Re-fetch after continue
            if not response_blocks: raise Exception("继续生成后无法找到内容块。")
            final_content = await response_blocks[-1].inner_text()

            # Save HTML
            file_base = safe_filename(user_title)
            html_dir = os.path.join(save_dir, "html")
            os.makedirs(html_dir, exist_ok=True)
            html_path = os.path.join(html_dir, f"{file_base}.html")
            html_match = re.search(r'(<!DOCTYPE html[\s\S]*?</html>)', final_content, re.IGNORECASE)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_match.group(1) if html_match else final_content)
            print(f"[{task_id}] AI 代码已保存到 {html_path}")

            # --- Handle "Run HTML" and Second Prompt ---
            run_html_selector = 'div.md-code-block-footer span:has-text("运行 HTML")'
            clicked_run_html = False
            try:
                run_html_button = page.locator(run_html_selector).last
                if await run_html_button.count() > 0 and await run_html_button.is_visible(timeout=5000):
                    await run_html_button.click()
                    print(f"[{task_id}] 已点击 '运行 HTML' 按钮。")
                    clicked_run_html = True
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"[{task_id}][WARN] 检测或点击 '运行 HTML' 按钮时出错: {e}")

            if clicked_run_html:
                print(f"[{task_id}] 刷新页面准备第二个 prompt...")
                await page.reload()
                await page.wait_for_selector("#chat-input", timeout=60000)
                await page.focus("#chat-input")
                await page.fill("#chat-input", "")
                await asyncio.sleep(0.2)
                # Type second prompt carefully
                for c in ai_doc:
                    if c == '\n': await page.keyboard.press('Shift+Enter')
                    else: await page.keyboard.type(c, delay=10) # Add small delay
                print(f"[{task_id}] 第二个 prompt 输入完毕。")
            else:
                 print(f"[{task_id}] 直接输入第二个 prompt...")
                 await page.focus("#chat-input")
                 await page.fill("#chat-input", "")
                 await asyncio.sleep(0.2)
                 await page.fill("#chat-input", ai_doc)
                 await asyncio.sleep(0.5)

        except Exception as first_prompt_err:
            print(f"[{task_id}][ERROR] 处理第一个 prompt 或保存 HTML 时出错: {first_prompt_err}")
            raise # Re-raise to be caught by outer try

        # --- Second Prompt (Description Generation) ---
        print(f"[{task_id}] 发送第二个 prompt (说明)...")
        try:
            await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]', timeout=10000)
            await page.click(f'{send_button_selector}[aria-disabled="false"]')
            print(f"[{task_id}] 等待 AI 说明生成...")
            await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]', timeout=600000)
            print(f"[{task_id}] AI 说明可能已生成。")
            await asyncio.sleep(2)

            retry_busy = 0
            final_doc_content = "[说明获取失败]" # Default
            while True:
                await random_human_delay(0.5, 1.5)
                response_blocks = await page.query_selector_all(content_selector)
                if not response_blocks:
                     print(f"[{task_id}][WARN] 未找到说明回复块。")
                     break # Exit loop if no content found
                doc_content = await response_blocks[-1].inner_text()

                if '服务器繁忙，请稍后再试' in doc_content:
                    retry_busy += 1
                    if retry_busy > 2:
                        print(f'[{task_id}] 说明生成服务器持续繁忙，跳过。')
                        final_doc_content = "[说明生成失败：服务器持续繁忙]"
                        break
                    print(f'[{task_id}] 说明生成遇服务器繁忙，尝试刷新...')
                    await refresh_retry_click(page)
                    await asyncio.sleep(5)
                    await page.wait_for_selector(f'{send_button_selector}[aria-disabled="false"]', timeout=600000)
                    await asyncio.sleep(2)
                    continue
                # Success case
                await auto_continue_generate(page) # Continue if needed
                response_blocks = await page.query_selector_all(content_selector) # Re-fetch
                if response_blocks: final_doc_content = await response_blocks[-1].inner_text()
                else: final_doc_content = "[说明获取失败：继续生成后未找到内容]"
                print(f"[{task_id}] AI 说明内容已获取。")
                break # Exit loop on success

            # Save description
            doc_path = os.path.join(save_dir, "软件说明.md")
            with open(doc_path, "a", encoding="utf-8") as f:
                f.write(f"\n# {user_title}\n\n{final_doc_content.strip()}\n")
            print(f"[{task_id}] AI 说明已追加到 {doc_path}")

        except Exception as second_prompt_err:
            print(f"[{task_id}][ERROR] 处理第二个 prompt 或保存说明时出错: {second_prompt_err}")
            # Log error to file
            doc_path = os.path.join(save_dir, "软件说明.md")
            with open(doc_path, "a", encoding="utf-8") as f:
                 f.write(f"\n# {user_title}\n\n[处理第二个 prompt 时出错: {second_prompt_err}]\n")

        print(f"[{task_id}] 浏览器任务完成。")

    except Exception as task_err:
        print(f"[{task_id}][ERROR] 浏览器任务执行期间发生错误: {task_err}")
        # Attempt screenshot if page exists
        if page and not page.is_closed():
             try:
                 screenshot_path = f"task_error_{task_id}.png"
                 await page.screenshot(path=screenshot_path)
                 print(f"[{task_id}] 已保存任务错误截图: {screenshot_path}")
             except Exception as screenshot_e:
                 print(f"[{task_id}] 保存任务错误截图失败: {screenshot_e}")
        # Re-raise the error so the main loop knows the task failed
        raise
    finally:
        # Ensure context is closed for this task
        if context:
            print(f"[{task_id}] 关闭浏览器上下文...")
            try:
                await context.close()
                print(f"[{task_id}] 上下文已关闭。")
            except Exception as close_err:
                print(f"[{task_id}][WARN] 关闭上下文时出错: {close_err}")

# --- Main Function ---
async def main():
    import glob
    import time
    CONCURRENCY_LIMIT = 3 # Set concurrency limit
    print(f"[LOG] 开始批量处理，并发限制: {CONCURRENCY_LIMIT}")
    file_lock = asyncio.Lock()
    active_users_lock = asyncio.Lock()
    active_users = set()
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT) # Semaphore for browser tasks

    # Check account pool size (optional but recommended)
    user_pool_path = 'user_pool.md'
    try:
        # Use run_in_executor as load_user_pool is sync
        loop = asyncio.get_running_loop()
        async with file_lock: # Need lock if load_user_pool writes back
             users_check = await loop.run_in_executor(None, load_user_pool, user_pool_path)
        if len(users_check) < CONCURRENCY_LIMIT:
            print(f"[WARNING] 账户池 ({len(users_check)}) 少于并发限制 ({CONCURRENCY_LIMIT})。")
    except Exception as e:
        print(f"[ERROR] 加载账户池检查失败: {e}")
        # Decide if to continue or exit

    print("[LOG] 扫描所有 user_prompt.md 文件...")
    user_prompt_dir = "user_prompt.md"
    user_prompt_files = sorted(
        glob.glob(os.path.join(user_prompt_dir, "[0-9][0-9] *.md")),
        key=lambda x: int(os.path.basename(x).split()[0])
    )
    print(f"[LOG] 共找到 {len(user_prompt_files)} 个 user_prompt.md 文件。")
    ai_prompt_path = "AI_prompt.md"
    if not os.path.exists(ai_prompt_path):
        print(f"[ERROR] {ai_prompt_path} 文件不存在，退出！")
        return
    ai_role, ai_doc = get_ai_prompts(ai_prompt_path)

    async with async_playwright() as p:
        browser = None
        try:
            print("[LOG] 启动浏览器实例...")
            browser = await p.chromium.launch(headless=False) # Launch one browser instance
            print("[LOG] 浏览器实例已启动。")

            all_tasks = [] # List to hold all task references

            for idx, user_prompt_path in enumerate(user_prompt_files):
                basename_no_ext = os.path.splitext(os.path.basename(user_prompt_path))[0]
                save_dir = os.path.join("saved_outputs", basename_no_ext)
                os.makedirs(save_dir, exist_ok=True)
                print(f"\n[LOG] 准备处理文件 {idx+1}/{len(user_prompt_files)}: {user_prompt_path}")

                user_prompts = get_user_prompts(user_prompt_path)
                match = re.match(r"\d+\s*(.*)", basename_no_ext)
                software_name = match.group(1) if match else basename_no_ext
                ai_role_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_role)
                ai_doc_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_doc)

                # Create tasks for each prompt within the file
                for prompt_idx, (user_title, user_content) in enumerate(user_prompts):
                    # Create a wrapper task to handle user selection, browser task execution, and user release
                    task = asyncio.create_task(
                        process_single_prompt_concurrently(
                            browser, file_lock, active_users_lock, active_users, semaphore,
                            ai_role_dynamic, ai_doc_dynamic, user_title, user_content, save_dir
                        )
                    )
                    all_tasks.append(task)

                # Optional: Wait between processing different user_prompt files
                if idx < len(user_prompt_files) - 1:
                     print(f"[LOG] 文件 {user_prompt_path} 的任务已创建，等待半小时后创建下一个文件的任务...")
                     # Note: This wait happens *before* the tasks for the current file might be finished.
                     # If you want to wait *after* a file's tasks are done, move this wait
                     # after the asyncio.gather below (but that would make it sequential per file).
                     wait_seconds = 30 * 60
                     for remain in range(wait_seconds, 0, -60):
                         print(f"[LOG] 剩余等待时间: {remain//60} 分钟...")
                         await asyncio.sleep(60)

            # Wait for all created tasks to complete
            print(f"[LOG] 所有任务已创建 ({len(all_tasks)} 个)，等待全部完成...")
            await asyncio.gather(*all_tasks, return_exceptions=True) # Gather results/exceptions
            print("[LOG] 所有并发任务已处理完毕。")

        except Exception as main_err:
             print(f"[ERROR] 主流程发生错误: {main_err}")
        finally:
            # Ensure the main browser instance is closed
            if browser:
                print("[LOG] 关闭主浏览器实例...")
                await browser.close()
                print("[LOG] 主浏览器实例已关闭。")

    print("[LOG] 全部处理流程完成！")

async def process_single_prompt_concurrently(
    browser: Browser,
    file_lock: asyncio.Lock,
    active_users_lock: asyncio.Lock,
    active_users: set,
    semaphore: asyncio.Semaphore,
    ai_role: str,
    ai_doc: str,
    user_title: str,
    user_content: str,
    save_dir: str
):
    """
    Wrapper function for a single prompt task: selects user, runs browser task, releases user.
    Controlled by semaphore.
    """
    selected_user = None
    task_id_prefix = safe_filename(user_title) # For logging

    async with semaphore: # Acquire semaphore slot
        print(f"[{task_id_prefix}] 获取到信号量，开始处理...")
        try:
            # 1. Select user (concurrency safe)
            print(f"[{task_id_prefix}] 尝试选择用户...")
            selected_user = await switch_user(file_lock, active_users_lock, active_users)
            print(f"[{task_id_prefix}] 成功选择用户: {selected_user['username']}")

            # 2. Run the browser task
            await run_browser_task(
                browser, selected_user, ai_role, ai_doc, user_title, user_content, save_dir
            )
            print(f"[{task_id_prefix}] 浏览器任务成功完成 for user {selected_user['username']}")

        except Exception as e:
            print(f"[{task_id_prefix}][ERROR] 处理时发生错误: {e}")
            # Error is logged, task will finish

        finally:
            # 3. Release user (concurrency safe)
            if selected_user:
                async with active_users_lock:
                    if selected_user['username'] in active_users:
                        active_users.remove(selected_user['username'])
                        print(f"[{task_id_prefix}] 释放用户: {selected_user['username']}")
                    else:
                        # This might happen if switch_user failed after adding the user but before returning
                        print(f"[{task_id_prefix}][WARN] 尝试释放用户 {selected_user['username']} 但其不在活跃集合中。")
            else:
                 print(f"[{task_id_prefix}][WARN] 任务结束时无用户可释放 (可能选择用户时失败)。")

            print(f"[{task_id_prefix}] 处理结束，释放信号量。")


if __name__ == "__main__":
    # Ensure necessary directories exist
    os.makedirs("./user_data_concurrent", exist_ok=True) # If run_browser_task needs it (it doesn't with new_context)
    os.makedirs("./saved_outputs", exist_ok=True)
    asyncio.run(main())