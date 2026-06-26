f = 'backend/services/llm.py'
content = open(f, 'r', encoding='utf-8').read()
old = "for tok in ('<img>', '<end_of_image>'):"
new = "for tok in ('<start_of_image>', '<end_of_image>'):"
content = content.replace(old, new)
open(f, 'w', encoding='utf-8').write(content)
idx = content.find('for tok in')
print(repr(content[idx:idx+70]))
print('Done')
