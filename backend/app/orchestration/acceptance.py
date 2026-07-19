"""Structured acceptance / checklist for tasks — single source of truth."""
from __future__ import annotations

import json
import re
from typing import Any

from .. import models
from ..patterns import normalize_checklist, format_checklist_block

# Marker embedded in task description so acceptance survives without always needing a column
_ACCEPTANCE_START = "<!--ACCEPTANCE_JSON:"
_ACCEPTANCE_END = "-->"

# Labels that mean a lead must approve before chain continues
_REVIEW_LABELS = frozenset({
    "needs-review", "lead-assigned", "has-checklist", "lead-workflow", "requires-review",
})

# Checklist text → skill ids that prove the check (active evidence)
_CHECK_SKILL_HINTS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    (re.compile(r"create_customer|crm|customer", re.I), frozenset({"create_customer", "update_customer"})),
    (re.compile(r"create_deal|deal|pipeline", re.I), frozenset({"create_deal", "move_deal", "update_deal", "pipeline_summary"})),
    (re.compile(r"email|send_email|outreach", re.I), frozenset({"send_email", "draft_email", "email_send"})),
    (re.compile(r"sms|send_sms", re.I), frozenset({"send_sms", "draft_sms"})),
    (re.compile(r"call|phone", re.I), frozenset({"make_voice_call", "initiate_call", "log_communication", "log_customer_activity"})),
    (re.compile(r"task|complete", re.I), frozenset({"create_task", "complete_task", "update_task"})),
    (re.compile(r"memory|save_memory", re.I), frozenset({"save_memory"})),
    (re.compile(r"notify|status_update|human", re.I), frozenset({"status_update", "notify_human"})),
    (re.compile(r"product", re.I), frozenset({"create_product", "update_product"})),
]


def merge_labels(*parts: str | None, extra: list[str] | None = None) -> str:
    seen: list[str] = []
    for p in parts:
        for tag in (p or "").split(","):
            t = tag.strip()
            if t and t not in seen:
                seen.append(t)
    for t in extra or []:
        t = (t or "").strip()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def pack_acceptance(
    *,
    done_when: str = "",
    checklist: list[str] | None = None,
    require_review: bool = False,
) -> str:
    """JSON blob for description embed / acceptance_json column."""
    return json.dumps({
        "done_when": (done_when or "")[:500],
        "checklist": normalize_checklist(checklist),
        "require_review": bool(require_review),
        "checks": [
            {"id": f"c{i}", "label": c, "status": "pending"}
            for i, c in enumerate(normalize_checklist(checklist))
        ],
    }, ensure_ascii=False)


def unpack_acceptance(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"done_when": "", "checklist": [], "require_review": False, "checks": []}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"done_when": "", "checklist": [], "require_review": False, "checks": []}
        checks = data.get("checks") or []
        if not checks and data.get("checklist"):
            checks = [
                {"id": f"c{i}", "label": c, "status": "pending"}
                for i, c in enumerate(normalize_checklist(data.get("checklist")))
            ]
        return {
            "done_when": str(data.get("done_when") or "")[:500],
            "checklist": normalize_checklist(data.get("checklist") or [c.get("label") for c in checks if isinstance(c, dict)]),
            "require_review": bool(data.get("require_review")),
            "checks": checks if isinstance(checks, list) else [],
        }
    except Exception:
        return {"done_when": "", "checklist": [], "require_review": False, "checks": []}


def embed_acceptance(description: str, acceptance: dict[str, Any] | str) -> str:
    """Append machine-readable acceptance + human checklist to description."""
    if isinstance(acceptance, str):
        blob = acceptance
        data = unpack_acceptance(acceptance)
    else:
        blob = json.dumps(acceptance, ensure_ascii=False)
        data = acceptance
    body = (description or "").strip()
    # Strip old embed
    if _ACCEPTANCE_START in body:
        body = body.split(_ACCEPTANCE_START)[0].rstrip()
    checks = normalize_checklist(data.get("checklist") or [])
    parts = [body]
    if checks:
        parts.append(format_checklist_block(checks))
    parts.append(f"{_ACCEPTANCE_START}{blob}{_ACCEPTANCE_END}")
    return "\n".join(parts)[:8000]


