import sqlite3, os
for path in ["backend/app.db", "app.db"]:
    if not os.path.exists(path):
        continue
    print("===", path, "===")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    print("tables", len(tables), tables[:30])
    if "users" in tables:
        for r in c.execute("SELECT id, email, name, role, plan, subscription_active FROM users LIMIT 30"):
            print(dict(r))
    if "companies" in tables:
        for r in c.execute("SELECT id, name, industry, owner_user_id FROM companies LIMIT 30"):
            print("co", dict(r))
    if "agents" in tables:
        for r in c.execute("SELECT id, name, hierarchy_role, company_id, owner_user_id, status FROM agents LIMIT 40"):
            print("ag", dict(r))
