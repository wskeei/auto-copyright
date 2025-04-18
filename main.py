import asyncio
from playwright.async_api import async_playwright
import os
import re
import random
from test_user_switch import switch_user

async def random_human_delay(min_sec=1, max_sec=3):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# 工具函数：自动查找并点击“重新生成”按钮
async def refresh_retry_click(page):
    btns = await page.query_selector_all('.ds-icon-button')
    for btn in btns:
        rect = await btn.query_selector('rect[id="重新生成"]')
        if rect is not None:
            print("找到带有 id=重新生成 的 rect，点击父按钮！")
            await btn.click()
            return
    raise Exception('未找到“重新生成”按钮，无法自动重试！')

# 工具函数：自动点击“继续生成”直到无按钮
async def auto_continue_generate(page, max_loops=10):
    """
    检查并自动点击“继续生成”按钮，直到按钮消失或达到最大次数。
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

async def process_prompt(p, ai_role, ai_doc, user_title, user_content, save_dir, force_clean_user_data_dir=False):
    user_data_dir = "./user_data_chromium"
    import shutil
    if force_clean_user_data_dir and os.path.exists(user_data_dir):
        print(f"检测到 user_data_dir {user_data_dir} 存在，正在自动清理...")
        shutil.rmtree(user_data_dir)
        print("user_data_dir 已清理。")
    context = await p.chromium.launch_persistent_context(user_data_dir, headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = context.pages[0] if context.pages else await context.new_page()
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
                    print('检测到服务器繁忙且刷新2次无效，自动切换账户...')
                    await switch_user(headless=False)
                    # 切换账户后需重新打开浏览器和页面
                    # 关闭当前context和browser
                    await page.context.close()
                    # 重新初始化 playwright browser/page/context
                    async with p.chromium.launch_persistent_context('./user_data_chromium', headless=False) as context:
                        page = context.pages[0] if context.pages else await context.new_page()
                        await page.goto("https://chat.deepseek.com/")
                        await asyncio.sleep(2)
                        # 重新发送当前提示词（假设变量 user_title, user_content, ai_role, ai_doc, save_dir 仍可用）
                        # 可将主循环包裹为 while/prompt_list 结构，当前提示词重试
                        continue  # 重新进入 while True 循环
                print('检测到“服务器繁忙”，自动点击刷新按钮重试...')
                await refresh_retry_click(page)
                await asyncio.sleep(2)
                await page.wait_for_selector(content_selector, timeout=60000)
                continue
            break
        await random_human_delay()
        # 检查并自动点击“继续生成”按钮
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
    # 重新整理第二次输入流程：点击发送按钮、等待生成、自动点击“继续生成”、保存说明
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
            # 检查并自动点击“继续生成”按钮（说明部分）
            await auto_continue_generate(page)
            # 检查服务器繁忙
            if '服务器繁忙，请稍后再试' in doc_content:
                retry_busy += 1
                if retry_busy > 2:
                    print('说明生成遇到服务器繁忙且刷新2次无效，直接跳过本次说明生成，进入下一个prompt...')
                    break
                print('说明生成遇到“服务器繁忙”，自动点击刷新按钮重试...')
                await refresh_retry_click(page)
                await asyncio.sleep(2)
                await page.wait_for_selector(content_selector, timeout=60000)
                continue
            break
        doc_path = os.path.join(save_dir, "软件说明.md")
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write(f"\n# {user_title}\n\n{doc_content.strip()}\n")
        print(f"AI 说明已追加到 {doc_path}")
    except Exception as e:
        print(f"等待复制按钮超时或出错: {e}")
    await context.close()


async def main():
    # 每次执行都切换到最久未用账户
    await switch_user(headless=False)
    ai_prompt_path = "AI_prompt.md"
    user_prompt_path = "uer_prompt.md"  # 注意你的实际文件名
    save_dir = "saved_outputs"
    os.makedirs(save_dir, exist_ok=True)
    ai_role, ai_doc = get_ai_prompts(ai_prompt_path)
    user_prompts = get_user_prompts(user_prompt_path)
    async with async_playwright() as p:
        for user_title, user_content in user_prompts:
            # 每次循环切换一次账户
            await switch_user(headless=False)
            await process_prompt(p, ai_role, ai_doc, user_title, user_content, save_dir)
    print("全部处理完成！")

if __name__ == "__main__":
    asyncio.run(main())