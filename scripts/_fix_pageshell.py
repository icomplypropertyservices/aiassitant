"""Repair broken PageShell migrations and finish simple wrapper swaps."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"


def fix_tasks_board() -> None:
    p = ROOT / "TasksBoard.jsx"
    src = p.read_text(encoding="utf-8")
    # loading close
    src = src.replace(
        """      <PageShell wide>
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: '64px 24px' }}>
            <Spin size="large" tip="Loading tasks board…" />
          </div>
        </Card>
      </div>""",
        """      <PageShell wide>
        <Card className="aba-soft-card">
          <div style={{ textAlign: 'center', padding: '64px 24px' }}>
            <Spin size="large" tip="Loading tasks board…" />
          </div>
        </Card>
      </PageShell>""",
    )
    # accidental close inside result pre block
    src = src.replace(
        """                  <div style={{ background: '#f6f8fa', padding: 12, borderRadius: 8, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                    {detail.result}
                  </PageShell>""",
        """                  <div style={{ background: '#f6f8fa', padding: 12, borderRadius: 8, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                    {detail.result}
                  </div>""",
    )
    p.write_text(src, encoding="utf-8")
    print("TasksBoard fixed", src.count("<PageShell"), src.count("</PageShell>"))


def fix_customer_detail() -> None:
    p = ROOT / "CustomerDetail.jsx"
    src = p.read_text(encoding="utf-8")
    src = src.replace(
        """      <PageShell style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>""",
        """      <PageShell style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </PageShell>""",
    )
    # diary notes div wrongly closed as PageShell
    src = src.replace(
        """{d.notes && <div style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 12 }}>{d.notes}</PageShell>}""",
        """{d.notes && <div style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 12 }}>{d.notes}</div>}""",
    )
    # also multi-line form
    src = src.replace(
        """{d.notes && <div style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 12 }}>{d.notes}</div>}""".replace(
            "</div>", "</PageShell>"
        ),
        """{d.notes && <div style={{ whiteSpace: 'pre-wrap', marginTop: 2, fontSize: 12 }}>{d.notes}</div>}""",
    )
    # direct bad close if present as separate lines
    bad = "{d.notes}</PageShell>"
    if bad in src:
        src = src.replace(bad, "{d.notes}</div>")
    p.write_text(src, encoding="utf-8")
    print("CustomerDetail fixed", src.count("<PageShell"), src.count("</PageShell>"))


def swap_shell_inner(src: str) -> str:
    """Replace aba-page-shell-inner wrappers that use pageWrap or inline maxWidth."""
    # style={pageWrap}
    src = re.sub(
        r'<div className="aba-page-shell-inner" style=\{pageWrap\}>',
        "<PageShell>",
        src,
    )
    src = re.sub(
        r"<div className=\"aba-page-shell-inner\" style=\{\{ width: '100%', maxWidth: 1120, margin: '0 auto' \}\}>",
        "<PageShell>",
        src,
    )
    src = re.sub(
        r'<div className="aba-page-shell-inner" style=\{\{ width: \'100%\', maxWidth: 1120, margin: \'0 auto\' \}\}>',
        "<PageShell>",
        src,
    )
    src = re.sub(
        r"<div className=\"aba-page-shell-inner\" style=\{\{ width: '100%', maxWidth: 1120, margin: '0 auto', textAlign: 'center', padding: 48 \}\}>",
        "<PageShell style={{ textAlign: 'center', padding: 48 }}>",
        src,
    )
    return src


def balance_page_shell_closes(src: str) -> str:
    """Pair unmatched PageShell opens by converting matching outer closes.

    Strategy: only convert `</div>` that appear immediately after common end patterns
    when opens > closes. Walk from the end and convert one at a time when the
    next unmatched open is a PageShell.
    """
    opens = len(re.findall(r"<PageShell\b", src))
    closes = src.count("</PageShell>")
    # Heuristic: after converting open tags, any remaining shell-inner openers
    # that became PageShell need their matching close — convert the </div>
    # that immediately closes those return trees.
    # Safer approach for our known patterns: for each PageShell open that is
    # a full-return wrapper, the matching close is the first </div> at the same
    # indent level after the open.

    lines = src.splitlines(keepends=True)
    stack: list[tuple[str, int]] = []  # (tag, line_idx)
    out = lines[:]

    i = 0
    while i < len(out):
        line = out[i]
        # opening PageShell
        if re.search(r"<PageShell\b[^>]*>", line) and not re.search(r"</PageShell>", line):
            # self-closing? no
            if "/>" not in line.split("PageShell", 1)[-1][:20]:
                stack.append(("PageShell", i))
        # opening plain div (track only if stack has PageShell looking for close)
        opens_div = len(re.findall(r"<div\b", line))
        closes_div = line.count("</div>")
        # also handle multi on one line
        # When we see </div>, if stack top is PageShell and this close is the
        # shell's close (div-depth zero under shell), convert it.
        # Simpler stack of frames:
        i += 1

    # Different algorithm using token scan
    tokens = []
    for li, line in enumerate(lines):
        for m in re.finditer(r"<PageShell\b[^>]*\/?>|</PageShell>|<div\b[^>]*\/?>|</div>", line):
            tok = m.group(0)
            tokens.append((li, m.start(), tok))

    stack2: list[tuple[str, int, int]] = []  # kind, line, start
    convert: list[tuple[int, int]] = []  # line, start of </div> to convert

    for li, start, tok in tokens:
        if tok.startswith("<PageShell") and not tok.endswith("/>"):
            stack2.append(("PageShell", li, start))
        elif tok.startswith("<div") and not tok.endswith("/>"):
            stack2.append(("div", li, start))
        elif tok == "</PageShell>":
            # pop until PageShell
            while stack2 and stack2[-1][0] != "PageShell":
                stack2.pop()
            if stack2 and stack2[-1][0] == "PageShell":
                stack2.pop()
        elif tok == "</div>":
            if stack2 and stack2[-1][0] == "div":
                stack2.pop()
            elif stack2 and stack2[-1][0] == "PageShell":
                # this </div> should close the PageShell
                convert.append((li, start))
                stack2.pop()

    # apply conversions from end so offsets stay valid within a line
    by_line: dict[int, list[int]] = {}
    for li, start in convert:
        by_line.setdefault(li, []).append(start)

    new_lines = []
    for li, line in enumerate(lines):
        if li in by_line:
            # replace from rightmost start
            for start in sorted(by_line[li], reverse=True):
                # find </div> at start
                if line[start : start + 6] == "</div>":
                    line = line[:start] + "</PageShell>" + line[start + 6 :]
        new_lines.append(line)

    src2 = "".join(new_lines)
    return src2


def migrate_simple_files() -> None:
    files = [
        "Ops.jsx",
        "Business.jsx",
        "Workspace.jsx",
        "Training.jsx",
        "Hierarchy.jsx",
        "Agents.jsx",
        "Meetings.jsx",
        "MeetingRoom.jsx",
        "Humans.jsx",
        "Permissions.jsx",
        "Settings.jsx",
    ]
    for name in files:
        p = ROOT / name
        src = p.read_text(encoding="utf-8")
        if "PageShell" not in src:
            # add import after last import
            m = list(re.finditer(r"^import .+$", src, re.M))
            if m:
                last = m[-1]
                src = src[: last.end()] + "\nimport PageShell from '../components/PageShell'" + src[last.end() :]
        before = src
        src = swap_shell_inner(src)
        src = balance_page_shell_closes(src)
        # Remove unused pageWrap const if no longer referenced
        if "pageWrap" not in src.replace("const pageWrap", ""):
            src = re.sub(
                r"\n(?:/\*\*[^*]*\*/\s*)?const pageWrap = \{[^}]+\}\n",
                "\n",
                src,
                count=1,
            )
        elif "style={pageWrap}" not in src and "pageWrap" in src:
            # const still there but unused
            if re.search(r"const pageWrap = \{", src) and src.count("pageWrap") == 1:
                src = re.sub(r"\n(?:/\*\*[^*]*\*/\s*)?const pageWrap = \{[^}]+\}\n", "\n", src, count=1)
            elif re.search(r"const pageWrap = \{", src):
                # only definition left?
                refs = len(re.findall(r"pageWrap", src))
                if refs == 1:
                    src = re.sub(r"\n(?:/\*\*[^*]*\*/\s*)?const pageWrap = \{[^}]+\}\n", "\n", src, count=1)
        p.write_text(src, encoding="utf-8")
        o = len(re.findall(r"<PageShell\b", src))
        c = src.count("</PageShell>")
        leftover = "pageWrap" in src and "style={pageWrap}" in src
        print(f"{name}: opens={o} closes={c} leftover_pageWrap_style={leftover} changed={src!=before}")


def main() -> None:
    fix_tasks_board()
    fix_customer_detail()
    migrate_simple_files()


if __name__ == "__main__":
    main()
