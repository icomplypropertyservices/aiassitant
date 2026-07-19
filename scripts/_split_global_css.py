"""Split frontend/src/styles/global.css into domain CSS files + import shell."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src" / "styles" / "global.css"
OUT = ROOT / "frontend" / "src" / "styles" / "parts"

# Map comment banners → file names (first match wins for following content)
RULES = [
    (re.compile(r"mobile|hamburger|bottom.?nav|safe-area|@media \(max-width", re.I), "mobile.css"),
    (re.compile(r"live.?ops|marquee|ticker", re.I), "live-ops.css"),
    (re.compile(r"auth|login|subscribe|plan.?card", re.I), "auth-billing.css"),
    (re.compile(r"chat|message|voice|media", re.I), "chat-media.css"),
    (re.compile(r"page.?shell|page.?container|aba-page|centering|boxed", re.I), "layout.css"),
    (re.compile(r"ant design|ant-|App shell|page chrome", re.I), "antd-polish.css"),
]


def main():
    text = SRC.read_text(encoding="utf-8")
    # Split on top-level section comments like /* ── ... */
    parts = re.split(r"(?=\n/\* ─)", "\n" + text)
    if parts and not parts[0].strip():
        parts = parts[1:]

    buckets: dict[str, list[str]] = {
        "base.css": [],
        "layout.css": [],
        "antd-polish.css": [],
        "mobile.css": [],
        "live-ops.css": [],
        "auth-billing.css": [],
        "chat-media.css": [],
        "misc.css": [],
    }

    for chunk in parts:
        head = chunk[:200]
        target = "misc.css"
        if "AI Business Assistant" in head or "global polish" in head or chunk == parts[0]:
            target = "base.css"
        else:
            for rx, name in RULES:
                if rx.search(head):
                    target = name
                    break
            # content-based for chunks without clear header
            if target == "misc.css":
                if re.search(r"hamburger|bottom-nav|@media \(max-width:\s*768", chunk):
                    target = "mobile.css"
                elif re.search(r"live-ops|aba-live", chunk, re.I):
                    target = "live-ops.css"
                elif re.search(r"aba-page|PageShell|page-shell", chunk):
                    target = "layout.css"
                elif re.search(r"\.ant-", chunk):
                    target = "antd-polish.css"
        buckets[target].append(chunk.lstrip("\n") if chunk.startswith("\n") else chunk)

    OUT.mkdir(parents=True, exist_ok=True)
    order = [
        "base.css",
        "antd-polish.css",
        "layout.css",
        "mobile.css",
        "live-ops.css",
        "auth-billing.css",
        "chat-media.css",
        "misc.css",
    ]
    imports = []
    for name in order:
        content = "\n".join(buckets[name]).strip() + "\n"
        if not content.strip():
            continue
        (OUT / name).write_text(f"/* part: {name} */\n{content}", encoding="utf-8")
        imports.append(f'@import "./parts/{name}";')
        print(f"{name}: {content.count(chr(10))} lines")

    SRC.write_text(
        "/* AI Business Assistant — global styles (split into parts/) */\n"
        + "\n".join(imports)
        + "\n",
        encoding="utf-8",
    )
    print("global.css now import shell,", len(imports), "parts")


if __name__ == "__main__":
    main()
