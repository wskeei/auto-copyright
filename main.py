import asyncio
from playwright.async_api import async_playwright
import os
import re

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
    await page.goto("https://chat.deepseek.com/")
    print(f"已打开 https://chat.deepseek.com/，处理：{user_title}")
    await page.wait_for_selector("textarea")
    # 1. 组合第一个 prompt，生成代码
    prompt_code = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
    await page.fill("textarea", prompt_code)
    await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
    await page.click('div._7436101[role="button"][aria-disabled="false"]')
    copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
    print("等待 AI 代码回复生成完毕...")
    try:
        await page.wait_for_selector(copy_button_selector, timeout=600000)
        print("检测到复制按钮，AI 代码已生成。")
        # 保存 HTML 文件
        content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
        # 检查是否遇到服务器繁忙提示，若是则自动刷新重试
        retry_busy = 0
        while True:
            content = await page.inner_text(content_selector)
            if '服务器繁忙，请稍后再试' in content:
                retry_busy += 1
                if retry_busy > 5:
                    raise Exception('连续多次服务器繁忙，自动重试失败！')
                print('检测到“服务器繁忙”，自动点击刷新按钮重试...')
                # 定位刷新按钮（svg 内含 id="重新生成"）
                refresh_btn = page.locator('div.ds-icon-button svg[id="重新生成"]')
                if await refresh_btn.count() > 0:
                    await refresh_btn.first.evaluate('el => el.closest(".ds-icon-button").click()')
                    await asyncio.sleep(2)
                    await page.wait_for_selector(content_selector, timeout=60000)
                    continue
                else:
                    raise Exception('未找到“重新生成”按钮，无法自动重试！')
            break
        print("AI 代码内容已获取。")
        file_base = safe_filename(user_title)
        html_dir = os.path.join(save_dir, "html")
        os.makedirs(html_dir, exist_ok=True)
        html_path = os.path.join(html_dir, f"{file_base}.html")
        # 只保留 <!DOCTYPE html> ... </html> 部分
        html_match = re.search(r'(<!DOCTYPE html[\s\S]*?</html>)', content, re.IGNORECASE)
        with open(html_path, "w", encoding="utf-8") as f:
            if html_match:
                f.write(html_match.group(1))
            else:
                f.write(content)
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
        # 如果点击了运行按钮，则截图
        if clicked_run_html:
            iframe_selector = 'iframe[src="https://cdn.deepseek.com/usercontent/usercontent.html"]'
            internal_element_selector = 'body'  # 截图整个 body
            screenshots_dir = os.path.join(save_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f"{file_base}.png")
        try:
            print(f"等待 iframe '{iframe_selector}' 出现...")
            await page.wait_for_selector(iframe_selector, state="visible", timeout=10000)
            frame = page.frame_locator(iframe_selector)
            print(f"成功定位 iframe。等待 iframe 内元素加载...")
            await frame.locator(internal_element_selector).wait_for(state="visible", timeout=45000)
            await asyncio.sleep(1)
            await frame.locator(internal_element_selector).screenshot(path=screenshot_path)
            print(f"已将 iframe 内 body 截图保存到 {screenshot_path}")
        except Exception as e:
            print(f"截图失败: {e}")
        # 截图后刷新页面，规避关闭按钮问题
        try:
            print("截图后刷新页面，重置状态...")
            await page.reload()
            await page.wait_for_selector("#chat-input", timeout=30000)
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
            # 手动触发 input 事件，确保按钮被激活
            await page.evaluate("document.querySelector('#chat-input').dispatchEvent(new Event('input', { bubbles: true }))")
            print("页面已刷新并成功写入 02 AI 角色设定 prompt")
        except Exception as e:
            print(f"刷新页面或写入 prompt 时出错: {e}")
        # 发送 02 AI 角色设定 prompt，生成说明（带服务器繁忙自动重试）
        print("发送 02 AI 角色设定 prompt...")
        retry_busy = 0
        while True:
            # 再次确认按钮可用
            await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
            btn_state = await page.get_attribute(send_btn_selector, "aria-disabled")
            print(f"发送前按钮aria-disabled={btn_state}")
            await page.click('div._7436101[role="button"][aria-disabled="false"]')
            print("已点击发送按钮，等待按钮状态变化...")
            # 严格等待按钮状态变化
            found_enabled = False
            for i in range(120):  # 最长2分钟
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
            # 检查服务器繁忙
            if '服务器繁忙，请稍后再试' in doc_content:
                retry_busy += 1
                if retry_busy > 5:
                    raise Exception('说明生成遇到服务器繁忙，自动重试5次仍失败！')
                print('说明生成遇到“服务器繁忙”，自动点击刷新按钮重试...')
                refresh_btn = page.locator('div.ds-icon-button svg[id="重新生成"]')
                if await refresh_btn.count() > 0:
                    await refresh_btn.first.evaluate('el => el.closest(".ds-icon-button").click()')
                    await asyncio.sleep(2)
                    await page.wait_for_selector(content_selector, timeout=60000)
                    continue
                else:
                    raise Exception('未找到“重新生成”按钮，无法自动重试！')
            break
        doc_path = os.path.join(save_dir, "软件说明.md")
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write(f"\n# {user_title}\n\n{doc_content.strip()}\n")
        print(f"AI 说明已追加到 {doc_path}")
    except Exception as e:
        print(f"等待复制按钮超时或出错: {e}")
    await context.close()


async def main():
    ai_prompt_path = "AI_prompt.md"
    user_prompt_path = "uer_prompt.md"  # 注意你的实际文件名
    save_dir = "saved_outputs"
    os.makedirs(save_dir, exist_ok=True)
    ai_role, ai_doc = get_ai_prompts(ai_prompt_path)
    user_prompts = get_user_prompts(user_prompt_path)
    async with async_playwright() as p:
        for user_title, user_content in user_prompts:
            await process_prompt(p, ai_role, ai_doc, user_title, user_content, save_dir)
    print("全部处理完成！")

if __name__ == "__main__":
    asyncio.run(main())