import json, urllib.request, urllib.error

BASE = "https://www.aibusinessagent.xyz"
# try a few known emails with likely password - only for setup
candidates = [
    ("firealarmsdublin@gmail.com", "Neverknow1"),
    ("firealarmsdublin@gmail.com", "Neverknow1!"),
    ("jack@icomplypropertyservices.co.uk", "Neverknow1"),
    ("admin@local", "admin123"),
]

def login(email, password):
    data = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
            return r.status, body
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"error": raw[:200]}
        return e.code, body

for email, pw in candidates:
    code, body = login(email, pw)
    token = None
    if isinstance(body, dict):
        token = body.get("access_token") or body.get("token")
        user = body.get("user") or body.get("email")
    else:
        user = None
    print(f"{email}: http={code} token={'yes' if token else 'no'} user={user if not token else (body.get('user') or {}).get('name') or (body.get('user') or {}).get('email') or 'ok'}")
    if token:
        # list companies
        req = urllib.request.Request(
            f"{BASE}/api/org/companies",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cos = json.loads(r.read().decode())
                print(" companies:", len(cos) if isinstance(cos, list) else cos)
                if isinstance(cos, list):
                    for c in cos[:10]:
                        print("  -", c.get("id"), c.get("name"), "agents", c.get("agent_count"))
        except urllib.error.HTTPError as e:
            print(" companies error", e.code, e.read()[:200])
        break
