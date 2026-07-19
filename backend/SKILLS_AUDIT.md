# Skills audit

- Catalog entries: **1282**
- Unique IDs: **1282**
- Duplicate IDs: **none**
- Premium (wallet): **31**
- HANDLER_TABLE entries: **146**
- `_skill_*` functions (handlers_all): **129**
- Table-wired catalog skills: **146**
- Default deliverable path: **1136** via `_skill_catalog_deliverable`
- Default handler present: **True**
- Custom skill handler present: **True**
- Truly unwired (no table + no default): **0**
- Broken table entries (missing fn): **0**

## Architecture

1. `HANDLER_TABLE` maps skill_id → implementation for side-effect skills.
2. Catalog skills without a table entry run `_skill_catalog_deliverable` (LLM brief).
3. Workspace-created skills use `_skill_run_created`.

## Duplicates

_none_

## Broken HANDLER_TABLE entries

_none_

## Premium skills

- `calendar_create_event` — Create calendar event — $0.02 — meter `premium-comm`
- `discord_dm_user` — DM Discord user — $0.015 — meter `premium-comm`
- `discord_post` — Post to Discord — $0.01 — meter `premium-comm`
- `email_reply` — Reply by email — $0.02 — meter `premium-comm`
- `email_send` — Send email (any) — $0.02 — meter `premium-comm`
- `facebook_post` — Facebook post — $0.02 — meter `premium-comm`
- `facebook_reply_comment` — Reply to Facebook comment — $0.015 — meter `premium-comm`
- `facebook_reply_message` — Reply to Facebook message / DM — $0.02 — meter `premium-comm`
- `generate_image` — Generate image (premium) — $0.06 — meter `image`
- `generate_video` — Generate video (premium) — $0.25 — meter `video`
- `gmail_reply` — Gmail reply — $0.015 — meter `premium-comm`
- `gmail_send` — Gmail send — $0.02 — meter `premium-comm`
- `initiate_call` — Initiate phone call — $0.08 — meter `voice_call`
- `initiate_text` — Initiate text / SMS — $0.015 — meter `premium-comm`
- `instagram_post` — Instagram post — $0.04 — meter `premium-comm`
- `instagram_reply_comment` — Reply to Instagram comment — $0.015 — meter `premium-comm`
- `linkedin_comment` — Comment on LinkedIn post — $0.015 — meter `premium-comm`
- `linkedin_post` — LinkedIn post (live) — $0.025 — meter `premium-comm`
- `make_voice_call` — Make phone call + speech (Twilio) — $0.08 — meter `voice_call`
- `send_email` — Send email (premium) — $0.02 — meter `premium-comm`
- `send_message` — Send message (any channel) — $0.02 — meter `premium-comm`
- `send_sms` — Send SMS / text (Twilio) — $0.015 — meter `premium-comm`
- `send_whatsapp` — Send WhatsApp (Twilio) — $0.02 — meter `premium-comm`
- `sheets_append` — Append to Google Sheet — $0.01 — meter `premium-comm`
- `slack_dm` — Send Slack DM — $0.015 — meter `premium-comm`
- `slack_post` — Post to Slack — $0.01 — meter `premium-comm`
- `slack_reply_thread` — Reply in Slack thread — $0.01 — meter `premium-comm`
- `whatsapp_reply` — Reply on WhatsApp — $0.02 — meter `premium-comm`
- `whatsapp_send` — Send WhatsApp message — $0.02 — meter `premium-comm`
- `x_post` — Post on X (Twitter) — $0.02 — meter `premium-comm`
- `x_reply` — Reply on X — $0.015 — meter `premium-comm`

## HANDLER_TABLE (dedicated side-effect skills)

