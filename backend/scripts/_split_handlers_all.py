"""One-shot: split skills/handlers_all.py into domain modules (behavior-preserving)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "skills" / "handlers_all.py"
OUT = ROOT / "app" / "skills"

# Domain -> ordered list of top-level function names
DOMAINS: dict[str, list[str]] = {
    "crm": [
        "_skill_list_customers",
        "_skill_get_customer",
        "_skill_update_customer",
        "_skill_log_customer_activity",
        "_skill_create_deal",
        "_parse_dt_safe",
        "_skill_schedule_meeting",
        "_skill_list_diary",
        "_skill_update_pipeline",
        "_skill_list_pipelines",
        "_skill_get_pipeline",
        "_skill_list_pipeline_stages",
        "_skill_move_deal",
        "_skill_win_deal",
        "_skill_lose_deal",
        "_skill_pipeline_summary",
        "_skill_ensure_sales_pipeline",
        "_skill_list_deals",
    ],
    "meetings": [
        "_parse_meeting_id",
        "_parse_id_list",
        "_meeting_room",
        "_skill_open_meeting",
        "_skill_post_to_meeting",
        "_skill_run_meeting_round",
        "_skill_close_meeting",
        "_skill_extract_meeting_tasks",
        "_skill_list_meetings",
    ],
    "comms": [
        "_skill_draft_email",
        "_skill_send_email",
        "_skill_draft_sms",
        "_skill_send_sms",
        "_skill_send_whatsapp",
        "_skill_make_voice_call",
        "_skill_log_communication",
        "_skill_send_message",
    ],
    "content": [
        "_skill_generate_image",
        "_skill_generate_video",
        "_skill_generate_content",
        "_skill_research",
        "_skill_summarize",
        "_skill_get_time",
        "_skill_suggest_times",
        "_skill_create_invoice_draft",
    ],
    "workspace": [
        "_skill_search_memory",
        "_skill_search_knowledge",
        "_skill_list_tasks",
        "_skill_get_task",
        "_skill_list_humans",
        "_skill_read_workspace",
        "_skill_comment",
    ],
    # Agent lifecycle / team ops (skill-factory split out to stay under ~1200)
    "meta_agents": [
        "_skill_spawn",
        "_skill_message",
        "_skill_assign_human",
        "_skill_save_memory",
        "_skill_save_training",
        "_skill_execute_goal",
        "_skill_create_task",
        "_skill_announce_plan",
        "_skill_notify_human",
        "_skill_status_update",
        "_skill_escalate_to_human",
        "_skill_set_agent_status",
        "_skill_create_reminder",
        "_skill_spawn_team",
        "_apply_preset_skills",
        "_skill_spawn_specialist",
        "_skill_clone_agent",
        "_skill_enable_skills_on",
        "_skill_bulk_enable_skills",
        "_skill_configure_agent",
        "_skill_promote_to_lead",
        "_skill_pause_agent",
        "_skill_resume_agent",
        "_skill_delete_agent",
        "_skill_list_team",
    ],
    "meta_skills": [
        "_skill_catalog_deliverable",
        "_slug_skill_key",
        "_skill_create_skill",
        "_skill_list_created_skills",
        "_resolve_created_skill",
        "_skill_publish_skill_to_bay",
        "_skill_unpublish_skill_from_bay",
        "_skill_share_skill",
        "_skill_run_created",
    ],
    "integrations": [
        "_skill_use_app",
        "_run_app",
        "_skill_facebook_post",
        "_skill_facebook_reply_comment",
        "_skill_facebook_reply_message",
        "_skill_facebook_get_comments",
        "_skill_facebook_get_posts",
        "_skill_facebook_get_conversations",
        "_skill_facebook_like_comment",
        "_skill_instagram_post",
        "_skill_instagram_reply_comment",
        "_skill_instagram_get_comments",
        "_skill_instagram_get_media",
        "_skill_linkedin_post",
        "_skill_linkedin_comment",
        "_skill_linkedin_get_posts",
        "_skill_linkedin_get_comments",
        "_skill_x_post",
        "_skill_x_reply",
        "_skill_x_get_mentions",
        "_skill_x_get_timeline",
        "_skill_x_search",
        "_skill_gmail_send",
        "_skill_gmail_reply",
        "_skill_gmail_draft",
        "_skill_gmail_list",
        "_skill_gmail_get_thread",
        "_skill_gmail_search",
        "_skill_gmail_archive",
        "_skill_email_reply",
        "_skill_slack_post",
        "_skill_slack_reply_thread",
        "_skill_slack_dm",
        "_skill_slack_list_channels",
        "_skill_slack_get_messages",
        "_skill_calendar_create_event",
        "_skill_calendar_list_events",
        "_skill_calendar_update_event",
        "_skill_calendar_delete_event",
        "_skill_sheets_append",
        "_skill_sheets_read",
        "_skill_sheets_update",
        "_skill_sheets_create_sheet",
        "_skill_shopify_action",
        "_skill_shopify_sync",
        "_skill_shopify_push_product",
        "_skill_shopify_push_customer",
        "_skill_hubspot_action",
        "_skill_notion_action",
        "_skill_discord_action",
        "_skill_whatsapp_reply",
        "_skill_mailchimp_action",
        "_skill_dropbox_action",
    ],
}

HEADERS: dict[str, str] = {
    "crm": '''\
"""CRM / deal / pipeline / diary skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops


''',
    "meetings": '''\
"""Meeting room skill handlers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops


''',
    "comms": '''\
"""Email / SMS / WhatsApp / voice / unified messaging skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .. import channels
from ..live_ops import emit_ops
from .bridge import (
    get_skill_catalog,
    charge_premium,
)


''',
    "content": '''\