def extract_acceptance_blob(description: str | None) -> dict[str, Any]:
    text = description or ""
    if _ACCEPTANCE_START not in text:
        # Fall back to parsing prose checklist lines
        checks = []
        for line in text.splitlines():
            m = re.match(r"^\s*(?:[-*•]|\[[ xX]?\])\s*(.+)$", line)
            if m and "CHECKLIST" not in line.upper():
                # only after CHECKLIST header ideally — loose parse
                pass
        # DONE WHEN / [ ] lines
        for line in text.splitlines():
            m = re.match(r"^\s*\[\s*\]\s*(.+)$", line)
            if m:
                checks.append(m.group(1).strip())
        done = ""
        for line in text.splitlines():
            if line.strip().upper().startswith("DONE WHEN:"):
                done = line.split(":", 1)[-1].strip()
                break
        return {
            "done_when": done,
            "checklist": checks,
            "require_review": bool(checks) or "needs-review" in text.lower(),
            "checks": [{"id": f"c{i}", "label": c, "status": "pending"} for i, c in enumerate(checks)],
        }
    try:
        mid = text.split(_ACCEPTANCE_START, 1)[1]
        raw = mid.split(_ACCEPTANCE_END, 1)[0]
        return unpack_acceptance(raw)
    except Exception:
        return unpack_acceptance(None)


def extract_checklist(task: models.Task) -> list[str]:
    """Checklist labels for a task (column or description)."""
    raw = getattr(task, "acceptance_json", None) or ""
    if raw and str(raw).strip() not in ("", "{}"):
        return unpack_acceptance(raw).get("checklist") or []
    return extract_acceptance_blob(task.description).get("checklist") or []


def task_requires_review(task: models.Task, *, agent: models.Agent | None = None) -> bool:
    """True when lead must approve before completed/chain unlock."""
    labs = {t.strip() for t in (task.labels or "").split(",") if t.strip()}
    if labs & _REVIEW_LABELS:
        return True
    acc = None
    raw = getattr(task, "acceptance_json", None) or ""
    if raw and str(raw).strip() not in ("", "{}"):
        acc = unpack_acceptance(raw)
    else:
        acc = extract_acceptance_blob(task.description)
    if acc.get("require_review"):
        return True
    if acc.get("checklist"):
        return True
    return False


def evaluate_skill_evidence(
    task: models.Task,
    skill_results: list[dict] | None,
) -> dict[str, Any]:
    """
    Active check: map checklist items to skill outcomes.
    Returns verdict pass | review | fail, plus per-check statuses.
    """
    checks = extract_checklist(task)
    results = skill_results or []
    ok_skills = {
        str(r.get("skill") or "").lower()
        for r in results
        if r.get("ok")
    }
    fail_skills = {
        str(r.get("skill") or "").lower()
        for r in results
        if r.get("ok") is False
    }
    any_ok = bool(ok_skills)
    any_fail = bool(fail_skills)

    check_rows: list[dict[str, Any]] = []
    failed_labels: list[str] = []
    pending_labels: list[str] = []

    for i, label in enumerate(checks):
        status = "pending"
        matched_skills: list[str] = []
        for pat, skills in _CHECK_SKILL_HINTS:
            if pat.search(label):
                matched_skills = list(skills)
                if skills & ok_skills:
                    status = "pass"
                elif skills & fail_skills:
                    status = "fail"
                break
        if status == "pending" and any_ok and not matched_skills:
            # Generic check with some successful skills — leave for lead review
            status = "pending"
        check_rows.append({
            "id": f"c{i}",
            "label": label,
            "status": status,
            "skills": matched_skills,
        })
        if status == "fail":
            failed_labels.append(label)
        elif status == "pending":
            pending_labels.append(label)

    requires = task_requires_review(task)

    if failed_labels:
        verdict = "fail"
    elif checks and pending_labels and requires:
        verdict = "review"
    elif checks and not pending_labels and not failed_labels:
        # All mapped checks passed
        verdict = "pass" if not requires else "review"
    elif requires:
        verdict = "review"
    elif any_fail and not any_ok:
        verdict = "fail"
    else:
        verdict = "pass"

    return {
        "verdict": verdict,
        "checks": check_rows,
        "failed": failed_labels,
        "pending": pending_labels,
        "skills_ok": sorted(ok_skills),
        "skills_fail": sorted(fail_skills),
    }
