import asyncio
from playwright.async_api import async_playwright
import os
import re
import random
from test_user_switch import switch_user, load_user_pool # 导入 load_user_pool 用于检查账户数量

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

async def process_prompt(p, ai_role, ai_doc, user_title, user_content, save_dir, file_lock: asyncio.Lock, active_users_lock: asyncio.Lock, active_users: set, semaphore: asyncio.Semaphore):
    """处理单个用户提示（一级标题）的函数，受信号量控制并发，并确保使用独立账户和独立用户数据目录"""
    username_in_use = None # 用于 finally 块中释放用户
    # 为此任务生成唯一的用户数据目录路径
    safe_title = safe_filename(user_title)
    task_user_data_dir = os.path.join("./user_data_concurrent", safe_title) # 存放在子目录中

    async with semaphore: # 获取信号量，限制并发数
        print(f"[并发任务] 开始处理: {user_title} (数据目录: {task_user_data_dir})")
        context = None # Ensure context is defined for finally block
        try:
            # 切换用户，传递此任务的唯一数据目录、文件锁、活跃用户锁和集合
            username_in_use = await switch_user(task_user_data_dir, file_lock, active_users_lock, active_users, headless=False)
            if not username_in_use: # switch_user 内部应该抛异常，但以防万一
                 raise Exception("Switch user did not return a username.")

            # 使用此任务的唯一用户数据目录启动浏览器上下文
            print(f"[并发任务] 使用数据目录 {task_user_data_dir} 启动浏览器 for {user_title}")
            context = await p.chromium.launch_persistent_context(task_user_data_dir, headless=False, args=["--disable-blink-features=AutomationControlled"])
            page = context.pages[0] if context.pages else await context.new_page()

            try: # 这个 try 块包含了主要的浏览器交互逻辑
                await random_human_delay()
                await page.goto("https://chat.deepseek.com/")
                print(f"已打开 https://chat.deepseek.com/，处理：{user_title}")
                await random_human_delay()
                await page.wait_for_selector("textarea")
                # 1. 组合第一个 prompt，生成代码
                prompt_code = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
                await random_human_delay()
                await page.fill("textarea", prompt_code)
                await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
                await random_human_delay()
                await page.click('div._7436101[role="button"][aria-disabled="false"]')
                copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
                print("等待 AI 代码回复生成完毕...")
                try: # 内部 try 处理代码生成和保存
                    await page.wait_for_selector(copy_button_selector, timeout=600000)
                    await random_human_delay()
                    print("检测到复制按钮，AI 代码已生成。")
                    # 保存 HTML 文件
                    content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
                    # 检查是否遇到服务器繁忙提示，若是则自动刷新重试
                    retry_busy = 0
                    while True:
                        await random_human_delay()
                        content = await page.inner_text(content_selector)
                        if '服务器繁忙，请稍后再试' in content:
                            retry_busy += 1
                            if retry_busy > 2:
                                print('检测到服务器繁忙且刷新2次无效，自动切换账户...')
                                print(f"服务器繁忙，尝试切换账户重试: {user_title}")
                                await context.close() # 关闭旧 context
                                # 切换用户，传递此任务的唯一数据目录、所有锁和集合
                                username_in_use = await switch_user(task_user_data_dir, file_lock, active_users_lock, active_users, headless=False)
                                # 使用此任务的唯一数据目录重新启动浏览器上下文
                                context = await p.chromium.launch_persistent_context(task_user_data_dir, headless=False, args=["--disable-blink-features=AutomationControlled"])
                                page = context.pages[0] if context.pages else await context.new_page()
                                await page.goto("https://chat.deepseek.com/")
                                await asyncio.sleep(2)
                                # 需要重新发送第一个 prompt
                                await page.wait_for_selector("textarea")
                                prompt_code = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
                                await random_human_delay()
                                await page.fill("textarea", prompt_code)
                                await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
                                await random_human_delay()
                                await page.click('div._7436101[role="button"][aria-disabled="false"]')
                                print(f"已重新发送第一个 prompt: {user_title}")
                                # 重置繁忙重试计数器
                                retry_busy = 0
                                # 等待新的代码生成
                                await page.wait_for_selector(copy_button_selector, timeout=600000)
                                print(f"切换账户后，代码重新生成完成: {user_title}")
                                continue # 继续 while True 循环检查内容
                            print('检测到"服务器繁忙"，自动点击刷新按钮重试...')
                            await refresh_retry_click(page)
                            await asyncio.sleep(2)
                            await page.wait_for_selector(content_selector, timeout=60000)
                            continue
                        break
                    await random_human_delay()
                    # 检查并自动点击"继续生成"按钮
                    await auto_continue_generate(page)
                    print("AI 代码内容已获取。")
                    file_base = safe_filename(user_title)
                    html_dir = os.path.join(save_dir, "html")
                    os.makedirs(html_dir, exist_ok=True)
                    await random_human_delay()
                    html_path = os.path.join(html_dir, f"{file_base}.html")
                    # 只保留 <!DOCTYPE html> ... </html> 部分
                    html_match = re.search(r'(<!DOCTYPE html[\s\S]*?</html>)', content, re.IGNORECASE)
                    with open(html_path, "w", encoding="utf-8") as f:
                        if html_match:
                            f.write(html_match.group(1))
                        else:
                            f.write(content)
                    await random_human_delay()
                    print(f"AI 代码已保存到 {html_path}")
                    # 检测并点击 "运行 HTML" 按钮
                    run_html_selector = 'div.md-code-block-footer span:has-text("运行 HTML")'
                    clicked_run_html = False
                    try: # 内部 try 处理运行 HTML 按钮
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
                    # 定义发送按钮选择器，确保后续代码可用
                    send_btn_selector = 'div._7436101[role="button"]'

                    # 如果点击了运行按钮，则刷新页面，重置状态（不再截图）
                    if clicked_run_html:
                        try: # 内部 try 处理刷新和输入第二个 prompt
                            print("点击 '运行 HTML' 后刷新页面，重置状态...")
                            await page.reload()
                            await page.wait_for_selector("#chat-input", timeout=60000)
                            await asyncio.sleep(1)
                            # 激活输入框，促使发送按钮enabled
                            await page.focus("#chat-input")
                            await page.type("#chat-input", "a")  # 输入一个字符
                            await asyncio.sleep(0.2)
                            await page.fill("#chat-input", "")  # 清空
                            await asyncio.sleep(0.2)
                            # 还原回 ai_doc (它在此作用域内持有动态内容)
                            await page.type("#chat-input", ai_doc, delay=30)
                            await asyncio.sleep(0.5)
                            # 手动触发 input 事件，确保按钮被激活
                            await page.evaluate("document.querySelector('#chat-input').dispatchEvent(new Event('input', { bubbles: true }))")
                            # send_btn_selector 定义已移到外部
                            btn_state = await page.get_attribute(send_btn_selector, "aria-disabled")
                            print(f"刷新后发送按钮aria-disabled={btn_state}, chat-input内容: '{await page.input_value('#chat-input')}'")
                            # 等待按钮可用
                            await page.wait_for_selector(f'{send_btn_selector}[aria-disabled="false"]', timeout=60000)
                            print("发送按钮已可用，准备输入 02 AI 角色设定 prompt")
                            # 多次尝试填入内容并确认
                            # 修正：逐字符输入，遇到换行用 Shift+Enter，避免提前发送
                            await page.fill("#chat-input", "")  # 清空
                            await asyncio.sleep(0.2)
                            # 还原回 ai_doc
                            for c in ai_doc:
                                if c == '\n':
                                    await page.keyboard.down('Shift')
                                    await page.keyboard.press('Enter')
                                    await page.keyboard.up('Shift')
                                else:
                                    await page.keyboard.type(c)
                                await asyncio.sleep(0.01)
                            # 检查输入框内容，确保全部输入完毕
                            for _ in range(20):
                                current_text = await page.input_value("#chat-input")
                                print(f"输入后chat-input内容: '{current_text}'")
                                # 还原回 ai_doc 进行验证
                                if current_text.strip() == ai_doc.strip():
                                    print("写入成功")
                                    break
                                await asyncio.sleep(0.1)
                            else:
                                raise Exception("无法写入 02 AI 角色设定 prompt 到输入框！")
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            print(f"刷新页面后处理异常: {e}")
                        # 手动触发 input 事件，确保按钮被激活
                        await page.evaluate("document.querySelector('#chat-input').dispatchEvent(new Event('input', { bubbles: true }))")
                        await random_human_delay()
                        print("页面已刷新并成功写入 02 AI 角色设定 prompt")
                except Exception as e: # 对应代码生成和保存的 try
                    print(f"处理第一个 prompt (代码生成/保存/运行HTML/刷新) 时出错: {e}")

                # ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
                # 重新整理第二次输入流程：点击发送按钮、等待生成、自动点击"继续生成"、保存说明
                print("发送 02 AI 角色设定 prompt...")
                retry_busy = 0
                try: # 内部 try 处理第二个 prompt (说明生成)
                    while True:
                        # 再次确认按钮可用
                        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
                        btn_state = await page.get_attribute(send_btn_selector, "aria-disabled")
                        print(f"发送前按钮aria-disabled={btn_state}")
                        await random_human_delay()
                        await page.click('div._7436101[role="button"][aria-disabled="false"]')
                        print("已点击发送按钮，等待按钮状态变化...")
                        # 严格等待按钮状态变化
                        found_enabled = False
                        for i in range(300):  # 最长5分钟
                            state = await page.get_attribute(send_btn_selector, "aria-disabled")
                            print(f"发送后第{i+1}秒，按钮aria-disabled={state}")
                            if state == "false":
                                found_enabled = True
                                break
                            await asyncio.sleep(1)
                        if not found_enabled:
                            print("发送后按钮未变为enabled，流程异常")
                        # 再等待生成结束（按钮变为disabled）
                        for i in range(600):  # 最长10分钟
                            state = await page.get_attribute(send_btn_selector, "aria-disabled")
                            print(f"生成中第{i+1}秒，按钮aria-disabled={state}")
                            if state == "true":
                                print("AI 说明生成完毕。")
                                break
                            await asyncio.sleep(1)
                        else:
                            print("AI 说明生成超时！")
                        # 获取所有说明节点，取最新一条（最后一条）内容
                        doc_nodes = await page.query_selector_all(content_selector)
                        if not doc_nodes:
                            doc_content = ""
                        else:
                            doc_content = await doc_nodes[-1].inner_text()
                        # 检查并自动点击"继续生成"按钮（说明部分）
                        await auto_continue_generate(page)
                        # 检查服务器繁忙
                        if '服务器繁忙，请稍后再试' in doc_content:
                            print('说明生成遇到"服务器繁忙"，直接跳过本次说明生成。')
                            # 注意：这里不再需要 retry_busy 计数器和刷新逻辑
                            break # 跳出 while True, 不再重试说明生成
                        break # 说明生成成功，跳出 while True
                    # 只有在成功生成说明后才写入文件
                    if '服务器繁忙，请稍后再试' not in doc_content:
                        doc_path = os.path.join(save_dir, "软件说明.md")
                        with open(doc_path, "a", encoding="utf-8") as f:
                            f.write(f"\n# {user_title}\n\n{doc_content.strip()}\n")
                        print(f"AI 说明已追加到 {doc_path}")
                    else:
                        print(f"因服务器持续繁忙，未保存 {user_title} 的说明。")
                except Exception as e: # 对应第二个 prompt 的 try
                    print(f"处理第二个 prompt (说明生成) 时出错: {e}")
                # Missing except block for the try starting at line 89
                except Exception as browser_err: # Handles errors within the main browser interaction block
                     print(f"[并发任务 BROWSER ERROR] 处理 {user_title} (用户: {username_in_use}) 时浏览器交互出错: {browser_err}")
                     # Consider re-raising or specific handling if needed
    
            # Outer except and finally blocks (correspond to try at line 78)
            except Exception as e_task: # 捕获整个任务执行过程中的异常 (包括 switch_user 或 browser_err)
                print(f"[并发任务 ERROR] 处理 {user_title} (用户: {username_in_use or '未知'}) 时发生异常: {e_task}") # Corrected indentation
        finally:
            # 确保 context 在任何情况下都被关闭
            if context: # Check if context was successfully created
                try:
                    await context.close()
                    print(f"[并发任务] Context closed for {user_title} (用户: {username_in_use})")
                except Exception as close_err:
                    # Playwright 可能因浏览器已崩溃而无法关闭，这通常不是关键错误
                    print(f"[并发任务 WARNING] 关闭 context 时出错 (可能浏览器已关闭) for {user_title} (用户: {username_in_use}): {close_err}")

            # 释放占用的用户 (无论任务成功或失败)
            if username_in_use:
                async with active_users_lock:
                    if username_in_use in active_users:
                        active_users.remove(username_in_use)
                        print(f"[并发任务] 释放账户: {username_in_use} (来自任务: {user_title})")
                    else:
                        # 可能在 switch_user 失败后 username_in_use 仍为 None 或已被移除
                        print(f"[并发任务 WARNING] 尝试释放账户 {username_in_use} 但其不在活跃集合中 (来自任务: {user_title})")
            else:
                 print(f"[并发任务 WARNING] 任务 {user_title} 结束时无用户名可释放。")

            print(f"[并发任务] 完成处理: {user_title}") # 标记任务完成

        # (Removed misleading comment)


