import os, re
from pathlib import Path
keys = []
for p in Path(".").glob(".env*"):
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        continue
    for line in text.splitlines():
        if re.match(r"^\s*(ABA_|TEST_|ADMIN_|DEMO_|USER_|LOGIN_)", line, re.I) or "EMAIL" in line.upper() and "GOOGLE" not in line.upper():
            k = line.split("=",1)[0].strip()
            keys.append(f"{p.name}:{k}")
print("\n".join(keys[:50]))
