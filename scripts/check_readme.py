"""Check every relative image/link in README.md resolves on disk. Fails loudly."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
readme = os.path.join(ROOT, "README.md")
text = open(readme, encoding="utf8").read()

missing = []
checked = 0

for match in re.finditer(r'<img\s+[^>]*src="([^"]+)"', text):
    src = match.group(1)
    if src.startswith(("http://", "https://")):
        continue
    checked += 1
    path = os.path.join(ROOT, src)
    if not os.path.exists(path):
        missing.append(src)
    else:
        print(f"  ok  img  {src}  ({os.path.getsize(path)//1024} KB)")

for match in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', text):
    src = match.group(1)
    if src.startswith(("http://", "https://")):
        continue
    checked += 1
    path = os.path.join(ROOT, src)
    if not os.path.exists(path):
        missing.append(src)
    else:
        print(f"  ok  md   {src}")

for match in re.finditer(r'\]\(((?:docs|scripts|apps)/[^)#]+)\)', text):
    src = match.group(1)
    checked += 1
    path = os.path.join(ROOT, src)
    if not os.path.exists(path):
        missing.append(src)
    else:
        print(f"  ok  link {src}")

print(f"\nchecked {checked} local references")
if missing:
    print("MISSING:")
    for m in missing:
        print("  -", m)
    sys.exit(1)
print("all references resolve")
