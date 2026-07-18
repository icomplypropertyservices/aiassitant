# Skills audit

- Catalog entries: **248**
- Unique IDs: **248**
- Duplicate IDs: **none**
- Premium (wallet): **29**
- Mentioned in `execute_skill`: **111**
- `_skill_*` functions: **97**
- Likely unwired / draft-only: **137**

## Duplicates


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
- `instagram_post` — Instagram post — $0.04 — meter `premium-comm`
- `instagram_reply_comment` — Reply to Instagram comment — $0.015 — meter `premium-comm`
- `linkedin_comment` — Comment on LinkedIn post — $0.015 — meter `premium-comm`
- `linkedin_post` — LinkedIn post (live) — $0.025 — meter `premium-comm`
- `make_voice_call` — Make voice call (premium) — $0.08 — meter `voice_call`
- `send_email` — Send email (premium) — $0.02 — meter `premium-comm`
- `send_message` — Send message (any channel) — $0.02 — meter `premium-comm`
- `send_sms` — Send SMS (premium) — $0.015 — meter `premium-comm`
- `send_whatsapp` — Send WhatsApp (premium) — $0.02 — meter `premium-comm`
- `sheets_append` — Append to Google Sheet — $0.01 — meter `premium-comm`
- `slack_dm` — Send Slack DM — $0.015 — meter `premium-comm`
- `slack_post` — Post to Slack — $0.01 — meter `premium-comm`
- `slack_reply_thread` — Reply in Slack thread — $0.01 — meter `premium-comm`
- `whatsapp_reply` — Reply on WhatsApp — $0.02 — meter `premium-comm`
- `whatsapp_send` — Send WhatsApp message — $0.02 — meter `premium-comm`
- `x_post` — Post on X (Twitter) — $0.02 — meter `premium-comm`
- `x_reply` — Reply on X — $0.015 — meter `premium-comm`

## Full unique catalog

