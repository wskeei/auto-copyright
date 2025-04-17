import asyncio
from playwright.async_api import async_playwright
import os
import re
import random
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

# 辅助函数：从标题提取序号
def get_title_index(title):
    match = re.match(r"(\d+)", title)
    return int(match.group(1)) if match else -1 # 如果没有序号返回 -1

# 修改后的 process_prompt，只负责核心交互逻辑，接收 page 对象
async def process_prompt(page, ai_role, ai_doc, user_title, user_content, save_dir):
    """
    处理单个 prompt 的核心交互逻辑。
    成功时返回 (user_title, doc_content)，失败或无说明时返回 (user_title, None)。
    """
    doc_content = None # 初始化说明内容
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
    try:
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
                    # 并发模式下，遇到严重错误直接记录并退出当前任务，而不是切换账户
                    print('检测到服务器繁忙且刷新2次无效，放弃当前 prompt 处理...')
                    # 可以选择抛出异常让上层处理，或者直接返回 False 表示失败
                    # raise Exception("服务器持续繁忙，无法处理")
                    return False # 表示处理失败
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
        # 如果点击了运行按钮，则刷新页面，重置状态（不再截图）
        if clicked_run_html:
            try:
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
                await page.type("#chat-input", ai_doc, delay=30)  # 模拟逐字输入 prompt
                await asyncio.sleep(0.5)
                # 手动触发 input 事件，确保按钮被激活
                await page.evaluate("document.querySelector('#chat-input').dispatchEvent(new Event('input', { bubbles: true }))")
                send_btn_selector = 'div._7436101[role="button"]'
                btn_state = await page.get_attribute(send_btn_selector, "aria-disabled")
                print(f"刷新后发送按钮aria-disabled={btn_state}, chat-input内容: '{await page.input_value('#chat-input')}'")
                # 等待按钮可用
                await page.wait_for_selector(f'{send_btn_selector}[aria-disabled="false"]', timeout=60000)
                print("发送按钮已可用，准备输入 02 AI 角色设定 prompt")
                # 多次尝试填入内容并确认
                # 修正：逐字符输入，遇到换行用 Shift+Enter，避免提前发送
                await page.fill("#chat-input", "")  # 清空
                await asyncio.sleep(0.2)
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
    except Exception as e:
        print(f"刷新页面或写入 prompt 时出错: {e}")
    # ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
    # 重新整理第二次输入流程：点击发送按钮、等待生成、自动点击"继续生成"、保存说明
    print("发送 02 AI 角色设定 prompt...")
    retry_busy = 0
    try:
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
                retry_busy += 1
                if retry_busy > 2:
                    print('说明生成遇到服务器繁忙且刷新2次无效，直接跳过本次说明生成，进入下一个prompt...')
                    break
                print('说明生成遇到"服务器繁忙"，自动点击刷新按钮重试...')
                await refresh_retry_click(page)
                await asyncio.sleep(2)
                await page.wait_for_selector(content_selector, timeout=60000)
                continue
            break
        # 不再直接写入文件，而是准备返回内容
        # doc_path = os.path.join(save_dir, "软件说明.md")
        # with open(doc_path, "a", encoding="utf-8") as f:
        #     f.write(f"\n# {user_title}\n\n{doc_content.strip()}\n")
        # print(f"AI 说明已获取，准备返回")
        pass # doc_content 已在前面获取或为 None
    except Exception as e:
        print(f"处理 AI 说明时出错: {e}")
        # 即使出错，也返回 title 和 None，让上层知道哪个 title 失败了
        return (user_title, None) # 返回标题和 None 表示失败

    # 返回获取到的标题和说明内容（可能为 None）
    return (user_title, doc_content)

