"""Replace ad-hoc ownership checks with ownership.require_owned."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app" / "routers"

PAT_A = re.compile(
    r"(?P<indent>[ \t]*)(?P<var>\w+)\s*=\s*db\.get\((?P<model>models\.\w+),\s*(?P<id>[^)]+)\)\s*\n"
    r"(?P=indent)if\s+not\s+(?P=var)\s+or\s+(?P=var)\.(?P<field>user_id|owner_user_id)\s*!=\s*user\.id\s*:\s*\n"
    r"(?P=indent)[ \t]+raise\s+HTTPException\(404,\s*(?P<msg>[\"'][^\"']+[\"'])\)\s*\n",
    re.M,
)

PAT_B = re.compile(
    r"(?P<indent>[ \t]*)(?P<var>\w+)\s*=\s*db\.get\((?P<model>models\.\w+),\s*(?P<id>[^)]+)\)\s*\n"
    r"(?P=indent)if\s+not\s+(?P=var)\s+or\s+\((?P=var)\.(?P<field>user_id|owner_user_id)\s*!=\s*user\.id\s+and\s+user\.role\s*!=\s*[\"']admin[\"']\)\s*:\s*\n"
    r"(?P=indent)[ \t]+raise\s+HTTPException\(404,\s*(?P<msg>[\"'][^\"']+[\"'])\)\s*\n",
    re.M,
)


def ensure_import(text: str) -> str:
    if "require_owned" in text and "ownership" in text:
        return text
    m = re.search(r"(from \.\.[\w.]+ import [^\n]+\n)+", text)
    if m:
        return text[: m.end()] + "from ..ownership import require_owned\n" + text[m.end() :]
    return "from ..ownership import require_owned\n" + text


def repl(m: re.Match) -> str:
    ind = m.group("indent")
    var = m.group("var")
    model = m.group("model")
    oid = m.group("id").strip()
    field = m.group("field")
    msg = m.group("msg")
    return (
        f"{ind}{var} = require_owned(\n"
        f"{ind}    db, {model}, {oid}, user,\n"
        f"{ind}    user_field={field!r}, not_found={msg},\n"
        f"{ind})\n"
    )


def main():
    total = 0
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        text2, n1 = PAT_A.subn(repl, text)
        text2, n2 = PAT_B.subn(repl, text2)
        n = n1 + n2
        if n:
            text2 = ensure_import(text2)
            path.write_text(text2, encoding="utf-8")
            print(f"{path.name}: {n}")
            total += n
    print("total", total)


if __name__ == "__main__":
    main()
