"""Pass 2: ownership when get and check are still on adjacent lines with role admin."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app" / "routers"

# if not x or x.field != user.id:  (without get on previous - skip)
# Pattern where get uses different spacing / 403

PAT = re.compile(
    r"(?P<indent>[ \t]*)(?P<var>\w+)\s*=\s*db\.get\((?P<model>models\.\w+),\s*(?P<id>[^)]+)\)\s*\n"
    r"(?P=indent)if\s+not\s+(?P=var)\s+or\s+\(?(?P=var)\.(?P<field>user_id|owner_user_id)\s*!=\s*user\.id"
    r"(?:\s+and\s+user\.role\s*!=\s*[\"']admin[\"'])?\)?\s*:\s*\n"
    r"(?P=indent)[ \t]+raise\s+HTTPException\((?P<code>404|403),\s*(?P<msg>[\"'][^\"']+[\"'])\)\s*\n",
    re.M,
)


def ensure_import(text: str) -> str:
    if "from ..ownership import require_owned" in text:
        return text
    m = re.search(r"(from \.\.[\w.]+ import [^\n]+\n)+", text)
    if m:
        return text[: m.end()] + "from ..ownership import require_owned\n" + text[m.end() :]
    return "from ..ownership import require_owned\n" + text


def main():
    total = 0
    for path in sorted(ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")

        def repl(m: re.Match) -> str:
            if m.group("code") not in ("404", "403"):
                return m.group(0)
            ind = m.group("indent")
            return (
                f"{ind}{m.group('var')} = require_owned(\n"
                f"{ind}    db, {m.group('model')}, {m.group('id').strip()}, user,\n"
                f"{ind}    user_field={m.group('field')!r}, not_found={m.group('msg')},\n"
                f"{ind})\n"
            )

        text2, n = PAT.subn(repl, text)
        if n:
            text2 = ensure_import(text2)
            path.write_text(text2, encoding="utf-8")
            print(path.name, n)
            total += n
    print("total", total)


if __name__ == "__main__":
    main()