# 新增：并发工作流函数（带顺序写入控制）
async def run_single_prompt_workflow(
    semaphore, ai_role, ai_doc, user_title, user_content, save_dir, worker_id,
    write_condition, expected_write_index, prompt_index
):
    """
    管理单个 prompt 的完整并发工作流，并按 prompt_index 顺序写入结果。
    """
    user_data_dir = f"./user_data_chromium_{worker_id}" # 每个 worker 使用独立的目录
    context = None # 初始化 context 为 None
    username = None # 初始化用户名
    log_prefix = f"[Worker {worker_id}]" # 默认日志前缀

    async with semaphore:
        print(f"{log_prefix} 获取信号量，开始处理: {user_title}")
        try:
            # 1. 切换用户（清理并登录）
            print(f"{log_prefix} 正在切换用户并准备环境: {user_data_dir}")
            username = await switch_user(user_data_dir, headless=False) # 使用独立的 user_data_dir 并获取用户名

            if username:
                log_prefix = f"[{username}][Worker {worker_id}]" # 更新日志前缀
                print(f"{log_prefix} 用户切换成功")
            else:
                print(f"{log_prefix} [ERROR] 用户切换失败，无法获取用户名，跳过处理: {user_title}")
                return # 切换失败则退出

            # 2. 启动浏览器并处理
            async with async_playwright() as p:
                print(f"{log_prefix} 启动浏览器上下文: {user_data_dir}")
                # 增加超时和重试机制
                for attempt in range(3):
                    try:
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir,
                            headless=False,
                            args=["--disable-blink-features=AutomationControlled"],
                            slow_mo=50 # 稍微降低速度，可能有助于稳定性
                        )
                        break # 成功则跳出循环
                    except Exception as launch_err:
                        print(f"{log_prefix} 启动浏览器上下文失败 (尝试 {attempt+1}/3): {launch_err}")
                        if attempt == 2:
                            print(f"{log_prefix} [ERROR] 无法启动浏览器，放弃处理: {user_title}")
                            # 确保在异常退出前关闭可能已部分启动的 context
                            if context:
                                try: await context.close()
                                except: pass
                            return # 放弃此任务
                        await asyncio.sleep(5) # 等待后重试
                if not context:
                    print(f"{log_prefix} [ERROR] context 未成功创建，退出任务")
                    return # 如果 context 未成功创建

                page = context.pages[0] if context.pages else await context.new_page()
                print(f"{log_prefix} 开始执行 process_prompt: {user_title}")
                # 注意：process_prompt 内部的 print 语句不会自动添加用户名
                res_title, res_content = await process_prompt(page, ai_role, ai_doc, user_title, user_content, save_dir)

                if res_content is not None:
                    print(f"{log_prefix} process_prompt 处理成功，获取到说明: {res_title}")
                    # --- 按顺序写入文件 ---
                    doc_path = os.path.join(save_dir, "软件说明.md")
                    async with write_condition: # 获取条件变量的锁
                        while expected_write_index[0] != prompt_index:
                            print(f"{log_prefix} 标题 '{res_title}' (序号 {prompt_index}) 等待写入，期望序号: {expected_write_index[0]}")
                            await write_condition.wait() # 等待通知

                        # 轮到自己写入
                        print(f"{log_prefix} 标题 '{res_title}' (序号 {prompt_index}) 开始写入文件: {doc_path}")
                        try:
                            # 使用追加模式写入
                            with open(doc_path, "a", encoding="utf-8") as f:
                                f.write(f"\n# {res_title}\n\n{res_content.strip()}\n")
                            print(f"{log_prefix} 标题 '{res_title}' 写入成功")
                            # 更新期望序号并通知其他等待者
                            expected_write_index[0] += 1
                            write_condition.notify_all()
                        except IOError as io_err:
                             print(f"{log_prefix} [ERROR] 写入文件 {doc_path} 时出错: {io_err}")
                             # 即使写入失败，也要尝试推进序号并通知，防止死锁
                             expected_write_index[0] += 1
                             write_condition.notify_all()

                    # --- 写入结束 ---
                else:
                     print(f"{log_prefix} [WARNING] process_prompt 处理完成但未获取到说明: {res_title}")
                     # 如果未获取到内容，也需要检查是否轮到自己推进序号
                     async with write_condition:
                         if expected_write_index[0] == prompt_index:
                             print(f"{log_prefix} 任务 {prompt_index} 未获取内容，推进期望序号并通知")
                             expected_write_index[0] += 1
                             write_condition.notify_all()


        except Exception as e:
            print(f"{log_prefix} [ERROR] 处理 {user_title} (序号 {prompt_index}) 时发生意外错误: {e}")
            # 发生意外错误时，同样需要尝试推进序号以防死锁
            async with write_condition:
                 if expected_write_index[0] == prompt_index:
                     print(f"{log_prefix} [ERROR] 任务 {prompt_index} 出错，尝试推进期望序号并通知")
                     expected_write_index[0] += 1
                     write_condition.notify_all()

        finally:
            if context:
                try:
                    await context.close()
                    print(f"{log_prefix} 浏览器上下文已关闭: {user_data_dir}")
                except Exception as close_err:
                    print(f"{log_prefix} [ERROR] 关闭浏览器上下文时出错: {close_err}")
            print(f"{log_prefix} 释放信号量，完成处理: {user_title}")
    # 这个函数现在不返回任何有意义的值，因为写入在内部完成