async def main():
    import glob
    import time
    CONCURRENCY_LIMIT = 2 # 设置并发限制为 2
    print(f"[LOG] 开始批量处理，并发限制: {CONCURRENCY_LIMIT}")
    # 创建文件锁，用于保护 user_pool.md 文件读写
    file_lock = asyncio.Lock()
    # 创建活跃用户锁和集合，用于跟踪正在使用的账户
    active_users_lock = asyncio.Lock()
    active_users = set()
    # 创建信号量，限制并发任务数量
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    # 检查账户数量是否足够支持并发 (load_user_pool 现在只需要 file_lock)
    user_pool_path = 'user_pool.md'
    try:
        # 临时加载一次检查数量 (load_user_pool 是同步函数，不再需要锁参数)
        # 需要在 asyncio 事件循环中运行同步函数，或者在外部调用
        # Easiest fix: Call it synchronously before starting the async part,
        # but this blocks startup. Better: run_in_executor or make main sync initially.
        # Let's try run_in_executor within main's async context.
        loop = asyncio.get_running_loop()
        # We need file_lock here to ensure consistency if load_user_pool needs to write back
        async with file_lock:
             users = await loop.run_in_executor(None, load_user_pool, user_pool_path)
        # users = load_user_pool(user_pool_path) # Incorrect: calling sync directly in async
        if len(users) < CONCURRENCY_LIMIT:
            print(f"[WARNING] 账户池中的账户数量 ({len(users)}) 少于并发限制 ({CONCURRENCY_LIMIT})，可能导致任务等待或失败。")
    except Exception as e:
        print(f"[ERROR] 加载账户池失败: {e}，无法检查账户数量。")

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
        for idx, user_prompt_path in enumerate(user_prompt_files):
            # 取去掉扩展名的完整文件名作为父目录名
            basename_no_ext = os.path.splitext(os.path.basename(user_prompt_path))[0]
            save_dir = os.path.join("saved_outputs", basename_no_ext)
            os.makedirs(save_dir, exist_ok=True)
            print(f"\n[LOG] 开始处理 {user_prompt_path}，输出目录：{save_dir}")
            try:
                # 不需要在这里切换账户，process_prompt 内部会切换
                # await switch_user(file_lock, headless=False) # 传递锁
                user_prompts = get_user_prompts(user_prompt_path)
                # 动态替换软件名称（去除前缀数字和空格）
                match = re.match(r"\d+\s*(.*)", basename_no_ext)
                software_name = match.group(1) if match else basename_no_ext
                ai_role_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_role)
                ai_doc_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_doc)

                tasks = []
                for user_title, user_content in user_prompts:
                    print(f"[LOG] 创建任务处理一级标题：{user_title}")
                    # 注意：process_prompt 现在需要 lock 和 semaphore 参数
                    # 不需要 force_clean_user_data_dir 参数了
                    task = asyncio.create_task(
                        process_prompt(p, ai_role_dynamic, ai_doc_dynamic, user_title, user_content, save_dir, file_lock, active_users_lock, active_users, semaphore)
                    )
                    tasks.append(task)

                # 等待当前文件的所有一级标题任务完成
                await asyncio.gather(*tasks)

                print(f"[LOG] {user_prompt_path} 内所有一级标题处理完成。")
            except Exception as e:
                print(f"[ERROR] 处理 {user_prompt_path} 出错: {e}")
            # 如果不是最后一个，等待半小时，这里逻辑有问题
            if idx < len(user_prompt_files) - 1:
                print("[LOG] 等待半小时后继续处理下一个 user_prompt.md ...")
                for remain in range(3600, 0, -60):
                    print(f"[LOG] 剩余等待时间: {remain//60} 分钟...")
                    await asyncio.sleep(60)
    print("[LOG] 全部 user_prompt.md 文件处理完成！")

if __name__ == "__main__":
    asyncio.run(main())