"""Content generation / research / time skill handlers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..live_ops import emit_ops
from .bridge import (
    get_skill_catalog,
    charge_premium,
)


''',
    "workspace": '''\
"""Workspace read / search / comment skill handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models


''',
    "meta_agents": '''\
"""Agent spawn / team / notify / task orchestration skill handlers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..agent_roles import is_orchestrator, normalize_role
from ..live_ops import emit_ops
from ..usage_billing import bill_llm_turn
from .bridge import (
    get_skill_catalog,
    get_enabled_skill_ids,
    set_enabled_skills,
    skills_for_template,
    skill_pack_for_template,
    skills_for_pack,
)


''',
    "meta_skills": '''\
"""Created-skill factory, AgentBay publish, and catalog deliverable handlers."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..usage_billing import bill_llm_turn
from .bridge import (
    get_enabled_skill_ids,
    set_enabled_skills,
)


''',
    "integrations": '''\
"""Connected-app wrappers and use_app / _run_app skill handlers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..agent_roles import is_orchestrator


''',
}

HANDLERS_ALL = '''\
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
'''


def _inject_lazy_import(body: str, func_name: str, import_line: str) -> str:
    """Insert a lazy import as the first statement of a function body (preserve logic)."""
    # Match def line(s) then insert after the first line that ends the signature
    # Functions may be single-line signature or multi-line.
    m = re.match(
        rf"(async\s+def\s+{re.escape(func_name)}\s*\(.*?\))\s*:\s*\n",
        body,
        flags=re.DOTALL,
    )
    if not m:
        # Try without requiring trailing newline after colon on same pattern
        m = re.match(
            rf"(async\s+def\s+{re.escape(func_name)}\b[\s\S]*?\)\s*->\s*[^:]+:\s*\n|"
            rf"async\s+def\s+{re.escape(func_name)}\b[\s\S]*?\)\s*:\s*\n|"
            rf"def\s+{re.escape(func_name)}\b[\s\S]*?\)\s*->\s*[^:]+:\s*\n|"
            rf"def\s+{re.escape(func_name)}\b[\s\S]*?\)\s*:\s*\n)",
            body,
        )
    if not m:
        raise RuntimeError(f"Could not find signature for {func_name} to inject import")
    head = body[: m.end()]
    rest = body[m.end() :]
    # Detect indent of first body line
    indent_m = re.match(r"([ \t]*)", rest)
    indent = indent_m.group(1) if indent_m else "    "
    injection = f"{indent}{import_line}\n"
    # Avoid double-inject
    if import_line in body:
        return body
    return head + injection + rest


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    # Allow re-run from backup if already split
    bak = OUT / "handlers_all.py.bak"
    if "Thin re-export" in src and bak.exists():
        print("handlers_all already split; restoring from .bak for re-split")
        src = bak.read_text(encoding="utf-8")

    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    by_name: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            end = node.end_lineno
            body = "".join(lines[start:end])
            if not body.endswith("\n"):
                body += "\n"
            by_name[node.name] = body

    all_assigned = [n for names in DOMAINS.values() for n in names]
    missing = [n for n in all_assigned if n not in by_name]
    extra = [n for n in by_name if n not in all_assigned]
    if missing:
        raise SystemExit(f"Missing from source: {missing}")
    if extra:
        raise SystemExit(f"Unassigned functions: {extra}")

    # Cross-module lazy imports (avoid circular imports; no logic change)
    by_name["_skill_send_email"] = _inject_lazy_import(
        by_name["_skill_send_email"],
        "_skill_send_email",
        "from .integrations import _run_app",
    )
    by_name["_skill_send_message"] = _inject_lazy_import(
        by_name["_skill_send_message"],
        "_skill_send_message",
        "from .integrations import _run_app",
    )
    by_name["_skill_email_reply"] = _inject_lazy_import(
        by_name["_skill_email_reply"],
        "_skill_email_reply",
        "from .comms import _skill_send_email",
    )
    by_name["_skill_whatsapp_reply"] = _inject_lazy_import(
        by_name["_skill_whatsapp_reply"],
        "_skill_whatsapp_reply",
        "from .comms import _skill_send_whatsapp",
    )

    if not bak.exists():
        bak.write_text(src if "Thin re-export" not in SRC.read_text(encoding="utf-8") else bak.read_text(encoding="utf-8") if bak.exists() else src, encoding="utf-8")
    # Always ensure backup of monolithic original exists
    if not bak.exists() or "Thin re-export" not in bak.read_text(encoding="utf-8")[:200]:
        # Write original monolithic content as backup when we still have it
        if "async def _skill_spawn" in src:
            bak.write_text(src, encoding="utf-8")
            print(f"Backed up original -> {bak}")

    counts: dict[str, int] = {}
    for domain, names in DOMAINS.items():
        parts = [HEADERS[domain]]
        for name in names:
            parts.append(by_name[name])
            if not by_name[name].endswith("\n\n"):
                parts.append("\n")
        # __all__ so import * re-exports underscore names
        all_list = ",\n    ".join(repr(n) for n in names)
        parts.append(f"\n__all__ = [\n    {all_list},\n]\n")
        text = "".join(parts)
        path = OUT / f"{domain}.py"
        path.write_text(text, encoding="utf-8")
        nlines = text.count("\n")
        counts[domain] = nlines
        print(f"Wrote {path.name}: {nlines} lines, {len(names)} symbols")

    (OUT / "handlers_all.py").write_text(HANDLERS_ALL, encoding="utf-8")
    hlines = HANDLERS_ALL.count("\n")
    counts["handlers_all"] = hlines
    print(f"Wrote handlers_all.py: {hlines} lines (re-export)")
    print("Domain line total:", sum(v for k, v in counts.items() if k != "handlers_all"))
    print("OK")


if __name__ == "__main__":
    main()
