"""Quick verification script for hundreds-of-skills + spawn-40 work."""
import ast, re, sys

with open("app/agent_skills.py", encoding="utf-8") as f:
    src = f.read()

try:
    ast.parse(src)
    print("PYTHON_SYNTAX: OK")
except Exception as e:
    print("PYTHON_SYNTAX_FAIL:", e)
    sys.exit(1)

ids = re.findall(r'"id":\s*"([^"]+)"', src)
print("TOTAL_SKILLS:", len(ids))

has_meta = all(x in src for x in ("_skill_spawn_team", "_skill_bulk_enable_skills", "_skill_enable_skills_on"))
print("META_SPAWN_SKILLS_IMPL:", "OK" if has_meta else "MISSING")

with open("app/routers/agents.py", encoding="utf-8") as f:
    rsrc = f.read()
print("SEED_40_ENDPOINT:", "OK" if "seed-professional-40" in rsrc else "MISSING")

print("LAST_5_SKILLS:", ids[-5:])
print("VERIFICATION_COMPLETE")