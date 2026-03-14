import re

with open('edit_page_dump.html', 'r', encoding='utf-8') as f:
    text = f.read()

# try to find the language text we click on
items = re.findall(r'<div[^>]*class=[\"\']item-text[^\"\']*[\"\'][^>]*>(.*?)</div>', text, re.DOTALL | re.IGNORECASE)
for i in items:
    if 'russian' in i.lower() or 'русский' in i.lower():
        print(f'TEXT ITEM: {i.strip()}')
