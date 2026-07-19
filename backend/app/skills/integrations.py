"""Connected-app wrappers and use_app / _run_app skill handlers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..agent_roles import is_orchestrator


async def _skill_use_app(db: Session, agent: models.Agent, user: models.User, args: dict) -> dict:
    from ..integration_actions import run_app_action

    # Accept common aliases: app, application, integration
    app_id = (
        args.get("app_id")
        or args.get("app")
        or args.get("application")
        or args.get("integration")
        or ""
    )
    app_id = str(app_id).strip().lower()
    action = (args.get("action") or args.get("operation") or "status").strip().lower()
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    if not app_id:
        return {
            "ok": False,
            "error": "app_id required (e.g. gmail, slack, shopify, hubspot — not a connection numeric id)",
        }
    # Numeric-only "app_id" is almost always a mistaken connection id
    if app_id.isdigit():
        return {
            "ok": False,
            "error": (
                f"app_id '{app_id}' looks like a connection id. "
                "Pass the app key string (gmail, slack, shopify, …)."
            ),
        }

    # Must be allocated to this agent
    links = db.query(models.AgentIntegration).filter_by(agent_id=agent.id).all()
    conn = None
    for link in links:
        c = db.get(models.IntegrationConnection, link.connection_id)
        if c and c.app_id == app_id and c.user_id == user.id:
            conn = c
            break
    if not conn:
        # Fall back to any connected app of that type for orchestrators
        if is_orchestrator(agent):
            conn = (
                db.query(models.IntegrationConnection)
                .filter_by(user_id=user.id, app_id=app_id, status="connected")
                .order_by(models.IntegrationConnection.id.desc())
                .first()
            )
    if not conn:
        # List available apps so the agent can recover
        connected = (
            db.query(models.IntegrationConnection)
            .filter_by(user_id=user.id, status="connected")
            .all()
        )
        available = sorted({(c.app_id or "") for c in connected if c.app_id})
        hint = f" Connected apps: {', '.join(available)}." if available else " No apps connected yet (Settings → Connected apps)."
        return {"ok": False, "error": f"No connected '{app_id}' app allocated to this agent.{hint}"}

    result = await run_app_action(conn, action, payload, app_id=app_id)
    return result

async def _run_app(db, agent, user, app_id: str, action: str, payload: dict) -> dict:
    from .. import models as _m
    from ..integration_actions import run_app_action
    app_id = (app_id or "").strip().lower()
    # Prefer exact app, then agent-linked, then Google hub token for gmail actions
    conn = (
        db.query(_m.IntegrationConnection)
        .filter_by(user_id=user.id, app_id=app_id, status="connected")
        .order_by(_m.IntegrationConnection.id.desc())
        .first()
    )
    if not conn:
        links = db.query(_m.AgentIntegration).filter_by(agent_id=agent.id).all()
        for link in links:
            c = db.get(_m.IntegrationConnection, link.connection_id)
            if c and c.user_id == user.id and c.status == "connected" and c.app_id == app_id:
                conn = c
                break
    if not conn and app_id == "gmail":
        conn = (
            db.query(_m.IntegrationConnection)
            .filter(
                _m.IntegrationConnection.user_id == user.id,
                _m.IntegrationConnection.status == "connected",
                _m.IntegrationConnection.app_id.in_(("gmail", "google")),
            )
            .order_by(_m.IntegrationConnection.id.desc())
            .first()
        )
    if not conn:
        return {
            "ok": False,
            "error": (
                f"No connected {app_id} app. "
                "Connect it under Settings → Connected apps (Gmail one-click OAuth)."
            ),
        }
    # Dispatch by requested skill app (not connection label) — never mutate conn.app_id
    result = await run_app_action(conn, action, payload or {}, app_id=app_id)
    if isinstance(result, dict) and result.get("token_refreshed"):
        try:
            db.commit()
        except Exception:
            db.rollback()
    return result

async def _skill_facebook_post(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "post", {
        "message": args.get("message") or args.get("text"),
        "link": args.get("link"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_reply_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "reply_comment", {
        "comment_id": args.get("comment_id"),
        "message": args.get("message"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_reply_message(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "reply_message", {
        "recipient_id": args.get("recipient_id"),
        "message": args.get("message"),
        "page_id": args.get("page_id"),
    })

async def _skill_facebook_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_comments", args)

async def _skill_facebook_get_posts(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_posts", args)

async def _skill_facebook_get_conversations(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "get_conversations", args)

async def _skill_facebook_like_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "facebook", "like_comment", args)

async def _skill_instagram_post(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "post", args)

async def _skill_instagram_reply_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "reply_comment", args)

async def _skill_instagram_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "get_comments", args)

async def _skill_instagram_get_media(db, agent, user, args):
    return await _run_app(db, agent, user, "instagram", "get_media", args)

async def _skill_linkedin_post(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "post", args)

async def _skill_linkedin_comment(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "comment", args)

async def _skill_linkedin_get_posts(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "get_posts", args)

async def _skill_linkedin_get_comments(db, agent, user, args):
    return await _run_app(db, agent, user, "linkedin", "get_comments", args)

async def _skill_x_post(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "post", args)

async def _skill_x_reply(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "reply", args)

async def _skill_x_get_mentions(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "get_mentions", args)

async def _skill_x_get_timeline(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "get_timeline", args)

async def _skill_x_search(db, agent, user, args):
    return await _run_app(db, agent, user, "x", "search", args)

async def _skill_gmail_send(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "send", {
        "to": args.get("to") or args.get("email"),
        "subject": args.get("subject"),
        "body": args.get("body") or args.get("text"),
        "cc": args.get("cc"),
        "bcc": args.get("bcc"),
        "html": args.get("html"),
        "thread_id": args.get("thread_id"),
    })

async def _skill_gmail_reply(db, agent, user, args):
    action = "reply_all" if str(args.get("reply_all") or "").lower() in ("1", "true", "yes") else "reply"
    return await _run_app(db, agent, user, "gmail", action, {
        "thread_id": args.get("thread_id"),
        "message_id": args.get("message_id"),
        "body": args.get("body") or args.get("text"),
        "to": args.get("to"),
        "cc": args.get("cc"),
        "bcc": args.get("bcc"),
        "html": args.get("html"),
        "subject": args.get("subject"),
    })

async def _skill_gmail_draft(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "draft", {
        "to": args.get("to"),
        "subject": args.get("subject"),
        "body": args.get("body") or args.get("text"),
        "cc": args.get("cc"),
        "bcc": args.get("bcc"),
        "html": args.get("html"),
        "thread_id": args.get("thread_id"),
    })

async def _skill_gmail_list(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "list", {
        "query": args.get("query") or args.get("q"),
        "label": args.get("label"),
        "limit": args.get("limit") or 10,
    })

async def _skill_gmail_get_thread(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "get_thread", {
        "thread_id": args.get("thread_id") or args.get("id"),
    })

async def _skill_gmail_search(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "search", {
        "query": args.get("query") or args.get("q"),
        "limit": args.get("limit") or 10,
    })

async def _skill_gmail_archive(db, agent, user, args):
    return await _run_app(db, agent, user, "gmail", "archive", {
        "message_id": args.get("message_id"),
        "thread_id": args.get("thread_id"),
    })

async def _skill_email_reply(db, agent, user, args):
    from .comms import _skill_send_email
    # Convenience: send email + log to CRM customer
    res = await _skill_send_email(db, agent, user, args)
    cid = args.get("customer_id")
    if cid and res.get("ok"):
        try:
            from .. import models as _m
            c = db.get(_m.Customer, int(cid))
            if c:
                db.add(_m.CustomerActivity(
                    customer_id=c.id, owner_user_id=user.id,
                    kind="email", title=args.get("subject") or "Reply",
                    body=(args.get("body") or "")[:500], agent_id=agent.id
                ))
                db.commit()
        except Exception:
            pass
    return res

async def _skill_slack_post(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "post", args)

async def _skill_slack_reply_thread(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "reply_thread", args)

async def _skill_slack_dm(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "dm", args)

async def _skill_slack_list_channels(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "list_channels", args)

async def _skill_slack_get_messages(db, agent, user, args):
    return await _run_app(db, agent, user, "slack", "get_messages", args)

async def _skill_calendar_create_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "create_event", args)

async def _skill_calendar_list_events(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "list_events", args)

async def _skill_calendar_update_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "update_event", args)

async def _skill_calendar_delete_event(db, agent, user, args):
    return await _run_app(db, agent, user, "google", "delete_event", args)

async def _skill_sheets_append(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "append", args)

async def _skill_sheets_read(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "read", args)

async def _skill_sheets_update(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "update", args)

async def _skill_sheets_create_sheet(db, agent, user, args):
    return await _run_app(db, agent, user, "google_sheets", "create_sheet", args)

async def _skill_shopify_action(db, agent, user, subaction, args):
    p = {**args, "action": subaction}
    return await _run_app(db, agent, user, "shopify", subaction, p)

async def _skill_shopify_sync(db, agent, user, args):
    from ..shopify_sync import sync_all_shopify, sync_shopify_products, sync_shopify_customers

    what = (args.get("what") or "all").lower().strip()
    company_id = args.get("company_id") or getattr(agent, "company_id", None)
    limit = int(args.get("limit") or 50)
    if what == "products":
        return await sync_shopify_products(db, user, company_id=company_id, limit=limit)
    if what == "customers":
        return await sync_shopify_customers(db, user, company_id=company_id, limit=limit)
    return await sync_all_shopify(db, user, company_id=company_id, limit=limit)

async def _skill_shopify_push_product(db, agent, user, args):
    from ..shopify_sync import push_product_tags_to_shopify

    pid = args.get("product_id") or args.get("id")
    if not pid:
        return {"ok": False, "error": "product_id required (local Business product id)"}
    return await push_product_tags_to_shopify(db, user, int(pid))

async def _skill_shopify_push_customer(db, agent, user, args):
    from ..shopify_sync import push_customer_tags_to_shopify

    cid = args.get("customer_id") or args.get("id")
    if not cid:
        return {"ok": False, "error": "customer_id required (local Business customer id)"}
    return await push_customer_tags_to_shopify(db, user, int(cid))

async def _skill_hubspot_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "hubspot", subaction, args)

async def _skill_notion_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "notion", subaction, args)

async def _skill_discord_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "discord", subaction, args)

async def _skill_whatsapp_reply(db, agent, user, args):
    from .comms import _skill_send_whatsapp
    return await _skill_send_whatsapp(db, agent, user, args)

async def _skill_mailchimp_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "mailchimp", subaction, args)

async def _skill_dropbox_action(db, agent, user, subaction, args):
    return await _run_app(db, agent, user, "dropbox", subaction, args)


__all__ = [
    '_skill_use_app',
    '_run_app',
    '_skill_facebook_post',
    '_skill_facebook_reply_comment',
    '_skill_facebook_reply_message',
    '_skill_facebook_get_comments',
    '_skill_facebook_get_posts',
    '_skill_facebook_get_conversations',
    '_skill_facebook_like_comment',
    '_skill_instagram_post',
    '_skill_instagram_reply_comment',
    '_skill_instagram_get_comments',
    '_skill_instagram_get_media',
    '_skill_linkedin_post',
    '_skill_linkedin_comment',
    '_skill_linkedin_get_posts',
    '_skill_linkedin_get_comments',
    '_skill_x_post',
    '_skill_x_reply',
    '_skill_x_get_mentions',
    '_skill_x_get_timeline',
    '_skill_x_search',
    '_skill_gmail_send',
    '_skill_gmail_reply',
    '_skill_gmail_draft',
    '_skill_gmail_list',
    '_skill_gmail_get_thread',
    '_skill_gmail_search',
    '_skill_gmail_archive',
    '_skill_email_reply',
    '_skill_slack_post',
    '_skill_slack_reply_thread',
    '_skill_slack_dm',
    '_skill_slack_list_channels',
    '_skill_slack_get_messages',
    '_skill_calendar_create_event',
    '_skill_calendar_list_events',
    '_skill_calendar_update_event',
    '_skill_calendar_delete_event',
    '_skill_sheets_append',
    '_skill_sheets_read',
    '_skill_sheets_update',
    '_skill_sheets_create_sheet',
    '_skill_shopify_action',
    '_skill_shopify_sync',
    '_skill_shopify_push_product',
    '_skill_shopify_push_customer',
    '_skill_hubspot_action',
    '_skill_notion_action',
    '_skill_discord_action',
    '_skill_whatsapp_reply',
    '_skill_mailchimp_action',
    '_skill_dropbox_action',
]
