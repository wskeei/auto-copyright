import os
import re

# 目标文件夹和输出文件
HTML_DIR = os.path.join(os.path.dirname(__file__), 'saved_outputs', 'html')
OUTPUT_FILE = os.path.join(HTML_DIR, 'ALL.html')

def extract_body_content(html_text):
    """提取<body>标签内的内容，如果没有则返回全文。"""
    match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html_text, re.IGNORECASE)
    return match.group(1).strip() if match else html_text

def extract_head_content(html_text):
    """提取<head>标签内的内容，如果没有则返回空字符串。"""
    match = re.search(r'<head[^>]*>([\s\S]*?)</head>', html_text, re.IGNORECASE)
    return match.group(1).strip() if match else ''

def main():
    html_files = [f for f in os.listdir(HTML_DIR) if f.endswith('.html')]
    all_body_contents = []
    all_head_contents = []
    for filename in sorted(html_files):
        path = os.path.join(HTML_DIR, filename)
        with open(path, 'r', encoding='utf-8') as f:
            html_text = f.read()
            body = extract_body_content(html_text)
            head = extract_head_content(html_text)
            all_body_contents.append(f'<!-- {filename} -->\n' + body)
            if head:
                all_head_contents.append(head)
    # 合并head内容，去重
    unique_head = '\n'.join(list(dict.fromkeys(all_head_contents)))
    # 构建完整HTML
    merged_html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
{unique_head}
</head>
<body>
{os.linesep.join(all_body_contents)}
</body>
</html>'''
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(merged_html)
    print(f"已合并{len(html_files)}个HTML文件到 {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