async def main():
    import glob
    import time

    CONCURRENCY_LIMIT = 2 # 设置并发限制
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    print("[LOG] 扫描所有 user_prompt.md 文件...")
    user_prompt_dir = "user_prompt.md"
    user_prompt_files = sorted(
        glob.glob(os.path.join(user_prompt_dir, "[0-9][0-9] *.md")),
        key=lambda x: int(os.path.basename(x).split()[0])
    )
    print(f"[LOG] 共找到 {len(user_prompt_files)} 个 user_prompt.md 文件: {user_prompt_files}")

    ai_prompt_path = "AI_prompt.md"
    if not os.path.exists(ai_prompt_path):
        print(f"[ERROR] {ai_prompt_path} 文件不存在，退出！")
        return
    ai_role, ai_doc = get_ai_prompts(ai_prompt_path)

    # Playwright 实例不再需要在 main 函数中创建

    for idx, user_prompt_path in enumerate(user_prompt_files):
        basename_no_ext = os.path.splitext(os.path.basename(user_prompt_path))[0]
        save_dir = os.path.join("saved_outputs", basename_no_ext)
        os.makedirs(save_dir, exist_ok=True)
        print(f"\n[LOG] 开始处理文件 {user_prompt_path}，输出目录：{save_dir}")

        # 为当前文件初始化写入控制变量
        file_lock = asyncio.Lock() # 虽然 Condition 内部有锁，但明确创建可能更清晰
        write_condition = asyncio.Condition(lock=file_lock)
        expected_write_index = [1] # 下一个期望写入的序号，从1开始
        doc_path = os.path.join(save_dir, "软件说明.md")

        # 清空之前的说明文件内容
        try:
            with open(doc_path, "w", encoding="utf-8") as f:
                f.write("") # 写入空字符串以清空
            print(f"[LOG] 已清空说明文件: {doc_path}")
        except IOError as e:
            print(f"[ERROR] 清空文件 {doc_path} 时出错: {e}")
            continue # 如果无法清空，跳过此文件处理

        try:
            user_prompts = get_user_prompts(user_prompt_path) # [(title, content), ...]
            match = re.match(r"\d+\s*(.*)", basename_no_ext)
            software_name = match.group(1) if match else basename_no_ext
            ai_role_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_role)
            ai_doc_dynamic = re.sub(r"我现在需要的制作的软件名称为：.*", f"我现在需要的制作的软件名称为：{software_name}", ai_doc)

            tasks = []
            # 为当前文件的所有 prompt 创建并发任务
            tasks = []
            for list_idx, (user_title, user_content) in enumerate(user_prompts):
                prompt_index = get_title_index(user_title) # 获取标题中的序号
                if prompt_index == -1:
                    print(f"[WARNING] 标题 '{user_title}' 无法提取序号，将跳过此 prompt 的顺序写入")
                    # 可以选择跳过，或者分配一个特殊序号
                    continue # 跳过这个 prompt

                worker_id = list_idx % CONCURRENCY_LIMIT # 循环使用 worker ID 0 和 1
                print(f"[LOG] 创建任务 Worker {worker_id} 处理一级标题：'{user_title}' (序号: {prompt_index})")
                task = asyncio.create_task(run_single_prompt_workflow(
                    semaphore,
                    ai_role_dynamic,
                    ai_doc_dynamic,
                    user_title,
                    user_content,
                    save_dir,
                    worker_id,
                    write_condition, # 传递条件变量
                    expected_write_index, # 传递期望序号列表
                    prompt_index # 传递当前 prompt 的序号
                ))
                tasks.append(task)

            # 等待所有任务完成（写入操作在任务内部按顺序进行）
            print(f"[LOG] 开始并发处理 {len(tasks)} 个 prompts (限制 {CONCURRENCY_LIMIT})... 写入将按序号进行")
            await asyncio.gather(*tasks)
            print(f"[LOG] 文件 {user_prompt_path} 的所有并发任务完成，说明已按序写入。")

        except Exception as e:
            print(f"[ERROR] 处理文件 {user_prompt_path} 时的主循环出错: {e}")

        # 文件间等待逻辑保持不变
        if idx < len(user_prompt_files) - 1:
            print("[LOG] 等待半小时后继续处理下一个 user_prompt.md ...")
            wait_seconds = 1800 # 30 minutes
            for remaining in range(wait_seconds, 0, -60):
                print(f"[LOG] 剩余等待时间: {remaining // 60} 分钟...")
                await asyncio.sleep(60)

    print("[LOG] 全部 user_prompt.md 文件处理完成！")

if __name__ == "__main__":
    # 增加健壮性：捕获 asyncio.run() 可能的异常
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[LOG] 检测到手动中断，程序退出。")
    except Exception as main_err:
        print(f"[FATAL] 程序运行出错: {main_err}")