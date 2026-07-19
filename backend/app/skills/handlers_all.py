"""Thin re-export of all _skill_* handlers from domain modules.

agent_skills._load_skill_handlers_into_globals imports this package module and
copies every name starting with _skill_ / _parse_ / _meeting_ into its globals.
Domain modules declare __all__ so underscore names are re-exported via import *.
"""
from __future__ import annotations

from .crm import *  # noqa: F403
from .meetings import *  # noqa: F403
from .comms import *  # noqa: F403
from .content import *  # noqa: F403
from .workspace import *  # noqa: F403
from .meta_agents import *  # noqa: F403
from .meta_skills import *  # noqa: F403
from .integrations import *  # noqa: F403
