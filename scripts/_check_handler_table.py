from pathlib import Path
import re

t = Path("backend/app/agent_skills.py").read_text(encoding="utf-8")
m = re.search(r"HANDLER_TABLE.*?= \{(.*?)\n\}", t, re.S)
block = m.group(1)
extra = [ln for ln in block.splitlines() if "'extra'" in ln]
print("extra mode count", len(extra))
for ln in extra[:25]:
    print(ln.strip()[:120])
print("--- shopify ---")
for ln in block.splitlines():
    if "shopify" in ln:
        print(ln.strip()[:120])
print("--- hubspot ---")
for ln in block.splitlines():
    if "hubspot" in ln:
        print(ln.strip()[:120])
