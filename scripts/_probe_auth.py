import json, urllib.request, urllib.error
BASE="https://www.aibusinessagent.xyz"
paths=["/api/auth/login","/api/auth/token","/api/login","/auth/login","/api/auth/register"]
for p in paths:
    try:
        req=urllib.request.Request(BASE+p, data=b'{}', headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            print(p, r.status, r.read()[:120])
    except urllib.error.HTTPError as e:
        print(p, e.code, e.read()[:160].decode('utf-8','replace'))
    except Exception as e:
        print(p, type(e).__name__, e)