| ID | Name | Roles | Premium | In execute? |
|----|------|-------|---------|-------------|
| `spawn_agent` | Spawn agent | orchestrator,lead |  | yes |
| `message_agent` | Message agent | orchestrator,lead,member,specialist |  | yes |
| `use_app` | Use connected app | orchestrator,lead,member,specialist |  | yes |
| `assign_human` | Assign work to human | orchestrator,lead,member |  | yes |
| `save_memory` | Save agent data | orchestrator,lead,member,specialist |  | yes |
| `save_training` | Save to training | orchestrator,lead,member,specialist |  | yes |
| `create_task` | Create task | orchestrator,lead,member |  | yes |
| `announce_plan` | Announce plan | orchestrator,lead,member,specialist |  | yes |
| `list_customers` | List customers | orchestrator,lead,member,specialist |  | yes |
| `get_customer` | Get customer | orchestrator,lead,member,specialist |  | yes |
| `update_customer` | Update customer | orchestrator,lead,member |  | yes |
| `log_customer_activity` | Log customer activity | orchestrator,lead,member,specialist |  | yes |
| `create_deal` | Create deal | orchestrator,lead,member |  | yes |
| `schedule_meeting` | Schedule meeting / diary | orchestrator,lead,member |  | yes |
| `list_diary` | List diary / meetings | orchestrator,lead,member,specialist |  | yes |
| `draft_email` | Draft email | orchestrator,lead,member,specialist |  | yes |
| `send_email` | Send email (premium) | orchestrator,lead,member | yes | yes |
| `draft_sms` | Draft SMS / text | orchestrator,lead,member,specialist |  | yes |
| `send_sms` | Send SMS (premium) | orchestrator,lead,member | yes | yes |
| `send_whatsapp` | Send WhatsApp (premium) | orchestrator,lead,member | yes | yes |
| `make_voice_call` | Make voice call (premium) | orchestrator,lead,member | yes | yes |
| `log_communication` | Log communication | orchestrator,lead,member,specialist |  | yes |
| `send_message` | Send message (any channel) | orchestrator,lead,member | yes | yes |
| `generate_image` | Generate image (premium) | orchestrator,lead,member,specialist | yes | yes |
| `generate_video` | Generate video (premium) | orchestrator,lead,member | yes | yes |
| `generate_content` | Generate content | orchestrator,lead,member,specialist |  | yes |
| `research` | Research topic | orchestrator,lead,member,specialist |  | yes |
| `summarize` | Summarize text | orchestrator,lead,member,specialist |  | yes |
| `get_time` | Get current time | orchestrator,lead,member,specialist |  | yes |
| `suggest_times` | Suggest meeting times | orchestrator,lead,member |  | yes |
| `create_invoice_draft` | Create invoice draft | orchestrator,lead,member |  | yes |
| `update_pipeline` | Update pipeline / deal | orchestrator,lead,member |  | yes |
| `escalate_to_human` | Escalate to human | orchestrator,lead,member |  | yes |
| `search_memory` | Search agent memory | orchestrator,lead,member,specialist |  | yes |
| `search_knowledge` | Search training knowledge | orchestrator,lead,member,specialist |  | yes |
| `set_agent_status` | Set my status | orchestrator,lead |  | yes |
| `create_reminder` | Create reminder / follow-up | orchestrator,lead,member,specialist |  | yes |
| `spawn_team` | Spawn team of agents | orchestrator,lead |  | yes |
| `spawn_specialist` | Spawn specialist | orchestrator,lead |  | yes |
| `clone_agent` | Clone agent | orchestrator,lead |  | yes |
| `enable_skills_on` | Enable skills on agent | orchestrator,lead |  | yes |
| `bulk_enable_skills` | Bulk enable skills | orchestrator,lead |  | yes |
| `configure_agent` | Configure agent | orchestrator,lead |  | yes |
| `promote_to_lead` | Promote to lead | orchestrator |  | yes |
| `qualify_lead` | Qualify lead | orchestrator,lead,member |  | **NO** |
| `write_proposal` | Write proposal | orchestrator,lead,member |  | **NO** |
| `objection_handler` | Handle objection | orchestrator,lead,member,specialist |  | **NO** |
| `follow_up_sequence` | Create follow-up sequence | orchestrator,lead,member |  | **NO** |
| `cold_outreach` | Cold outreach | orchestrator,lead,member |  | **NO** |
| `book_meeting` | Book meeting | orchestrator,lead,member |  | **NO** |
| `triage_ticket` | Triage support ticket | orchestrator,lead,member,specialist |  | **NO** |
| `refund_or_credit` | Decide refund / credit | orchestrator,lead,member |  | **NO** |
| `knowledge_answer` | Answer from knowledge base | orchestrator,lead,member,specialist |  | **NO** |
| `escalation_reason` | Write escalation note | orchestrator,lead,member |  | **NO** |
| `onboarding_flow` | Create onboarding flow | orchestrator,lead,member |  | **NO** |
| `linkedin_write_post` | Write LinkedIn post (draft) | orchestrator,lead,member,specialist |  | **NO** |
| `twitter_thread` | Write Twitter/X thread | orchestrator,lead,member,specialist |  | **NO** |
| `ad_copy` | Write ad copy | orchestrator,lead,member,specialist |  | **NO** |
| `email_newsletter` | Write newsletter | orchestrator,lead,member |  | **NO** |
| `video_script` | Write video script | orchestrator,lead,member,specialist |  | **NO** |
| `seo_article` | Write SEO article | orchestrator,lead,member |  | **NO** |
| `case_study` | Write case study | orchestrator,lead,member |  | **NO** |
| `write_api_endpoint` | Write API endpoint | orchestrator,lead,member,specialist |  | **NO** |
| `write_tests` | Write tests | orchestrator,lead,member,specialist |  | **NO** |
| `refactor_code` | Refactor code | orchestrator,lead,member,specialist |  | **NO** |
| `debug_error` | Debug error | orchestrator,lead,member,specialist |  | **NO** |
| `database_migration` | Create DB migration | orchestrator,lead,member,specialist |  | **NO** |
| `docker_setup` | Create Docker setup | orchestrator,lead,member,specialist |  | **NO** |
| `ci_pipeline` | Create CI/CD pipeline | orchestrator,lead,member,specialist |  | **NO** |
| `code_review` | Perform code review | orchestrator,lead,member,specialist |  | **NO** |
| `build_dashboard_query` | Build dashboard query | orchestrator,lead,member,specialist |  | **NO** |
| `generate_report` | Generate report | orchestrator,lead,member |  | **NO** |
| `analyze_metrics` | Analyze metrics | orchestrator,lead,member,specialist |  | **NO** |
| `forecast` | Forecast numbers | orchestrator,lead,member |  | **NO** |
| `chase_payment` | Write payment chase | orchestrator,lead,member |  | **NO** |
| `expense_categorize` | Categorize expenses | orchestrator,lead,member |  | **NO** |
| `monthly_summary` | Monthly business summary | orchestrator,lead |  | **NO** |
| `write_job_description` | Write job description | orchestrator,lead,member |  | **NO** |
| `interview_questions` | Create interview questions | orchestrator,lead,member |  | **NO** |
| `onboarding_plan` | Create onboarding plan | orchestrator,lead,member |  | **NO** |
| `performance_review` | Draft performance review | orchestrator,lead |  | **NO** |
| `draft_contract_clause` | Draft contract clause | orchestrator,lead,member |  | **NO** |
| `gdpr_request` | Handle GDPR / data request | orchestrator,lead,member |  | **NO** |
| `risk_assessment` | Risk assessment | orchestrator,lead,member |  | **NO** |
| `brand_voice_guide` | Create brand voice guide | orchestrator,lead,member |  | **NO** |
| `logo_concept` | Logo concept ideas | orchestrator,lead,member |  | **NO** |
| `ui_copy` | Write UI microcopy | orchestrator,lead,member,specialist |  | **NO** |
| `design_workflow` | Design workflow | orchestrator,lead,member |  | **NO** |
| `write_zapier_webhook` | Write webhook payload | orchestrator,lead,member,specialist |  | **NO** |
| `reflect_on_outcome` | Reflect on outcome | orchestrator,lead,member,specialist |  | **NO** |
| `improve_prompt` | Improve own prompt | orchestrator,lead |  | **NO** |
| `save_lesson` | Save lesson to training | orchestrator,lead,member,specialist |  | **NO** |
| `prioritize_list` | Prioritize list | orchestrator,lead,member,specialist |  | **NO** |
| `meeting_agenda` | Create meeting agenda | orchestrator,lead,member |  | **NO** |
| `action_items` | Extract action items | orchestrator,lead,member,specialist |  | **NO** |
| `decision_log` | Log decision | orchestrator,lead,member |  | **NO** |
| `pause_agent` | Pause agent | orchestrator,lead |  | yes |
| `resume_agent` | Resume agent | orchestrator,lead |  | yes |
| `delete_agent` | Delete agent | orchestrator |  | yes |
| `list_team` | List my team | orchestrator,lead,member |  | yes |
| `build_icp` | Build ICP | orchestrator,lead,member,specialist |  | **NO** |
| `enrich_lead` | Enrich lead | orchestrator,lead,member |  | **NO** |
| `score_lead` | Score lead | orchestrator,lead,member,specialist |  | **NO** |
| `build_sales_script` | Build sales script | orchestrator,lead,member,specialist |  | **NO** |
| `competitive_battlecard` | Competitive battlecard | orchestrator,lead,member |  | **NO** |
| `proposal_pricing` | Proposal pricing calculator | orchestrator,lead,member |  | **NO** |
| `close_plan` | Close plan | orchestrator,lead,member |  | **NO** |
| `upsell_crosssell` | Upsell / cross-sell | orchestrator,lead,member |  | **NO** |
| `churn_risk` | Churn risk analysis | orchestrator,lead,member |  | **NO** |
| `health_score` | Customer health score | orchestrator,lead,member,specialist |  | **NO** |
| `qbr_prep` | QBR prep pack | orchestrator,lead,member |  | **NO** |
| `success_plan` | Success plan | orchestrator,lead,member |  | **NO** |
| `ticket_root_cause` | Ticket root cause | orchestrator,lead,member,specialist |  | **NO** |
| `sla_breach_risk` | SLA breach risk | orchestrator,lead,member |  | **NO** |
| `knowledge_gap` | Knowledge gap finder | orchestrator,lead,member |  | **NO** |
| `cancel_save` | Cancellation save | orchestrator,lead,member |  | **NO** |
| `content_calendar` | Content calendar | orchestrator,lead,member,specialist |  | **NO** |
| `landing_page_copy` | Landing page copy | orchestrator,lead,member |  | **NO** |
| `email_sequence` | Email nurture sequence | orchestrator,lead,member |  | **NO** |
| `ab_test_ideas` | A/B test ideas | orchestrator,lead,member,specialist |  | **NO** |
| `influencer_pitch` | Influencer pitch | orchestrator,lead,member |  | **NO** |
| `referral_program` | Referral program design | orchestrator,lead,member |  | **NO** |
| `webinar_outline` | Webinar outline | orchestrator,lead,member |  | **NO** |
| `growth_loop` | Growth loop design | orchestrator,lead |  | **NO** |
| `prioritise_features` | Prioritise features | orchestrator,lead,member |  | **NO** |
| `user_story_map` | User story map | orchestrator,lead,member |  | **NO** |
| `roadmap_quarter` | Quarterly roadmap | orchestrator,lead |  | **NO** |
| `changelog` | Write changelog | orchestrator,lead,member |  | **NO** |
| `feedback_theming` | Theme customer feedback | orchestrator,lead,member,specialist |  | **NO** |
| `cashflow_forecast` | Cashflow forecast | orchestrator,lead,member |  | **NO** |
| `pricing_model` | Pricing model review | orchestrator,lead |  | **NO** |
| `expense_policy` | Expense policy checker | orchestrator,lead,member |  | **NO** |
| `subscription_health` | Subscription health | orchestrator,lead |  | **NO** |
| `tax_ready_export` | Tax-ready export | orchestrator,lead,member |  | **NO** |
| `sourcing_plan` | Sourcing plan | orchestrator,lead,member |  | **NO** |
| `cv_screen` | CV screen | orchestrator,lead,member,specialist |  | **NO** |
| `offer_letter_draft` | Offer letter draft | orchestrator,lead |  | **NO** |
| `team_morale` | Team morale pulse | orchestrator,lead |  | **NO** |
| `one_on_one_agenda` | 1:1 agenda generator | orchestrator,lead,member |  | **NO** |
| `policy_generator` | Policy generator | orchestrator,lead |  | **NO** |
| `contract_risk_scan` | Contract risk scan | orchestrator,lead,member |  | **NO** |
| `data_processing_addendum` | DPA draft | orchestrator,lead |  | **NO** |
| `incident_response` | Incident response plan | orchestrator,lead |  | **NO** |
| `architecture_review` | Architecture review | orchestrator,lead,specialist |  | **NO** |
| `openapi_spec` | OpenAPI spec | orchestrator,lead,member,specialist |  | **NO** |
| `sql_optimise` | SQL optimiser | orchestrator,lead,member,specialist |  | **NO** |
| `load_test_plan` | Load test plan | orchestrator,lead,member |  | **NO** |
| `feature_flag_plan` | Feature flag rollout plan | orchestrator,lead,member |  | **NO** |
| `tech_debt_audit` | Tech debt audit | orchestrator,lead,member |  | **NO** |
| `pair_debug` | Pair debug session | orchestrator,lead,member,specialist |  | **NO** |
| `sdk_client` | Generate SDK client | orchestrator,lead,member,specialist |  | **NO** |
| `metric_definition` | Define metric | orchestrator,lead,member,specialist |  | **NO** |
| `cohort_analysis` | Cohort analysis | orchestrator,lead,member |  | **NO** |
| `funnel_report` | Funnel report | orchestrator,lead,member |  | **NO** |
| `anomaly_detect` | Anomaly detector | orchestrator,lead,member,specialist |  | **NO** |
| `experiment_design` | Experiment design | orchestrator,lead,member |  | **NO** |
| `webhook_design` | Webhook design | orchestrator,lead,member,specialist |  | **NO** |
| `etl_pipeline` | ETL pipeline sketch | orchestrator,lead,member |  | **NO** |
| `oauth_flow` | OAuth integration flow | orchestrator,lead,member |  | **NO** |
| `cron_schedule` | Cron / schedule design | orchestrator,lead,member |  | **NO** |
| `sync_conflict` | Sync conflict resolver | orchestrator,lead,member |  | **NO** |
| `brand_guidelines` | Brand guidelines | orchestrator,lead,member |  | **NO** |
| `illustration_brief` | Illustration brief | orchestrator,lead,member |  | **NO** |
| `pitch_deck_outline` | Pitch deck outline | orchestrator,lead |  | **NO** |
| `social_asset_pack` | Social asset pack | orchestrator,lead,member |  | **NO** |
| `weekly_review` | Weekly review | orchestrator,lead,member,specialist |  | **NO** |
| `lesson_extract` | Lesson extract | orchestrator,lead,member,specialist |  | **NO** |
| `prompt_diff` | Prompt diff | orchestrator,lead,member |  | **NO** |
| `autonomy_audit` | Autonomy audit | orchestrator,lead |  | **NO** |
| `training_gap` | Training gap report | orchestrator,lead,member |  | **NO** |
| `runbook` | Write runbook | orchestrator,lead,member |  | **NO** |
| `meeting_notes` | Meeting notes + actions | orchestrator,lead,member,specialist |  | **NO** |
| `okrs` | Write OKRs | orchestrator,lead |  | **NO** |
| `risk_register` | Risk register | orchestrator,lead,member |  | **NO** |
| `status_update` | Status update | orchestrator,lead,member |  | **NO** |
| `time_audit` | Time audit | orchestrator,lead,member |  | **NO** |
| `vendor_eval` | Vendor evaluation | orchestrator,lead,member |  | **NO** |
| `process_map` | Process map | orchestrator,lead,member |  | **NO** |
| `personalised_video_script` | Personalised video script | orchestrator,lead,member |  | **NO** |
| `sms_campaign` | SMS campaign draft | orchestrator,lead,member |  | **NO** |
| `support_macro` | Support macro | orchestrator,lead,member,specialist |  | **NO** |
| `exec_summary_email` | Executive summary email | orchestrator,lead,member |  | **NO** |
| `post_mortem` | Post mortem | orchestrator,lead,member |  | **NO** |
| `skill_recommend` | Recommend skills for agent | orchestrator,lead |  | **NO** |
| `agent_compare` | Compare agents | orchestrator,lead |  | **NO** |
| `facebook_post` | Facebook post | orchestrator,lead,member,specialist | yes | yes |
| `facebook_reply_comment` | Reply to Facebook comment | orchestrator,lead,member,specialist | yes | yes |
| `facebook_reply_message` | Reply to Facebook message / DM | orchestrator,lead,member | yes | yes |
| `facebook_get_comments` | Get Facebook comments | orchestrator,lead,member,specialist |  | yes |
| `facebook_get_posts` | List Facebook page posts | orchestrator,lead,member |  | yes |
| `facebook_get_conversations` | Facebook Messenger inbox | orchestrator,lead,member |  | yes |
| `facebook_like_comment` | Like Facebook comment | orchestrator,lead,member |  | yes |
| `instagram_post` | Instagram post | orchestrator,lead,member,specialist | yes | yes |
| `instagram_reply_comment` | Reply to Instagram comment | orchestrator,lead,member,specialist | yes | yes |
| `instagram_get_comments` | Get Instagram comments | orchestrator,lead,member,specialist |  | yes |
| `instagram_get_media` | List Instagram media | orchestrator,lead,member |  | yes |
| `linkedin_post` | LinkedIn post (live) | orchestrator,lead,member,specialist | yes | yes |
| `linkedin_comment` | Comment on LinkedIn post | orchestrator,lead,member,specialist | yes | yes |
| `linkedin_get_posts` | List LinkedIn posts | orchestrator,lead,member |  | yes |
| `linkedin_get_comments` | Get LinkedIn comments | orchestrator,lead,member |  | yes |
| `x_post` | Post on X (Twitter) | orchestrator,lead,member,specialist | yes | yes |
| `x_reply` | Reply on X | orchestrator,lead,member,specialist | yes | yes |
| `x_get_mentions` | Get X mentions | orchestrator,lead,member |  | yes |
| `x_get_timeline` | X home timeline | orchestrator,lead,member |  | yes |
| `x_search` | Search on X | orchestrator,lead,member,specialist |  | yes |
| `gmail_send` | Gmail send | orchestrator,lead,member | yes | yes |
| `gmail_reply` | Gmail reply | orchestrator,lead,member | yes | yes |
| `gmail_draft` | Gmail draft | orchestrator,lead,member,specialist |  | yes |
| `gmail_list` | List Gmail messages | orchestrator,lead,member,specialist |  | yes |
| `gmail_get_thread` | Get Gmail thread | orchestrator,lead,member |  | yes |
| `gmail_search` | Search Gmail | orchestrator,lead,member,specialist |  | yes |
| `gmail_archive` | Archive Gmail thread | orchestrator,lead,member |  | yes |
| `email_send` | Send email (any) | orchestrator,lead,member | yes | yes |
| `email_reply` | Reply by email | orchestrator,lead,member | yes | yes |
| `slack_post` | Post to Slack | orchestrator,lead,member,specialist | yes | yes |
| `slack_reply_thread` | Reply in Slack thread | orchestrator,lead,member | yes | yes |
| `slack_dm` | Send Slack DM | orchestrator,lead,member | yes | yes |
| `slack_list_channels` | List Slack channels | orchestrator,lead,member |  | yes |
| `slack_get_messages` | Get Slack messages | orchestrator,lead,member |  | yes |
| `calendar_create_event` | Create calendar event | orchestrator,lead,member | yes | yes |
| `calendar_list_events` | List calendar events | orchestrator,lead,member,specialist |  | yes |
| `calendar_update_event` | Update calendar event | orchestrator,lead,member |  | yes |
| `calendar_delete_event` | Delete calendar event | orchestrator,lead,member |  | yes |
| `sheets_append` | Append to Google Sheet | orchestrator,lead,member,specialist | yes | yes |
| `sheets_read` | Read Google Sheet | orchestrator,lead,member,specialist |  | yes |
| `sheets_update` | Update Google Sheet cells | orchestrator,lead,member |  | yes |
| `sheets_create_sheet` | Create new sheet tab | orchestrator,lead,member |  | yes |
| `shopify_create_order_note` | Add Shopify order note | orchestrator,lead,member |  | yes |
| `shopify_update_product` | Update Shopify product | orchestrator,lead,member,specialist |  | yes |
| `shopify_get_orders` | List Shopify orders | orchestrator,lead,member |  | yes |
| `shopify_get_customers` | List Shopify customers | orchestrator,lead,member |  | yes |
| `shopify_fulfill_order` | Fulfill Shopify order | orchestrator,lead,member |  | yes |
| `hubspot_create_contact` | Create HubSpot contact | orchestrator,lead,member |  | yes |
| `hubspot_create_deal` | Create HubSpot deal | orchestrator,lead,member |  | yes |
| `hubspot_log_note` | Log note in HubSpot | orchestrator,lead,member |  | yes |
| `hubspot_get_contacts` | Search HubSpot contacts | orchestrator,lead,member |  | yes |
| `notion_create_page` | Create Notion page | orchestrator,lead,member,specialist |  | yes |
| `notion_update_page` | Update Notion page | orchestrator,lead,member |  | yes |
| `notion_query_database` | Query Notion database | orchestrator,lead,member,specialist |  | yes |
| `notion_append_block` | Append blocks to Notion page | orchestrator,lead,member |  | yes |
| `discord_post` | Post to Discord | orchestrator,lead,member | yes | yes |
| `discord_dm_user` | DM Discord user | orchestrator,lead,member | yes | yes |
| `whatsapp_send` | Send WhatsApp message | orchestrator,lead,member | yes | yes |
| `whatsapp_reply` | Reply on WhatsApp | orchestrator,lead,member | yes | yes |
| `mailchimp_add_subscriber` | Add Mailchimp subscriber | orchestrator,lead,member |  | yes |
| `mailchimp_create_campaign` | Create Mailchimp campaign | orchestrator,lead,member |  | yes |
| `dropbox_upload` | Upload to Dropbox | orchestrator,lead,member |  | yes |
| `dropbox_list` | List Dropbox folder | orchestrator,lead,member |  | yes |

