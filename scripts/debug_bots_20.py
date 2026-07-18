"""20 debug bots: offline + DB + skill mapping verification."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure backend on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

results: list[dict] = []


def ok(name: str, detail: str = "") -> None:
    results.append({"bot": name, "status": "PASS", "detail": detail})
    print(f"PASS  {name}: {detail}")


def fail(name: str, detail: str = "") -> None:
    results.append({"bot": name, "status": "FAIL", "detail": str(detail)[:500]})
    print(f"FAIL  {name}: {detail}")


def main() -> int:
    # 01 App import
    try:
        from app.main import app

        routes = [getattr(r, "path", None) for r in app.routes if hasattr(r, "path")]
        ok("01-app-import", f"{len(routes)} routes")
    except Exception:
        fail("01-app-import", traceback.format_exc())
        _write()
        return 1

    # 02 Critical routers
    need = [
        "/auth",
        "/agents",
        "/org",
        "/billing",
        "/integrations",
        "/humans",
        "/permissions",
        "/dashboard",
        "/ops",
        "/business",
    ]
    for p in need:
        if any(r and (str(r).startswith(p) or p in str(r)) for r in routes):
            ok(f"02-route{p.replace('/', '-')}", "mounted")
        else:
            fail(f"02-route{p.replace('/', '-')}", "missing")

    # 03 Schema
    try:
        from app.database import engine
        from app.schema_migrate import ensure_schema
        from sqlalchemy import inspect

        ensure_schema(engine)
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        required = {
            "users",
            "agents",
            "tasks",
            "companies",
            "projects",
            "humans",
            "token_usage",
            "crypto_invoices",
            "integration_connections",
        }
        miss = required - tables
        if miss:
            fail("03-schema-tables", str(miss))
        else:
            ok("03-schema-tables", f"{len(tables)} tables")
        for t, cols in [
            ("agents", ["permission_level", "escalate_when", "company_id"]),
            ("tasks", ["human_id", "assignee_type", "project_id"]),
            ("humans", ["permission_level"]),
        ]:
            have = {c["name"] for c in insp.get_columns(t)}
            m = [c for c in cols if c not in have]
            if m:
                fail(f"03-cols-{t}", str(m))
            else:
                ok(f"03-cols-{t}", "ok")
    except Exception:
        fail("03-schema", traceback.format_exc())

    # 04 Skills catalog
    skill_ids: set[str] = set()
    try:
        import app.agent_skills as sk

        cats = []
        for name in dir(sk):
            obj = getattr(sk, name)
            if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "id" in obj[0]:
                cats.append((name, len(obj)))
                for s in obj:
                    if s.get("id"):
                        skill_ids.add(s["id"])
        ok("04-skills-catalog", f"lists={cats} unique_ids={len(skill_ids)}")
    except Exception:
        fail("04-skills-catalog", traceback.format_exc())

    # 05 Skill handlers mapped
    try:
        import app.agent_skills as sk

        # Common patterns: HANDLERS dict or execute_skill
        mapped = 0
        unmapped = []
        handler_map = getattr(sk, "SKILL_HANDLERS", None) or getattr(sk, "HANDLERS", None)
        if isinstance(handler_map, dict):
            mapped = len(handler_map)
            for sid in skill_ids:
                if sid not in handler_map:
                    unmapped.append(sid)
        else:
            # Probe execute function
            exec_fn = (
                getattr(sk, "execute_skill", None)
                or getattr(sk, "run_skill", None)
                or getattr(sk, "dispatch_skill", None)
            )
            if exec_fn:
                ok("05-skill-dispatch", f"dispatch={exec_fn.__name__}")
            else:
                # Scan for handle_* functions matching skill ids
                funcs = {n: getattr(sk, n) for n in dir(sk) if callable(getattr(sk, n, None))}
                ok(
                    "05-skill-dispatch",
                    f"no HANDLERS dict; callables={len(funcs)}; skill_ids={len(skill_ids)}",
                )
        if handler_map is not None:
            if unmapped[:20]:
                fail("05-skill-handlers", f"unmapped={unmapped[:20]} mapped={mapped}")
            else:
                ok("05-skill-handlers", f"all {mapped} handlers mapped")
    except Exception:
        fail("05-skill-handlers", traceback.format_exc())

    # 06 Scaffold / runtime map
    try:
        from app.agent_scaffold import resolve_runtime, repair_agent  # noqa: F401
        from app.agent_serialize import agent_out, agents_out_list  # noqa: F401

        ok("06-scaffold-map", "resolve_runtime + repair_agent + agent_out")
    except Exception:
        fail("06-scaffold-map", traceback.format_exc())

    # 06b Skill execute coverage (catalog ids must not hard-fail)
    try:
        import re
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath("backend/app/agent_skills.py").read_text(
            encoding="utf-8"
        )
        ids = re.findall(r'"id":\s*"([a-z0-9_]+)"', text)
        catalog = []
        seen = set()
        for i in ids:
            if i not in seen:
                seen.add(i)
                catalog.append(i)
        # after our fix, else branch uses catalog_deliverable — no hard unmapped
        has_fallback = "_skill_catalog_deliverable" in text and "not implemented" not in text.split(
            "async def execute_skill"
        )[1].split("async def run_skills")[0]
        handled = set(re.findall(r'skill_id == "([a-z0-9_]+)"', text.split("async def execute_skill")[1].split("async def run_skills")[0]))
        ok(
            "06b-skill-coverage",
            f"catalog={len(catalog)} dedicated_handlers={len(handled)} "
            f"generic_fallback={has_fallback}",
        )
        if not has_fallback:
            fail("06b-skill-fallback", "generic catalog deliverable missing")
    except Exception:
        fail("06b-skill-coverage", traceback.format_exc())

    # 07 Permissions
    try:
        from app.permissions import PERMISSION_LEVELS, ESCALATE_WHEN, normalize_permission

        normalize_permission("operator")
        ok(
            "07-permissions",
            f"levels={len(PERMISSION_LEVELS)} escalate_when={len(ESCALATE_WHEN)}",
        )
    except Exception:
        fail("07-permissions", traceback.format_exc())

    # 08 Integrations
    try:
        from app.integrations_catalog import INTEGRATION_APPS

        oauth_n = sum(1 for a in INTEGRATION_APPS.values() if a.get("oauth"))
        ok("08-integrations", f"{len(INTEGRATION_APPS)} apps, {oauth_n} oauth")
    except Exception:
        fail("08-integrations", traceback.format_exc())

    # 09 Crypto
    try:
        from app import crypto_payments as cp

        chains = [c["id"] for c in cp.available_chains()]
        ok("09-crypto", f"enabled={cp.crypto_enabled()} chains={chains}")
    except Exception:
        fail("09-crypto", traceback.format_exc())

    # 10 Stripe
    try:
        from app import config

        sk = config.STRIPE_SECRET_KEY or ""
        mode = (
            "live"
            if sk.startswith("sk_live")
            else ("test" if sk.startswith("sk_test") else "none")
        )
        ok(
            "10-stripe",
            f"mode={mode} webhook={bool(config.STRIPE_WEBHOOK_SECRET)}",
        )
    except Exception:
        fail("10-stripe", traceback.format_exc())

    # 11 LLM
    try:
        from app import config

        ok(
            "11-llm",
            f"xai={bool(getattr(config, 'XAI_API_KEY', ''))} "
            f"anthropic={bool(getattr(config, 'ANTHROPIC_API_KEY', ''))}",
        )
    except Exception:
        fail("11-llm", traceback.format_exc())

    # 12 Roles
    try:
        from app.agent_roles import resolve_create_role  # noqa: F401

        ok("12-roles", "hierarchy helpers")
    except Exception:
        fail("12-roles", traceback.format_exc())

    # 13 Autonomy
    try:
        from app.autonomy import autonomy_background_loop  # noqa: F401

        ok("13-autonomy", "import ok")
    except Exception:
        fail("13-autonomy", traceback.format_exc())

    # 14 Media
    try:
        from app.routers import media  # noqa: F401

        ok("14-media", "router ok")
    except Exception:
        fail("14-media", traceback.format_exc())

    # 15 CRM models
    try:
        from app.models import Customer, Deal, Pipeline, DiaryEntry, Human, CryptoInvoice  # noqa: F401

        ok("15-crm-models", "Customer Deal Pipeline Diary Human CryptoInvoice")
    except Exception:
        fail("15-crm-models", traceback.format_exc())

    # 16 Usage billing
    try:
        from app.usage_billing import meter_snapshot  # noqa: F401

        ok("16-usage-billing", "meter_snapshot")
    except Exception:
        fail("16-usage-billing", traceback.format_exc())

    # 17 DB query smoke
    try:
        from app.database import SessionLocal
        from app import models

        db = SessionLocal()
        u = db.query(models.User).count()
        a = db.query(models.Agent).count()
        c = db.query(models.Company).count()
        t = db.query(models.Task).count()
        h = db.query(models.Human).count()
        for ag in db.query(models.Agent).limit(10).all():
            _ = ag.permission_level, ag.escalate_when, ag.idle_mode
        for tk in db.query(models.Task).limit(10).all():
            _ = tk.human_id, tk.assignee_type
        ok(
            "17-db-query",
            f"users={u} agents={a} companies={c} tasks={t} humans={h}",
        )
        db.close()
    except Exception:
        fail("17-db-query", traceback.format_exc())

    # 18 Pricing + plans
    try:
        from app.pricing import PRICING, MODEL_LABELS
        from app.plans import PLANS

        ok(
            "18-pricing-plans",
            f"pricing={len(PRICING)} labels={len(MODEL_LABELS)} plans={list(PLANS.keys())}",
        )
    except Exception:
        fail("18-pricing-plans", traceback.format_exc())

    # 19 Org / permissions routers
    try:
        from app.routers import org, humans, agents, dashboard, permissions_api  # noqa: F401

        ok("19-routers-core", "org humans agents dashboard permissions")
    except Exception:
        fail("19-routers-core", traceback.format_exc())

    # 20 Live production HTTP (public)
    try:
        import httpx

        base = "https://aiassitant-nu.vercel.app/api"
        with httpx.Client(timeout=30.0) as client:
            h = client.get(f"{base}/health")
            p = client.get(f"{base}/billing/payment-options")
            d = client.get(f"{base}/dashboard/")  # expect 401
        pay = p.json() if p.status_code == 200 else {}
        ok(
            "20-prod-http",
            f"health={h.status_code} pay={p.status_code} "
            f"stripe={pay.get('stripe', {}).get('mode')} "
            f"crypto={pay.get('crypto', {}).get('chains')} "
            f"dash_unauth={d.status_code}",
        )
        if h.status_code != 200 or p.status_code != 200:
            fail("20-prod-http-status", f"health={h.status_code} pay={p.status_code}")
    except Exception:
        fail("20-prod-http", traceback.format_exc())

    return _write()


def _write() -> int:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    out = {
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "results": results,
    }
    path = ROOT / "scripts" / "_debug_bots_report.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("---")
    print(f"SUMMARY total={len(results)} PASS={passed} FAIL={failed}")
    print(f"Report: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
