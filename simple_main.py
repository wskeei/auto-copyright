import asyncio
from playwright.async_api import async_playwright
import os
import re

# 解析 AI_prompt.md，获取 AI角色设定内容
def get_ai_role(ai_prompt_path):
    with open(ai_prompt_path, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"# AI角色设定[\s\n]+([\s\S]+?)(?=^#|\Z)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""

# 解析 user_prompt.md，获取所有一级标题和内容
# 返回 [(标题, 内容), ...]
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

# 文件名安全处理
def safe_filename(title):
    name = re.sub(r"[^\u4e00-\u9fa5\w]+", "_", title)
    name = name.strip("_")
    return name

async def process_prompt(p, ai_role, user_title, user_content, save_dir):
    user_data_dir = "./user_data_chromium"
    context = await p.chromium.launch_persistent_context(user_data_dir, headless=False, args=["--disable-blink-features=AutomationControlled"])
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://chat.deepseek.com/")
    print(f"已打开 https://chat.deepseek.com/，处理：{user_title}")
    await page.wait_for_selector("textarea")
    # 组合提示词
    prompt = f"# AI角色设定\n{ai_role}\n\n# {user_title}\n{user_content}"
    await page.fill("textarea", prompt)
    await page.wait_for_selector('div._7436101[role="button"][aria-disabled="false"]')
    await page.click('div._7436101[role="button"][aria-disabled="false"]')
    # 等待复制按钮
    copy_button_selector = 'div._8f60047 div.ds-flex._965abe9 div.ds-icon-button:first-child'
    try:
        await page.wait_for_selector(copy_button_selector, timeout=600000)
        print("检测到复制按钮，AI 回复已生成。")
        # 获取内容并保存
        content_selector = 'div._8f60047 .ds-markdown.ds-markdown--block'
        content = await page.inner_text(content_selector)
        file_base = safe_filename(user_title)
        html_path = os.path.join(save_dir, f"{file_base}.html")
        html_match = re.search(r'(<!DOCTYPE html[\s\S]*?</html>)', content, re.IGNORECASE)
        with open(html_path, "w", encoding="utf-8") as f:
            if html_match:
                f.write(html_match.group(1))
            else:
                f.write(content)
        print(f"AI 代码已保存到 {html_path}")
        # 检测并点击 "运行 HTML" 按钮
        run_html_selector = 'div.md-code-block-footer span:has-text("运行 HTML")'
        if await page.locator(run_html_selector).count() > 0:
            await page.wait_for_selector(run_html_selector, state="visible", timeout=5000)
            await page.click(run_html_selector)
            print("已点击 '运行 HTML' 按钮。")
            # 截图
            iframe_selector = 'iframe[src="https://cdn.deepseek.com/usercontent/usercontent.html"]'
            internal_element_selector = 'body'
            screenshot_path = os.path.join(save_dir, f"{file_base}.png")
            try:
                await page.wait_for_selector(iframe_selector, state="visible", timeout=10000)
                frame = page.frame_locator(iframe_selector)
                await frame.locator(internal_element_selector).wait_for(state="visible", timeout=45000)
                await asyncio.sleep(1)
                await frame.locator(internal_element_selector).screenshot(path=screenshot_path)
                print(f"已将 iframe 内 body 截图保存到 {screenshot_path}")
            except Exception as e:
                print(f"截图失败: {e}")
        else:
            print("'运行 HTML' 按钮未找到。")
    except Exception as e:
        print(f"等待复制按钮超时或出错: {e}")
    await context.close()

async def main():
    ai_prompt_path = "AI_prompt.md"
    user_prompt_path = "uer_prompt.md"
    save_dir = "saved_outputs"
    os.makedirs(save_dir, exist_ok=True)
    ai_role = get_ai_role(ai_prompt_path)
    user_prompts = get_user_prompts(user_prompt_path)
    async with async_playwright() as p:
        for user_title, user_content in user_prompts:
            await process_prompt(p, ai_role, user_title, user_content, save_dir)
    print("全部处理完成！")

if __name__ == "__main__":
    asyncio.run(main())
