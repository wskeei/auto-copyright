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

async def process_prompt(p, ai_role, ai_doc, user_title, user_content, save_dir):
    user_data_dir = "./user_data_chromium"
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
        content = await page.inner_text(content_selector)
        print("AI 代码内容已获取。")
        file_base = safe_filename(user_title)
        html_path = os.path.join(save_dir, f"{file_base}.html")
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
            screenshot_path = os.path.join(save_dir, f"{file_base}.png")
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
            await page.wait_for_selector("textarea", timeout=30000)
            # 确保textarea可编辑且内容为空
            await asyncio.sleep(1)
            await page.fill("textarea", "")
            retry_count = 0
            while retry_count < 3:
                await page.fill("textarea", ai_doc)
                value = await page.input_value("textarea")
                if value.strip() == ai_doc.strip():
                    break
                print(f"填写 02 AI 角色设定 prompt 失败，重试...{retry_count+1}")
                await asyncio.sleep(1)
                retry_count += 1
            else:
                raise Exception("无法写入 02 AI 角色设定 prompt 到输入框！")
            print("页面已刷新并成功写入 02 AI 角色设定 prompt")
        except Exception as e:
            print(f"刷新页面或写入 prompt 时出错: {e}")
        # 发送 02 AI 角色设定 prompt，生成说明
        print("发送 02 AI 角色设定 prompt...")
        await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
        await page.click('div._7436101[role="button"][aria-disabled="false"]')
        print("等待 AI 说明回复生成...（检测发送按钮 aria-disabled=true）")
        try:
            # 等待发送按钮变为禁用，表示生成完成
            send_btn_selector = 'div._7436101[role="button"]'
            await page.wait_for_selector(f'{send_btn_selector}[aria-disabled="true"]', timeout=600000)
            print("发送按钮已禁用，AI 说明生成完毕。")
            doc_content = await page.inner_text(content_selector)
            doc_path = os.path.join(save_dir, "软件说明.md")
            with open(doc_path, "a", encoding="utf-8") as f:
                f.write(f"\n# {user_title}\n\n{doc_content.strip()}\n")
            print(f"AI 说明已追加到 {doc_path}")
        except Exception as e:
            print(f"AI 说明生成超时或出错: {e}")
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