| ID | Handler | Mode |
|----|---------|------|
| `announce_plan` | `_skill_announce_plan` | std |
| `assign_human` | `_skill_assign_human` | std |
| `bulk_enable_skills` | `_skill_bulk_enable_skills` | std |
| `calendar_create_event` | `_skill_calendar_create_event` | std |
| `calendar_delete_event` | `_skill_calendar_delete_event` | std |
| `calendar_list_events` | `_skill_calendar_list_events` | std |
| `calendar_update_event` | `_skill_calendar_update_event` | std |
| `clone_agent` | `_skill_clone_agent` | std |
| `close_meeting` | `_skill_close_meeting` | std |
| `comment` | `_skill_comment` | std |
| `configure_agent` | `_skill_configure_agent` | std |
| `create_deal` | `_skill_create_deal` | std |
| `create_invoice_draft` | `_skill_create_invoice_draft` | std |
| `create_reminder` | `_skill_create_reminder` | std |
| `create_skill` | `_skill_create_skill` | std |
| `create_task` | `_skill_create_task` | std |
| `delete_agent` | `_skill_delete_agent` | std |
| `discord_dm_user` | `_skill_discord_action` | extra ('dm_user',) |
| `discord_post` | `_skill_discord_action` | extra ('post',) |
| `draft_email` | `_skill_draft_email` | std |
| `draft_sms` | `_skill_draft_sms` | std |
| `dropbox_list` | `_skill_dropbox_action` | extra ('list',) |
| `dropbox_upload` | `_skill_dropbox_action` | extra ('upload',) |
| `email_reply` | `_skill_email_reply` | std |
| `email_send` | `_skill_send_email` | std |
| `enable_skills_on` | `_skill_enable_skills_on` | std |
| `ensure_sales_pipeline` | `_skill_ensure_sales_pipeline` | std |
| `escalate_to_human` | `_skill_escalate_to_human` | std |
| `execute_goal` | `_skill_execute_goal` | std |
| `extract_meeting_tasks` | `_skill_extract_meeting_tasks` | std |
| `facebook_get_comments` | `_skill_facebook_get_comments` | std |
| `facebook_get_conversations` | `_skill_facebook_get_conversations` | std |
| `facebook_get_posts` | `_skill_facebook_get_posts` | std |
| `facebook_like_comment` | `_skill_facebook_like_comment` | std |
| `facebook_post` | `_skill_facebook_post` | std |
| `facebook_reply_comment` | `_skill_facebook_reply_comment` | std |
| `facebook_reply_message` | `_skill_facebook_reply_message` | std |
| `generate_content` | `_skill_generate_content` | std |
| `generate_image` | `_skill_generate_image` | std |
| `generate_video` | `_skill_generate_video` | std |
| `get_customer` | `_skill_get_customer` | std |
| `get_pipeline` | `_skill_get_pipeline` | std |
| `get_task` | `_skill_get_task` | std |
| `get_time` | `_skill_get_time` | std |
| `gmail_archive` | `_skill_gmail_archive` | std |
| `gmail_draft` | `_skill_gmail_draft` | std |
| `gmail_get_thread` | `_skill_gmail_get_thread` | std |
| `gmail_list` | `_skill_gmail_list` | std |
| `gmail_reply` | `_skill_gmail_reply` | std |
| `gmail_search` | `_skill_gmail_search` | std |
| `gmail_send` | `_skill_gmail_send` | std |
| `hubspot_create_contact` | `_skill_hubspot_action` | extra ('create_contact',) |
| `hubspot_create_deal` | `_skill_hubspot_action` | extra ('create_deal',) |
| `hubspot_get_contacts` | `_skill_hubspot_action` | extra ('get_contacts',) |
| `hubspot_log_note` | `_skill_hubspot_action` | extra ('log_note',) |
| `initiate_call` | `_skill_make_voice_call` | std |
| `initiate_text` | `_skill_send_sms` | std |
| `instagram_get_comments` | `_skill_instagram_get_comments` | std |
| `instagram_get_media` | `_skill_instagram_get_media` | std |
| `instagram_post` | `_skill_instagram_post` | std |
| `instagram_reply_comment` | `_skill_instagram_reply_comment` | std |
| `linkedin_comment` | `_skill_linkedin_comment` | std |
| `linkedin_get_comments` | `_skill_linkedin_get_comments` | std |
| `linkedin_get_posts` | `_skill_linkedin_get_posts` | std |
| `linkedin_post` | `_skill_linkedin_post` | std |
| `list_created_skills` | `_skill_list_created_skills` | std |
| `list_customers` | `_skill_list_customers` | std |
| `list_deals` | `_skill_list_deals` | std |
| `list_diary` | `_skill_list_diary` | std |
| `list_humans` | `_skill_list_humans` | std |
| `list_meetings` | `_skill_list_meetings` | std |
| `list_pipeline_stages` | `_skill_list_pipeline_stages` | std |
| `list_pipelines` | `_skill_list_pipelines` | std |
| `list_tasks` | `_skill_list_tasks` | std |
| `list_team` | `_skill_list_team` | std |
| `log_communication` | `_skill_log_communication` | std |
| `log_customer_activity` | `_skill_log_customer_activity` | std |
| `lose_deal` | `_skill_lose_deal` | std |
| `mailchimp_add_subscriber` | `_skill_mailchimp_action` | extra ('add_subscriber',) |
| `mailchimp_create_campaign` | `_skill_mailchimp_action` | extra ('create_campaign',) |
| `make_voice_call` | `_skill_make_voice_call` | std |
| `message_agent` | `_skill_message` | std |
| `move_deal` | `_skill_move_deal` | std |
| `notify_human` | `_skill_notify_human` | std |
| `notion_append_block` | `_skill_notion_action` | extra ('append_block',) |
| `notion_create_page` | `_skill_notion_action` | extra ('create_page',) |
| `notion_query_database` | `_skill_notion_action` | extra ('query_database',) |
| `notion_update_page` | `_skill_notion_action` | extra ('update_page',) |
| `open_meeting` | `_skill_open_meeting` | std |
| `pause_agent` | `_skill_pause_agent` | std |
| `pipeline_summary` | `_skill_pipeline_summary` | std |
| `post_to_meeting` | `_skill_post_to_meeting` | std |
| `promote_to_lead` | `_skill_promote_to_lead` | std |
| `publish_skill_to_bay` | `_skill_publish_skill_to_bay` | std |
| `read_workspace` | `_skill_read_workspace` | std |
| `research` | `_skill_research` | std |
| `resume_agent` | `_skill_resume_agent` | std |
| `run_meeting_round` | `_skill_run_meeting_round` | std |
| `save_memory` | `_skill_save_memory` | std |
| `save_training` | `_skill_save_training` | std |
| `schedule_meeting` | `_skill_schedule_meeting` | std |
| `search_knowledge` | `_skill_search_knowledge` | std |
| `search_memory` | `_skill_search_memory` | std |
| `send_email` | `_skill_send_email` | std |
| `send_message` | `_skill_send_message` | std |
| `send_sms` | `_skill_send_sms` | std |
| `send_whatsapp` | `_skill_send_whatsapp` | std |
| `set_agent_status` | `_skill_set_agent_status` | std |
| `share_skill` | `_skill_share_skill` | std |
| `sheets_append` | `_skill_sheets_append` | std |
| `sheets_create_sheet` | `_skill_sheets_create_sheet` | std |
| `sheets_read` | `_skill_sheets_read` | std |
| `sheets_update` | `_skill_sheets_update` | std |
| `shopify_create_order_note` | `_skill_shopify_action` | extra ('create_order_note',) |
| `shopify_fulfill_order` | `_skill_shopify_action` | extra ('fulfill_order',) |
| `shopify_get_customers` | `_skill_shopify_action` | extra ('get_customers',) |
| `shopify_get_orders` | `_skill_shopify_action` | extra ('get_orders',) |
| `shopify_get_products` | `_skill_shopify_action` | extra ('get_products',) |
| `shopify_push_customer_tags` | `_skill_shopify_push_customer` | std |
| `shopify_push_product_tags` | `_skill_shopify_push_product` | std |
| `shopify_sync_catalog` | `_skill_shopify_sync` | std |
| `shopify_update_customer` | `_skill_shopify_action` | extra ('update_customer',) |
| `shopify_update_product` | `_skill_shopify_action` | extra ('update_product',) |
| `slack_dm` | `_skill_slack_dm` | std |
| `slack_get_messages` | `_skill_slack_get_messages` | std |
| `slack_list_channels` | `_skill_slack_list_channels` | std |
| `slack_post` | `_skill_slack_post` | std |
| `slack_reply_thread` | `_skill_slack_reply_thread` | std |
| `spawn_agent` | `_skill_spawn` | std |
| `spawn_specialist` | `_skill_spawn_specialist` | std |
| `spawn_team` | `_skill_spawn_team` | std |
| `status_update` | `_skill_status_update` | std |
| `suggest_times` | `_skill_suggest_times` | std |
| `summarize` | `_skill_summarize` | std |
| `unpublish_skill_from_bay` | `_skill_unpublish_skill_from_bay` | std |
| `update_customer` | `_skill_update_customer` | std |
| `update_pipeline` | `_skill_update_pipeline` | std |
| `use_app` | `_skill_use_app` | std |
| `whatsapp_reply` | `_skill_whatsapp_reply` | std |
| `whatsapp_send` | `_skill_send_whatsapp` | std |
| `win_deal` | `_skill_win_deal` | std |
| `x_get_mentions` | `_skill_x_get_mentions` | std |
| `x_get_timeline` | `_skill_x_get_timeline` | std |
| `x_post` | `_skill_x_post` | std |
| `x_reply` | `_skill_x_reply` | std |
| `x_search` | `_skill_x_search` | std |

## Sample catalog-default skills (first 40)

- `qualify_lead`
- `write_proposal`
- `objection_handler`
- `follow_up_sequence`
- `cold_outreach`
- `book_meeting`
- `triage_ticket`
- `refund_or_credit`
- `knowledge_answer`
- `escalation_reason`
- `onboarding_flow`
- `linkedin_write_post`
- `twitter_thread`
- `ad_copy`
- `email_newsletter`
- `video_script`
- `seo_article`
- `case_study`
- `write_api_endpoint`
- `write_tests`
- `refactor_code`
- `debug_error`
- `database_migration`
- `docker_setup`
- `ci_pipeline`
- `code_review`
- `build_dashboard_query`
- `generate_report`
- `analyze_metrics`
- `forecast`
- `chase_payment`
- `expense_categorize`
- `monthly_summary`
- `write_job_description`
- `interview_questions`
- `onboarding_plan`
- `performance_review`
- `draft_contract_clause`
- `gdpr_request`
- `risk_assessment`
- … and 1096 more
