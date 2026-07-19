"""One-shot: wrap remaining pages in PageShell (idempotent-ish)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"


def ensure_import(src: str, name: str = "PageShell", path: str = "../components/PageShell") -> str:
    if re.search(rf"import\s+{name}\b", src):
        return src
    # Prefer after other component imports
    m = list(re.finditer(r"^import .+$", src, re.M))
    if not m:
        return f"import {name} from '{path}'\n{src}"
    last = m[-1]
    return src[: last.end()] + f"\nimport {name} from '{path}'" + src[last.end() :]


def drop_page_wrap_const(src: str) -> str:
    """Remove common pageWrap / PAGE_WRAP constants."""
    src = re.sub(
        r"\n/\*\*[^*]*\*/\s*\nconst pageWrap = \{[^}]+\}\n",
        "\n",
        src,
        count=1,
    )
    src = re.sub(
        r"\nconst pageWrap = \{[^}]+\}\n",
        "\n",
        src,
        count=1,
    )
    src = re.sub(
        r"\n/\*[^*]*\*/\s*\nconst PAGE_WRAP = \{[^}]+\}\n",
        "\n",
        src,
        count=1,
    )
    src = re.sub(
        r"\nconst PAGE_WRAP = \{[^}]+\}\n",
        "\n",
        src,
        count=1,
    )
    return src


def replace_openers(src: str) -> str:
    patterns = [
        (
            r'<div className="aba-page-shell-inner" style=\{pageWrap\}>',
            "<PageShell>",
        ),
        (
            r'<div className="aba-page-shell-inner is-wide tasks-board-page">',
            '<PageShell wide className="tasks-board-page">',
        ),
        (
            r'<div className="aba-page-shell-inner is-wide">',
            "<PageShell wide>",
        ),
        (
            r'<div className="aba-page-shell-inner is-narrow"[^>]*>',
            "<PageShell narrow>",
        ),
        (
            r"<div className=\"aba-page-shell-inner\" style=\{\{ width: '100%', maxWidth: 1120, margin: '0 auto' \}\}>",
            "<PageShell>",
        ),
        (
            r"<div className=\"aba-page-shell-inner\" style=\{\{ width: '100%', maxWidth: 1120, margin: '0 auto', textAlign: 'center', padding: 48 \}\}>",
            "<PageShell style={{ textAlign: 'center', padding: 48 }}>",
        ),
        (
            r'<div className="aba-page-shell-inner" style=\{PAGE_WRAP\}>',
            "<PageShell>",
        ),
        (
            r'<div className="aba-page-shell" style=\{PAGE_WRAP\}>',
            "<PageShell>",
        ),
        (
            r'<div className="aba-page-shell" style=\{pageWrap\}>',
            "<PageShell>",
        ),
    ]
    for old, new in patterns:
        src = src.replace(old, new)
    return src


def balance_closes(src: str) -> str:
    """If more opens than closes, rewrite trailing outer </div> to </PageShell>."""
    opens = len(re.findall(r"<PageShell\b", src))
    closes = src.count("</PageShell>")
    while opens > closes:
        # Prefer replacing a closing tag that matches shell-inner usage at end of returns
        idx = src.rfind("</div>")
        if idx < 0:
            break
        src = src[:idx] + "</PageShell>" + src[idx + 6 :]
        closes += 1
    return src


def migrate_file(rel: str, extra: callable | None = None) -> None:
    path = ROOT / rel
    if not path.exists():
        print(f"skip missing {rel}")
        return
    src = path.read_text(encoding="utf-8")
    original = src
    src = ensure_import(src)
    src = drop_page_wrap_const(src)
    src = replace_openers(src)
    if extra:
        src = extra(src)
    src = balance_closes(src)
    # Clean empty className=""
    src = src.replace(' className=""', "")
    if src != original:
        path.write_text(src, encoding="utf-8")
        n_open = len(re.findall(r"<PageShell\b", src))
        n_close = src.count("</PageShell>")
        print(f"updated {rel}: PageShell opens={n_open} closes={n_close}")
    else:
        print(f"unchanged {rel}")


def ops_extra(src: str) -> str:
    # pageWrap may remain as style={{...}} if const removed — already handled
    return src


def main() -> None:
    files = [
        "Settings.jsx",
        "Humans.jsx",
        "Permissions.jsx",
        "Ops.jsx",
        "Business.jsx",
        "Workspace.jsx",
        "Training.jsx",
        "Hierarchy.jsx",
        "Agents.jsx",
        "Meetings.jsx",
        "TasksBoard.jsx",
        "CompanyProfile.jsx",
        "CustomerDetail.jsx",
        "MeetingRoom.jsx",
    ]
    for f in files:
        migrate_file(f)

    # Special: CompanyProfile uses aba-page and raw pageWrap styles
    p = ROOT / "CompanyProfile.jsx"
    if p.exists():
        src = p.read_text(encoding="utf-8")
        src = ensure_import(src)
        src = drop_page_wrap_const(src)
        src = src.replace('<div style={pageWrap}>', "<PageShell>")
        src = src.replace(
            '<div className="aba-page" style={{ ...pageWrap, overflowX: \'hidden\' }}>',
            "<PageShell style={{ overflowX: 'hidden' }}>",
        )
        src = src.replace(
            '<div className="aba-page" style={{ ...pageWrap, overflowX: "hidden" }}>',
            '<PageShell style={{ overflowX: "hidden" }}>',
        )
        src = balance_closes(src)
        p.write_text(src, encoding="utf-8")
        print("CompanyProfile special pass")

    p = ROOT / "CustomerDetail.jsx"
    if p.exists():
        src = p.read_text(encoding="utf-8")
        src = ensure_import(src)
        src = drop_page_wrap_const(src)
        src = re.sub(
            r"<div style=\{\{\s*\.\.\.pageWrap,\s*textAlign: 'center', padding: 80\s*\}\}>",
            "<PageShell style={{ textAlign: 'center', padding: 80 }}>",
            src,
        )
        src = src.replace("<div style={pageWrap}>", "<PageShell>")
        src = balance_closes(src)
        p.write_text(src, encoding="utf-8")
        print("CustomerDetail special pass")

    p = ROOT / "MeetingRoom.jsx"
    if p.exists():
        src = p.read_text(encoding="utf-8")
        src = ensure_import(src)
        src = drop_page_wrap_const(src)
        src = src.replace("<div style={pageWrap}>", "<PageShell>")
        src = balance_closes(src)
        p.write_text(src, encoding="utf-8")
        print("MeetingRoom special pass")

    # TasksBoard loading state may not use shell
    p = ROOT / "TasksBoard.jsx"
    if p.exists():
        src = p.read_text(encoding="utf-8")
        src = ensure_import(src)
        src = src.replace(
            'if (loading && !board) {\n    return <div style={{ textAlign: \'center\', padding: 80 }}><Spin size="large" /></div>\n  }',
            'if (loading && !board) {\n    return (\n      <PageShell wide style={{ textAlign: \'center\', padding: 80 }}>\n        <Spin size="large" />\n      </PageShell>\n    )\n  }',
        )
        src = src.replace(
            '<div className="aba-page-shell-inner is-wide">',
            "<PageShell wide>",
        )
        src = src.replace(
            '<div className="aba-page-shell-inner is-wide tasks-board-page">',
            '<PageShell wide className="tasks-board-page">',
        )
        # legacy maxWidth 1480 wrapper
        src = src.replace(
            "<div style={{ maxWidth: 1480, margin: '0 auto', width: '100%' }}>",
            "<PageShell wide>",
        )
        src = balance_closes(src)
        p.write_text(src, encoding="utf-8")
        print("TasksBoard special pass")


if __name__ == "__main__":
    main()
