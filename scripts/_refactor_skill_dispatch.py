"""
Replace execute_skill's giant if/elif tree with a registry lookup.

Keeps all _skill_* implementations in agent_skills.py; only changes dispatch shape.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "backend" / "app" / "agent_skills.py"
DISPATCH = ROOT / "backend" / "app" / "skill_dispatch.py"


def main():
    text = SKILLS.read_text(encoding="utf-8")

    # Locate try block inside execute_skill
    start_marker = "    try:\n        if skill_id == \"spawn_agent\":"
    end_marker = "    except Exception as e:\n        result = {\"ok\": False, \"error\": str(e)}"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit(f"markers not found start={start} end={end}")

    block = text[start:end]
    # Parse arms: if/elif skill_id == "x" or in ("a","b")
    # Also: elif is_custom or ...
    lines = block.splitlines()

    # Build list of (keys: list[str]|None special, await_expr)
    entries: list[tuple[list[str] | str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # match if/elif skill_id == "foo":
        m_eq = re.match(r'(?:if|elif)\s+skill_id\s*==\s*"([^"]+)"\s*:\s*$', stripped)
        m_in = re.match(r'(?:if|elif)\s+skill_id\s+in\s+\(([^)]+)\)\s*:\s*$', stripped)
        m_custom = re.match(
            r'elif\s+is_custom\s+or\s+\(meta\s+or\s+\{\}\)\.get\("handler"\)\s*==\s*"created_skill"\s*:\s*$',
            stripped,
        )
        m_else = re.match(r'else\s*:\s*$', stripped)

        if m_eq or m_in or m_custom or m_else:
            # next non-empty line should be result = await ...
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                break
            res_line = lines[j].strip()
            m_res = re.match(r'result\s*=\s*await\s+(.+)$', res_line)
            if not m_res:
                i += 1
                continue
            call = m_res.group(1).rstrip()
            if m_eq:
                entries.append(([m_eq.group(1)], call))
            elif m_in:
                ids = re.findall(r'"([^"]+)"', m_in.group(1))
                entries.append((ids, call))
            elif m_custom:
                entries.append(("__custom__", call))
            elif m_else:
                entries.append(("__default__", call))
            i = j + 1
            continue
        i += 1

    print(f"parsed {len(entries)} dispatch arms")

    # Generate skill_dispatch.py that builds handlers lazily from agent_skills module
    # We register after agent_skills loads handlers - chicken/egg.
    # Better: put registry builder IN agent_skills after all _skill_* defs,
    # and only replace the try block with lookup.

    # Generate mapping as Python source embedded in agent_skills
    map_lines = [
        "",
        "# ── Skill handler registry (replaces elif chain in execute_skill) ─────────",
        "# Built once at import; keys are skill_id strings.",
        "",
        "def _register_skill_handlers() -> dict:",
        "    \"\"\"Map skill_id -> async callable(db, agent, user, args, *, meta, skill_id, custom_row).\"\"\"",
        "    async def _wrap_std(fn):",
        "        async def _h(db, agent, user, args, *, meta=None, skill_id=None, custom_row=None):",
        "            return await fn(db, agent, user, args)",
        "        return _h",
        "",
        "    async def _wrap_meta(fn):",
        "        async def _h(db, agent, user, args, *, meta=None, skill_id=None, custom_row=None):",
        "            return await fn(db, agent, user, skill_id, meta, args)",
        "        return _h",
        "",
        "    async def _wrap_created(fn):",
        "        async def _h(db, agent, user, args, *, meta=None, skill_id=None, custom_row=None):",
        "            return await fn(db, agent, user, skill_id, meta, args, custom_row)",
        "        return _h",
        "",
        "    async def _wrap_extra(fn, *extra):",
        "        async def _h(db, agent, user, args, *, meta=None, skill_id=None, custom_row=None, _extra=extra, _fn=fn):",
        "            return await _fn(db, agent, user, *_extra, args) if False else await _fn(db, agent, user, *(_extra + (args,)))",
        "        return _h",
        "",
        "    reg = {}",
    ]

    # Classify calls:
    # _skill_spawn(db, agent, user, args) -> std
    # _skill_catalog_deliverable(db, agent, user, skill_id, meta, args) -> meta
    # _skill_run_created(db, agent, user, skill_id, meta, args, custom_row) -> created
    # _skill_hubspot_action(db, agent, user, "create_contact", args) -> extra string before args
    # _skill_shopify_action(db, agent, user, "get_products", args)

    default_call = None
    custom_call = None
    for keys, call in entries:
        if keys == "__default__":
            default_call = call
            continue
        if keys == "__custom__":
            custom_call = call
            continue
        # parse function name and args inside call
        m = re.match(r'(_skill_\w+)\((.*)\)$', call)
        if not m:
            print("skip unparsed", call)
            continue
        fn, arglist = m.group(1), m.group(2)
        # determine wrapper type from arglist
        if "custom_row" in arglist:
            wrap = f"await {fn}(db, agent, user, skill_id, meta, args, custom_row)"
            maker = "created"
        elif "skill_id, meta, args" in arglist or "skill_id, meta" in arglist:
            wrap = f"await {fn}(db, agent, user, skill_id, meta, args)"
            maker = "meta"
        elif re.search(r',\s*"[^"]+"\s*,\s*args\s*$', arglist) or re.search(
            r"db, agent, user, \"[^\"]+\", args", arglist
        ):
            # extract quoted extra args between user and args
            extras = re.findall(r'"([^"]*)"', arglist)
            # typically one subaction
            if extras:
                extras_py = ", ".join(repr(e) for e in extras)
                wrap = f"await {fn}(db, agent, user, {extras_py}, args)"
            else:
                wrap = f"await {fn}(db, agent, user, args)"
            maker = "std_extra"
        else:
            wrap = f"await {fn}(db, agent, user, args)"
            maker = "std"

        for sid in keys if isinstance(keys, list) else [keys]:
            # generate closure via factory pattern in dict
            map_lines.append(f"    # {sid}")
            if maker == "std":
                map_lines.append(
                    f"    reg[{sid!r}] = (lambda _fn={fn}: "
                    f"(lambda db, agent, user, args, *, meta=None, skill_id=None, custom_row=None, __f=_fn: "
                    f"__import__('asyncio').iscoroutinefunction(__f) and __f(db, agent, user, args)))()  # placeholder"
                )
            # Actually lambdas with async are messy. Use explicit async defs in a loop-friendly way.

    # Simpler approach: generate a flat dict of skill_id -> coroutine function names + mode + extras
    # Then a single _invoke_skill_handler resolves them.

    table_rows = []
    for keys, call in entries:
        if keys == "__default__":
            default_call = call
            continue
        if keys == "__custom__":
            custom_call = call
            continue
        m = re.match(r'(_skill_\w+)\((.*)\)$', call)
        if not m:
            continue
        fn, arglist = m.group(1), m.group(2)
        if "custom_row" in arglist:
            mode, extras = "created", ()
        elif re.search(r'skill_id,\s*meta,\s*args', arglist):
            mode, extras = "meta", ()
        else:
            quoted = re.findall(r'"([^"]*)"', arglist)
            # exclude if no quoted between user and args - check pattern
            if re.search(r'user,\s*"[^"]+"\s*,\s*args', arglist):
                mode, extras = "extra", tuple(quoted)
            else:
                mode, extras = "std", ()
        for sid in keys:
            table_rows.append((sid, fn, mode, extras))

    # Write skill_handlers table + invoke into agent_skills by replacing try block
    gen = [
        "    try:",
        "        result = await _dispatch_skill(",
        "            skill_id, db, agent, user, args,",
        "            meta=meta, is_custom=is_custom, custom_row=custom_row,",
        "        )",
        "    except Exception as e:",
        "        result = {\"ok\": False, \"error\": str(e)}",
        "",
    ]

    # Build _dispatch_skill + HANDLER_TABLE before execute_skill
    handler_fn = [
        "",
        "# Auto-generated skill dispatch table (from former elif chain). Do not hand-edit;",
        "# re-run scripts/_refactor_skill_dispatch.py after adding skills, or append to HANDLER_TABLE.",
        "",
        "# skill_id -> (handler_attr, mode, extra_args_tuple)",
        "# mode: std | extra | meta | created | default",
        "HANDLER_TABLE: dict[str, tuple[str, str, tuple]] = {",
    ]
    for sid, fn, mode, extras in table_rows:
        handler_fn.append(f"    {sid!r}: ({fn!r}, {mode!r}, {extras!r}),")
    handler_fn.append("}")
    handler_fn.append("")
    if default_call:
        m = re.match(r'(_skill_\w+)', default_call)
        default_fn = m.group(1) if m else "_skill_catalog_deliverable"
    else:
        default_fn = "_skill_catalog_deliverable"
    if custom_call:
        m = re.match(r'(_skill_\w+)', custom_call)
        custom_fn = m.group(1) if m else "_skill_run_created"
    else:
        custom_fn = "_skill_run_created"

    handler_fn.extend([
        f"DEFAULT_SKILL_HANDLER = {default_fn!r}",
        f"CUSTOM_SKILL_HANDLER = {custom_fn!r}",
        "",
        "async def _dispatch_skill(",
        "    skill_id: str,",
        "    db,",
        "    agent,",
        "    user,",
        "    args: dict,",
        "    *,",
        "    meta=None,",
        "    is_custom: bool = False,",
        "    custom_row=None,",
        "):",
        "    \"\"\"Registry lookup — replaces the historical if/elif skill tree.\"\"\"",
        "    g = globals()",
        "    if is_custom or (meta or {}).get(\"handler\") == \"created_skill\":",
        "        fn = g.get(CUSTOM_SKILL_HANDLER)",
        "        if not fn:",
        "            return {\"ok\": False, \"error\": \"custom skill handler missing\"}",
        "        return await fn(db, agent, user, skill_id, meta, args, custom_row)",
        "",
        "    entry = HANDLER_TABLE.get(skill_id)",
        "    if entry:",
        "        fname, mode, extras = entry",
        "        fn = g.get(fname)",
        "        if not fn:",
        "            return {\"ok\": False, \"error\": f\"handler {fname} missing\"}",
        "        if mode == \"std\":",
        "            return await fn(db, agent, user, args)",
        "        if mode == \"extra\":",
        "            return await fn(db, agent, user, *extras, args)",
        "        if mode == \"meta\":",
        "            return await fn(db, agent, user, skill_id, meta, args)",
        "        if mode == \"created\":",
        "            return await fn(db, agent, user, skill_id, meta, args, custom_row)",
        "        return await fn(db, agent, user, args)",
        "",
        "    # Catalog skills without dedicated side-effects",
        "    fn = g.get(DEFAULT_SKILL_HANDLER)",
        "    if not fn:",
        "        return {\"ok\": False, \"error\": f\"Unknown skill '{skill_id}'\"}",
        "    return await fn(db, agent, user, skill_id, meta, args)",
        "",
    ])

    # Insert HANDLER_TABLE just before `async def execute_skill`
    insert_at = text.find("async def execute_skill(")
    if insert_at < 0:
        raise SystemExit("execute_skill not found for insert")

    # Avoid double-insert
    if "HANDLER_TABLE:" in text and "_dispatch_skill" in text:
        print("already refactored?")
        # still replace try block
        text2 = text[:start] + "\n".join(gen) + "\n" + text[end:]
    else:
        text2 = text[:insert_at] + "\n".join(handler_fn) + "\n" + text[insert_at:]
        # re-find start/end after insert
        start2 = text2.find(start_marker)
        end2 = text2.find(end_marker, start2)
        if start2 < 0:
            # maybe already different
            start2 = text2.find("    try:\n        if skill_id == \"spawn_agent\":")
        end2 = text2.find(end_marker, start2 if start2 >= 0 else 0)
        if start2 < 0 or end2 < 0:
            raise SystemExit(f"post-insert markers missing {start2} {end2}")
        text2 = text2[:start2] + "\n".join(gen) + "\n" + text2[end2:]

    SKILLS.write_text(text2, encoding="utf-8")
    print("wrote", SKILLS)
    print("HANDLER_TABLE size", len(table_rows))
    print("default", default_fn, "custom", custom_fn)


if __name__ == "__main__":
    main()
