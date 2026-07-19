"""GET/PUT skills and skills/run endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth_utils import get_current_user, ensure_credits
from .agents_common import _get_owned, SkillsUpdateIn, SkillRunIn

router = APIRouter()


@router.get("/{agent_id}/skills")
def get_skills(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import (
        list_skills_for_agent,
        list_skills_grouped,
        SKILL_CATALOG,
        get_comprehensive_skill_catalog,
        enabled_skill_ids,
    )
    from ..agent_roles import normalize_role
    from ..plans import plan_skill_caps
    a = _get_owned(agent_id, user, db)
    skills = list_skills_for_agent(a, db)
    free = [s for s in skills if not s.get("premium")]
    premium = [s for s in skills if s.get("premium")]
    enabled = enabled_skill_ids(a, db)
    caps = plan_skill_caps(user.plan)
    return {
        "agent_id": a.id,
        "role": normalize_role(a),
        "skills": skills,
        "catalog": SKILL_CATALOG,
        "categories": list_skills_grouped(),
        "grouped": get_comprehensive_skill_catalog(),
        "enabled_count": len(enabled),
        "plan_caps": caps,
        "summary": {
            "total": len(skills),
            "unique_catalog": len(SKILL_CATALOG),
            "enabled": len(enabled),
            "enabled_cap": caps.get("skills_per_agent"),
            "skill_packs": caps.get("skill_packs"),
            "skill_packs_total": caps.get("skill_packs_total"),
            "free": len(free),
            "premium": len(premium),
            "premium_allowed": caps.get("premium_skills"),
            "premium_examples": [p["name"] for p in premium[:8]],
        },
    }


@router.put("/{agent_id}/skills")
def put_skills(agent_id: int, data: SkillsUpdateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import set_enabled_skills, list_skills_for_agent
    from ..plans import plan_skill_caps
    a = _get_owned(agent_id, user, db)
    requested = list(data.enabled or [])
    enabled = set_enabled_skills(db, a, requested)
    caps = plan_skill_caps(user.plan)
    capped = len(requested) > len(enabled)
    return {
        "agent_id": a.id,
        "enabled": enabled,
        "skills": list_skills_for_agent(a, db),
        "plan_caps": caps,
        "capped": capped,
        "message": (
            f"Enabled {len(enabled)} skills (plan cap {caps.get('skills_per_agent')})."
            if capped
            else f"Enabled {len(enabled)} skills."
        ),
    }


@router.post("/{agent_id}/skills/run")
async def run_skill(agent_id: int, data: SkillRunIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from ..agent_skills import execute_skill
    a = _get_owned(agent_id, user, db)
    ensure_credits(db, user.id)
    result = await execute_skill(db, a, user, data.skill, data.args or {})
    return result

