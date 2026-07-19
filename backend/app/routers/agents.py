"""Agents HTTP API — combined router assembled from focused submodules.

Public API: ``from app.routers import agents; agents.router``
(same paths and schemas as the previous monolithic module).
"""
from fastapi import APIRouter

from .agents_common import (  # noqa: F401 — re-exports for org.py and tests
    _get_owned,
    _run_task,
    log_activity,
    mode_for_template,
    AgentIn,
    AgentUpdate,
    HierarchyIn,
    DelegateIn,
    TaskIn,
    TaskStatusIn,
    AgentChatIn,
    AgentMsgIn,
    MemoryIn,
    SkillsUpdateIn,
    SkillRunIn,
    SpawnIn,
    _agent_plan_cap,
    _require_agent_slot,
    _would_cycle,
    _team_context,
    _apply_hierarchy,
)
from . import agents_hierarchy
from . import agents_spawn
from . import agents_skills_http
from . import agents_crud
from . import agents_tasks
from . import agents_chat

router = APIRouter(prefix="/agents", tags=["agents"])

# Order: static/named collections first, then parameterized agent routes.
router.include_router(agents_hierarchy.router)
router.include_router(agents_spawn.router)
router.include_router(agents_tasks.router)
router.include_router(agents_skills_http.router)
router.include_router(agents_crud.router)
router.include_router(agents_chat.router)
