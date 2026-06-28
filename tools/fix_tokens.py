import os
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
f = PROJECT_ROOT / 'backend' / 'services' / 'llm.py'
content = open(f, 'r', encoding='utf-8').read()
old = "for tok in ('<img>', '<end_of_image>'):"
new = "for tok in ('\n', '<end_of_image>'):" # Note: fix_tokens replaces <img> with actual character, let's keep original replacement string
content = content.replace(old, new)
open(f, 'w', encoding='utf-8').write(content)
idx = content.find('for tok in')
print(repr(content[idx:idx+70]))
print('Done')
