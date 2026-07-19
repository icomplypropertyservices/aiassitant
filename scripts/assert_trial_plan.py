#!/usr/bin/env python3
"""Assert free-trial plan caps: 10 agents, 2 companies (local + optional prod).

Usage:
  python scripts/assert_trial_plan.py
  python scripts/assert_trial_plan.py --prod
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Expected product caps (must match plans.TRIAL_*)
EXPECT_AGENTS = 10
EXPECT_COMPANIES = 2
EXPECT_PROJECTS = 2
EXPECT_TOKENS = 50_000


def _check_local() -> dict:
    from app.plans import (  # type: ignore
        TRIAL_AGENTS,
        TRIAL_COMPANIES,
        TRIAL_PROJECTS,
        TRIAL_TOKENS_INCLUDED,
        plan_limits,
        public_plans,
    )

    errs: list[str] = []
    if TRIAL_AGENTS != EXPECT_AGENTS:
        errs.append(f"TRIAL_AGENTS={TRIAL_AGENTS} want {EXPECT_AGENTS}")
    if TRIAL_COMPANIES != EXPECT_COMPANIES:
        errs.append(f"TRIAL_COMPANIES={TRIAL_COMPANIES} want {EXPECT_COMPANIES}")
    if TRIAL_PROJECTS != EXPECT_PROJECTS:
        errs.append(f"TRIAL_PROJECTS={TRIAL_PROJECTS} want {EXPECT_PROJECTS}")
    if TRIAL_TOKENS_INCLUDED != EXPECT_TOKENS:
        errs.append(f"TRIAL_TOKENS_INCLUDED={TRIAL_TOKENS_INCLUDED} want {EXPECT_TOKENS}")

    t = plan_limits("trial")
    for key, want in (
        ("agents", EXPECT_AGENTS),
        ("companies", EXPECT_COMPANIES),
        ("projects", EXPECT_PROJECTS),
        ("tokens_included", EXPECT_TOKENS),
    ):
        got = int(t.get(key) or 0)
        if got != want:
            errs.append(f"plan_limits('trial')[{key}]={got} want {want}")

    pub = public_plans().get("trial") or {}
    if int(pub.get("agents") or 0) != EXPECT_AGENTS:
        errs.append(f"public_plans trial agents={pub.get('agents')}")
    if int(pub.get("companies") or 0) != EXPECT_COMPANIES:
        errs.append(f"public_plans trial companies={pub.get('companies')}")

    features = " ".join(str(x) for x in (t.get("features") or []))
    if "10" not in features and "Up to 10" not in features:
        # features use f-string from constants — still require agent copy
        if f"Up to {EXPECT_AGENTS}" not in features:
            errs.append(f"trial features missing agent copy: {features!r}")
    if f"{EXPECT_COMPANIES} companies" not in features:
        errs.append(f"trial features missing companies copy: {features!r}")

    return {
        "ok": not errs,
        "errors": errs,
        "trial": {
            "agents": t.get("agents"),
            "companies": t.get("companies"),
            "projects": t.get("projects"),
            "tokens_included": t.get("tokens_included"),
        },
    }


def _check_prod(base: str) -> dict:
    url = base.rstrip("/") + "/billing/plans"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    t = data.get("trial") or {}
    errs: list[str] = []
    if int(t.get("agents") or 0) != EXPECT_AGENTS:
        errs.append(f"prod agents={t.get('agents')} want {EXPECT_AGENTS}")
    if int(t.get("companies") or 0) != EXPECT_COMPANIES:
        errs.append(f"prod companies={t.get('companies')} want {EXPECT_COMPANIES}")
    if int(t.get("projects") or 0) != EXPECT_PROJECTS:
        errs.append(f"prod projects={t.get('projects')} want {EXPECT_PROJECTS}")
    return {
        "ok": not errs,
        "errors": errs,
        "url": url,
        "trial": {
            "agents": t.get("agents"),
            "companies": t.get("companies"),
            "projects": t.get("projects"),
            "tokens_included": t.get("tokens_included"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--prod",
        action="store_true",
        help="Also GET production /api/billing/plans",
    )
    ap.add_argument(
        "--base",
        default="https://www.aibusinessagent.xyz/api",
        help="API base when using --prod",
    )
    args = ap.parse_args()

    report: dict = {"local": _check_local()}
    print("LOCAL:", "OK" if report["local"]["ok"] else "FAIL", report["local"]["trial"])
    if report["local"]["errors"]:
        for e in report["local"]["errors"]:
            print("  -", e)

    if args.prod:
        try:
            report["prod"] = _check_prod(args.base)
            print("PROD:", "OK" if report["prod"]["ok"] else "FAIL", report["prod"]["trial"])
            if report["prod"]["errors"]:
                for e in report["prod"]["errors"]:
                    print("  -", e)
        except Exception as exc:  # noqa: BLE001
            report["prod"] = {"ok": False, "errors": [str(exc)]}
            print("PROD: FAIL", exc)

    ok = report["local"]["ok"] and (not args.prod or report.get("prod", {}).get("ok"))
    out = ROOT / "scripts" / "assert_trial_plan_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
