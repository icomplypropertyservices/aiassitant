"""Extract AgentDetail skills tab into components/AgentSkillsPanel.jsx"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAIL = ROOT / "frontend" / "src" / "pages" / "AgentDetail.jsx"
OUT = ROOT / "frontend" / "src" / "components" / "AgentSkillsPanel.jsx"


def main():
    t = DETAIL.read_text(encoding="utf-8")
    start = t.find("key: 'skills'")
    if start < 0:
        raise SystemExit("skills tab not found")
    cstart = t.find("children: (", start)
    cend = t.find("key: 'settings'", cstart)
    chunk = t[cstart:cend]
    m = re.search(
        r"children:\s*\(\s*(<Space[\s\S]*?</Space>)\s*\),\s*\},?\s*\{?\s*$",
        chunk,
    )
    if not m:
        m = re.search(r"children:\s*\(\s*(<Space[\s\S]*?</Space>)", chunk)
    if not m:
        raise SystemExit("could not parse skills children")
    inner = m.group(1)
    lines = inner.splitlines()
    stripped = []
    for ln in lines:
        if ln.startswith("        "):
            stripped.append(ln[8:])
        else:
            stripped.append(ln)
    inner2 = "\n".join(stripped)

    OUT.write_text(
        f'''import React from 'react'
import {{
  Card, Space, Typography, Tag, List, Switch, Button, Form, Input, Select, message,
}} from 'antd'
import {{
  ThunderboltOutlined, RobotOutlined, AppstoreOutlined, TeamOutlined,
}} from '@ant-design/icons'
import {{ api }} from '../api'

/** Agent manage page — Skills tab body. */
export default function AgentSkillsPanel({{
  id, skills, setSkills, skillBusy, setSkillBusy,
  templates, spawnForm, load, setAllAgents, agentApps, humans, nav,
}}) {{
  return (
{inner2}
  )
}}
''',
        encoding="utf-8",
    )
    print("wrote", OUT, "lines", inner2.count("\n") + 20)

    replacement = """children: (
        <AgentSkillsPanel
          id={id}
          skills={skills}
          setSkills={setSkills}
          skillBusy={skillBusy}
          setSkillBusy={setSkillBusy}
          templates={templates}
          spawnForm={spawnForm}
          load={load}
          setAllAgents={setAllAgents}
          agentApps={agentApps}
          humans={humans}
          nav={nav}
        />
      ),
    },
    {
      key: 'settings'"""

    before = t[:cstart]
    after = t[cend:]  # starts with key: 'settings'
    if not after.startswith("key: 'settings'"):
        raise SystemExit(f"unexpected after: {after[:50]!r}")
    new_t = before + replacement + after[len("key: 'settings'") :]

    if "AgentSkillsPanel" not in new_t.split("export default")[0]:
        new_t = new_t.replace(
            "import PageShell from '../components/PageShell'",
            "import PageShell from '../components/PageShell'\n"
            "import AgentSkillsPanel from '../components/AgentSkillsPanel'",
        )
    DETAIL.write_text(new_t, encoding="utf-8")
    print("AgentDetail lines", new_t.count("\n") + 1)


if __name__ == "__main__":
    main()