## Unwired / draft-only (not found in execute_skill)

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
- `brand_voice_guide`
- `logo_concept`
- `ui_copy`
- `design_workflow`
- `write_zapier_webhook`
- `reflect_on_outcome`
- `improve_prompt`
- `save_lesson`
- `prioritize_list`
- `meeting_agenda`
- `action_items`
- `decision_log`
- `build_icp`
- `enrich_lead`
- `score_lead`
- `build_sales_script`
- `competitive_battlecard`
- `proposal_pricing`
- `close_plan`
- `upsell_crosssell`
- `churn_risk`
- `health_score`
- `qbr_prep`
- `success_plan`
- `ticket_root_cause`
- `sla_breach_risk`
- `knowledge_gap`
- `cancel_save`
- `content_calendar`
- `landing_page_copy`
- `email_sequence`
- `ab_test_ideas`
- `influencer_pitch`
- `referral_program`
- `webinar_outline`
- `growth_loop`
- `prioritise_features`
- `user_story_map`
- `roadmap_quarter`
- `changelog`
- `feedback_theming`
- `cashflow_forecast`
- `pricing_model`
- `expense_policy`
- `subscription_health`
- `tax_ready_export`
- `sourcing_plan`
- `cv_screen`
- `offer_letter_draft`
- `team_morale`
- `one_on_one_agenda`
- `policy_generator`
- `contract_risk_scan`
- `data_processing_addendum`
- `incident_response`
- `architecture_review`
- `openapi_spec`
- `sql_optimise`
- `load_test_plan`
- `feature_flag_plan`
- `tech_debt_audit`
- `pair_debug`
- `sdk_client`
- `metric_definition`
- `cohort_analysis`
- `funnel_report`
- `anomaly_detect`
- `experiment_design`
- `webhook_design`
- `etl_pipeline`
- `oauth_flow`
- `cron_schedule`
- `sync_conflict`
- `brand_guidelines`
- `illustration_brief`
- `pitch_deck_outline`
- `social_asset_pack`
- `weekly_review`
- `lesson_extract`
- `prompt_diff`
- `autonomy_audit`
- `training_gap`
- `runbook`
- `meeting_notes`
- `okrs`
- `risk_register`
- `status_update`
- `time_audit`
- `vendor_eval`
- `process_map`
- `personalised_video_script`
- `sms_campaign`
- `support_macro`
- `exec_summary_email`
- `post_mortem`
- `skill_recommend`
- `agent_compare`
