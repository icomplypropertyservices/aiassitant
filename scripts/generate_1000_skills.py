#!/usr/bin/env python3
"""Generate 20 domain skill packs × 50 skills = 1000 unique catalog skills."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "app" / "skill_packs"

ALL_ROLES = ["orchestrator", "lead", "member", "specialist"]
LEAD_ROLES = ["orchestrator", "lead", "member"]
ORCH_LEAD = ["orchestrator", "lead"]

# 20 packs × 50 skills. Each entry is (slug, title, description, args, roles, premium?, cost)
# Handlers fall through to _skill_catalog_deliverable unless aliased later.

PACKS: dict[str, dict] = {
    "01_sales": {
        "category": "sales",
        "label": "Sales",
        "skills": [
            ("sales_qualify_lead", "Qualify lead", "Score and qualify a lead against ICP and BANT/MEDDIC-style criteria.", ["lead", "company", "notes", "score_model"], LEAD_ROLES),
            ("sales_discovery_script", "Discovery call script", "Write a discovery call script with questions and talk tracks.", ["persona", "product", "objections"], ALL_ROLES),
            ("sales_demo_agenda", "Demo agenda", "Build a product demo agenda tailored to the prospect.", ["prospect", "product", "duration_min"], ALL_ROLES),
            ("sales_proposal_outline", "Proposal outline", "Outline a commercial proposal with value, scope, and pricing placeholders.", ["customer", "scope", "price"], LEAD_ROLES),
            ("sales_proposal_full", "Full sales proposal", "Draft a complete sales proposal document.", ["customer", "scope", "price", "terms"], LEAD_ROLES),
            ("sales_roi_calculator", "ROI calculator brief", "Build ROI assumptions and a one-page ROI narrative.", ["inputs", "baseline", "target"], ALL_ROLES),
            ("sales_objection_handler", "Objection handler", "Create rebuttals for common sales objections.", ["objections", "product", "persona"], ALL_ROLES),
            ("sales_negotiation_plan", "Negotiation plan", "Plan concessions, walk-away, and trade structure.", ["deal", "constraints", "authority"], LEAD_ROLES),
            ("sales_close_plan", "Close plan", "Multi-step close plan with next actions and owners.", ["deal", "stakeholders", "deadline"], LEAD_ROLES),
            ("sales_pipeline_review", "Pipeline review", "Summarize pipeline health and risks by stage.", ["deals", "period"], LEAD_ROLES),
            ("sales_forecast_notes", "Forecast notes", "Write forecast commentary from deal list.", ["deals", "period", "confidence"], LEAD_ROLES),
            ("sales_account_map", "Account map", "Map stakeholders, power, and buying process.", ["account", "contacts"], ALL_ROLES),
            ("sales_territory_plan", "Territory plan", "Plan territory coverage and prioritization.", ["region", "accounts", "quota"], LEAD_ROLES),
            ("sales_quota_breakdown", "Quota breakdown", "Break quota into weekly activity and deal targets.", ["quota", "avg_deal", "win_rate"], LEAD_ROLES),
            ("sales_cold_email", "Cold email sequence", "Write a multi-touch cold email sequence.", ["persona", "offer", "touches"], ALL_ROLES),
            ("sales_cold_call_script", "Cold call script", "Write a cold call opener and talk track.", ["persona", "offer"], ALL_ROLES),
            ("sales_linkedin_outreach", "LinkedIn outreach", "Draft LinkedIn connection + follow-up messages.", ["persona", "offer", "profile_notes"], ALL_ROLES),
            ("sales_follow_up_email", "Follow-up email", "Write a post-meeting follow-up email.", ["meeting_notes", "next_steps"], ALL_ROLES),
            ("sales_renewal_play", "Renewal playbook", "Plan renewal outreach and expansion motions.", ["account", "arr", "risks"], LEAD_ROLES),
            ("sales_upsell_plan", "Upsell plan", "Identify upsell paths and messaging.", ["account", "products", "usage"], LEAD_ROLES),
            ("sales_cross_sell_plan", "Cross-sell plan", "Design cross-sell opportunities across products.", ["account", "portfolio"], LEAD_ROLES),
            ("sales_win_loss", "Win/loss analysis", "Analyze why a deal was won or lost.", ["deal", "notes", "outcome"], ALL_ROLES),
            ("sales_competitor_battlecard", "Competitor battlecard", "Create a sales battlecard vs a competitor.", ["competitor", "our_product", "differentiators"], ALL_ROLES),
            ("sales_pricing_options", "Pricing options", "Present good/better/best pricing options.", ["package", "constraints"], LEAD_ROLES),
            ("sales_discount_request", "Discount request brief", "Justify a discount request for approval.", ["deal", "requested_discount", "rationale"], LEAD_ROLES),
            ("sales_mutual_action_plan", "Mutual action plan", "Create a shared close plan with buyer tasks.", ["deal", "milestones"], ALL_ROLES),
            ("sales_rfp_response", "RFP response draft", "Draft answers for RFP questions.", ["questions", "product", "company"], LEAD_ROLES),
            ("sales_security_questionnaire", "Security questionnaire assist", "Draft responses for security questionnaire items.", ["questions", "security_notes"], ALL_ROLES),
            ("sales_case_study_brief", "Case study brief", "Outline a customer case study for sales use.", ["customer", "results", "industry"], ALL_ROLES),
            ("sales_testimonial_request", "Testimonial request", "Write a customer testimonial request message.", ["customer", "relationship"], ALL_ROLES),
            ("sales_referral_ask", "Referral ask", "Draft a referral request for happy customers.", ["customer", "offer"], ALL_ROLES),
            ("sales_event_followup", "Event follow-up", "Write event/trade-show follow-up messages.", ["event", "leads", "offer"], ALL_ROLES),
            ("sales_handoff_csm", "Sales→CSM handoff", "Create a structured handoff package for CS.", ["account", "deal", "promises"], LEAD_ROLES),
            ("sales_call_summary", "Sales call summary", "Summarize a sales call with action items.", ["notes", "attendees"], ALL_ROLES),
            ("sales_stage_criteria", "Stage exit criteria", "Define pipeline stage exit criteria.", ["stages", "product"], LEAD_ROLES),
            ("sales_playbook_snippet", "Playbook snippet", "Write a playbook section for a sales motion.", ["motion", "steps"], ALL_ROLES),
            ("sales_abm_target_list", "ABM target list brief", "Prioritize accounts for ABM with reasons.", ["accounts", "icp"], LEAD_ROLES),
            ("sales_multi_thread_plan", "Multi-thread plan", "Plan multi-threading across buyer roles.", ["account", "contacts"], LEAD_ROLES),
            ("sales_champion_enablement", "Champion enablement", "Materials and talk track for a champion.", ["champion", "internal_buyers", "product"], ALL_ROLES),
            ("sales_economic_buyer_brief", "Economic buyer brief", "One-pager for the economic buyer.", ["buyer", "business_case"], ALL_ROLES),
            ("sales_tech_buyer_brief", "Technical buyer brief", "Technical evaluation brief for IT/security.", ["stack", "requirements"], ALL_ROLES),
            ("sales_legal_review_prep", "Legal review prep", "Prep redlines and negotiation notes for legal.", ["contract_points", "risks"], LEAD_ROLES),
            ("sales_qbr_deck_outline", "Customer QBR outline", "Outline a commercial QBR for an account.", ["account", "metrics", "period"], ALL_ROLES),
            ("sales_channel_partner_brief", "Channel partner brief", "Brief a partner on co-selling an opportunity.", ["partner", "deal"], LEAD_ROLES),
            ("sales_inbound_triage", "Inbound lead triage", "Triage inbound leads with priority and routing.", ["leads", "rules"], ALL_ROLES),
            ("sales_outbound_cadence", "Outbound cadence", "Design multi-channel outbound cadence.", ["persona", "channels", "days"], ALL_ROLES),
            ("sales_meeting_prep", "Meeting prep pack", "Prep agenda, research, and goals for a sales meeting.", ["prospect", "goal"], ALL_ROLES),
            ("sales_slack_deal_update", "Deal update (Slack-ready)", "Write a concise deal status update for the team.", ["deal", "stage", "risks"], ALL_ROLES),
            ("sales_commission_explain", "Commission explanation", "Explain commission impact of a deal structure.", ["deal", "plan"], LEAD_ROLES),
            ("sales_weekly_plan", "AE weekly plan", "Create a weekly sales activity plan.", ["pipeline", "quota", "calendar"], ALL_ROLES),
        ],
    },
    "02_marketing": {
        "category": "content",
        "label": "Marketing",
        "skills": [
            ("mkt_positioning", "Positioning statement", "Craft product positioning and messaging pillars.", ["product", "audience", "competitors"], ALL_ROLES),
            ("mkt_messaging_matrix", "Messaging matrix", "Build message matrix by persona and stage.", ["personas", "product"], ALL_ROLES),
            ("mkt_campaign_brief", "Campaign brief", "Write a full campaign brief.", ["goal", "audience", "channels", "budget"], LEAD_ROLES),
            ("mkt_content_calendar", "Content calendar", "Plan a content calendar for a period.", ["themes", "channels", "weeks"], ALL_ROLES),
            ("mkt_blog_outline", "Blog outline", "Outline a blog post with SEO angles.", ["topic", "keywords", "audience"], ALL_ROLES),
            ("mkt_blog_draft", "Blog draft", "Draft a full blog article.", ["topic", "keywords", "tone", "length"], ALL_ROLES),
            ("mkt_landing_page", "Landing page copy", "Write landing page hero, sections, and CTA.", ["offer", "audience", "proof"], ALL_ROLES),
            ("mkt_ad_copy", "Ad copy set", "Write ad variants for paid channels.", ["offer", "channel", "audience"], ALL_ROLES),
            ("mkt_seo_keyword_map", "SEO keyword map", "Map keywords to pages and intent.", ["seed", "site"], ALL_ROLES),
            ("mkt_seo_meta", "SEO meta tags", "Write title/description meta for pages.", ["pages", "keywords"], ALL_ROLES),
            ("mkt_email_newsletter", "Newsletter draft", "Draft an email newsletter issue.", ["topics", "audience", "cta"], ALL_ROLES),
            ("mkt_nurture_sequence", "Nurture sequence", "Multi-email nurture sequence.", ["persona", "offer", "steps"], ALL_ROLES),
            ("mkt_webinar_plan", "Webinar plan", "Plan webinar agenda, promo, and follow-up.", ["topic", "date", "audience"], ALL_ROLES),
            ("mkt_press_release", "Press release", "Draft a press release.", ["announcement", "quotes", "boilerplate"], LEAD_ROLES),
            ("mkt_brand_voice", "Brand voice guide", "Document brand voice and do/don't examples.", ["brand", "samples"], ALL_ROLES),
            ("mkt_competitor_content", "Competitor content audit", "Audit competitor content themes and gaps.", ["competitors", "topics"], ALL_ROLES),
            ("mkt_persona_card", "Buyer persona card", "Create a detailed buyer persona card.", ["role", "data", "pain"], ALL_ROLES),
            ("mkt_journey_map", "Customer journey map", "Map journey stages, moments, and content.", ["persona", "stages"], ALL_ROLES),
            ("mkt_ab_test_plan", "A/B test plan", "Design an A/B test hypothesis and metrics.", ["asset", "variants", "metric"], ALL_ROLES),
            ("mkt_utm_plan", "UTM tagging plan", "Define UTM structure for campaigns.", ["campaigns", "channels"], ALL_ROLES),
            ("mkt_launch_checklist", "Product launch checklist", "Checklist for a product marketing launch.", ["product", "date", "channels"], LEAD_ROLES),
            ("mkt_pricing_page", "Pricing page copy", "Write pricing page copy and FAQs.", ["plans", "objections"], ALL_ROLES),
            ("mkt_case_study", "Marketing case study", "Write a full marketing case study.", ["customer", "results", "quote"], ALL_ROLES),
            ("mkt_infographic_brief", "Infographic brief", "Brief design for an infographic.", ["topic", "stats", "sections"], ALL_ROLES),
            ("mkt_video_script", "Marketing video script", "Script a short marketing video.", ["goal", "duration", "cta"], ALL_ROLES),
            ("mkt_podcast_outline", "Podcast episode outline", "Outline a podcast episode.", ["topic", "guests", "segments"], ALL_ROLES),
            ("mkt_community_plan", "Community plan", "Plan community engagement and content.", ["platform", "audience", "goals"], ALL_ROLES),
            ("mkt_influencer_brief", "Influencer brief", "Brief for influencer or creator partnership.", ["creator", "offer", "deliverables"], LEAD_ROLES),
            ("mkt_event_booth", "Event booth plan", "Plan booth messaging and lead capture.", ["event", "offer"], ALL_ROLES),
            ("mkt_lead_magnet", "Lead magnet", "Create lead magnet outline and CTA.", ["topic", "format", "audience"], ALL_ROLES),
            ("mkt_gated_content", "Gated content outline", "Outline gated asset and form fields.", ["topic", "value"], ALL_ROLES),
            ("mkt_retargeting_ads", "Retargeting ad set", "Write retargeting ad copy by funnel stage.", ["stages", "offer"], ALL_ROLES),
            ("mkt_brand_guidelines_snip", "Brand guidelines snippet", "Write a brand guideline section.", ["section", "examples"], ALL_ROLES),
            ("mkt_tagline_options", "Tagline options", "Generate tagline options with rationale.", ["product", "tone", "count"], ALL_ROLES),
            ("mkt_slogan_campaign", "Campaign slogan", "Slogans for a named campaign.", ["campaign", "theme"], ALL_ROLES),
            ("mkt_pr_pitch", "PR pitch email", "Pitch email to journalists/podcasts.", ["story", "outlet"], ALL_ROLES),
            ("mkt_analyst_brief", "Analyst brief", "Brief for industry analysts.", ["product", "metrics"], LEAD_ROLES),
            ("mkt_partner_co_marketing", "Co-marketing plan", "Plan co-marketing with a partner.", ["partner", "assets"], LEAD_ROLES),
            ("mkt_referral_program", "Referral program design", "Design referral incentives and messaging.", ["audience", "reward"], LEAD_ROLES),
            ("mkt_churn_winback", "Win-back campaign", "Win-back email/ads for churned users.", ["segments", "offer"], ALL_ROLES),
            ("mkt_lifecycle_emails", "Lifecycle email map", "Map lifecycle emails by user state.", ["states", "product"], ALL_ROLES),
            ("mkt_onboarding_emails", "Onboarding emails", "Write product onboarding email series.", ["product", "milestones"], ALL_ROLES),
            ("mkt_feature_announce", "Feature announcement", "Announce a feature across channels.", ["feature", "audience", "channels"], ALL_ROLES),
            ("mkt_changelog", "Changelog entry", "Write a clear changelog entry.", ["changes", "version"], ALL_ROLES),
            ("mkt_social_proof", "Social proof pack", "Compile quotes, logos, stats narrative.", ["assets", "claims"], ALL_ROLES),
            ("mkt_budget_plan", "Marketing budget plan", "Allocate marketing budget by channel.", ["budget", "goals", "channels"], LEAD_ROLES),
            ("mkt_kpi_dashboard", "Marketing KPI brief", "Define marketing KPIs and targets.", ["goals", "period"], LEAD_ROLES),
            ("mkt_weekly_report", "Marketing weekly report", "Write marketing weekly performance report.", ["metrics", "highlights"], ALL_ROLES),
            ("mkt_creative_brief", "Creative brief", "Write a creative brief for design/ads.", ["goal", "audience", "mandatories"], ALL_ROLES),
            ("mkt_brand_audit", "Brand audit summary", "Summarize brand consistency issues and fixes.", ["samples", "guidelines"], ALL_ROLES),
        ],
    },
}


def expand_pack_to_50(pack_id: str, category: str, base: list) -> list[dict]:
    """Ensure exactly 50 skills; pad with generated variants if short."""
    skills = []
    seen = set()
    for item in base:
        if len(item) == 5:
            sid, name, desc, args, roles = item
            premium = False
            cost = 0
        else:
            sid, name, desc, args, roles, premium, cost = item
        if sid in seen:
            continue
        seen.add(sid)
        skills.append(_skill(sid, name, desc, args, roles, category, premium, cost, pack_id))

    # If pack definition is incomplete, pad systematically
    i = 1
    while len(skills) < 50:
        sid = f"{pack_id.split('_', 1)[-1]}_auto_{i:02d}"
        if sid in seen:
            i += 1
            continue
        seen.add(sid)
        skills.append(
            _skill(
                sid,
                f"{category.title()} playbook step {i}",
                f"Produce a high-quality {category} deliverable for step {i} of the domain playbook.",
                ["context", "goal", "constraints", "audience"],
                ALL_ROLES,
                category,
                False,
                0,
                pack_id,
            )
        )
        i += 1
    return skills[:50]


def _skill(sid, name, desc, args, roles, category, premium, cost, pack_id):
    d = {
        "id": sid,
        "name": name,
        "description": desc,
        "args": list(args),
        "roles": list(roles),
        "category": category,
        "pack": pack_id,
        "handler": "catalog_deliverable",
    }
    if premium:
        d["premium"] = True
        d["cost_credits"] = float(cost or 0.02)
        d["meter_kind"] = "premium-comm"
    return d


# Domain templates for packs 3-20 (generated systematically with rich names)
DOMAIN_SPECS = [
    ("03_customer_success", "support", "cs", "Customer Success", [
        "health_score", "qbr_prep", "onboarding_plan", "adoption_plan", "churn_risk",
        "expansion_signal", "csm_call_agenda", "success_plan", "milestone_map", "nps_followup",
        "csat_response", "escalation_path", "renewal_forecast", "usage_review", "training_plan",
        "value_realization", "stakeholder_map", "executive_sponsor", "playbook_at_risk", "winback_cs",
        "feature_request_log", "roadmap_sync", "handoff_intake", "kickoff_agenda", "go_live_checklist",
        "support_trend", "time_to_value", "segment_play", "lifecycle_stage", "reference_ask",
        "case_study_cs", "community_invite", "office_hours", "webinar_cs", "email_checkin",
        "slack_update_cs", "risk_mitigation", "multi_product", "partner_cs", "implementation_gap",
        "data_migration_cs", "integration_help", "security_review_cs", "compliance_check", "sla_review",
        "capacity_plan_cs", "territory_cs", "portfolio_review", "weekly_cs_report", "cs_play_custom",
    ]),
    ("04_support", "support", "sup", "Support", [
        "ticket_triage", "reply_draft", "macro_write", "escalation_note", "bug_repro",
        "rca_summary", "kb_article", "faq_update", "deflection_script", "chat_handoff",
        "phone_script_sup", "refund_policy_explain", "status_page_update", "outage_comms", "vip_play",
        "sla_breach_plan", "queue_prioritize", "tag_taxonomy", "csat_recover", "angry_customer",
        "billing_dispute", "login_help", "api_error_help", "integration_troubleshoot", "data_export_help",
        "privacy_request_help", "feature_how_to", "workaround", "release_notes_sup", "known_issue",
        "shift_handoff", "team_huddle", "quality_review", "coaching_note", "training_new_hire",
        "channel_policy", "social_support", "email_template_sup", "internal_note", "public_reply",
        "severity_map", "language_localize", "accessibility_help", "enterprise_support", "partner_ticket",
        "security_incident_sup", "compliance_ticket", "multi_account", "bulk_action_help", "sup_report",
    ]),
    ("05_finance", "finance", "fin", "Finance", [
        "invoice_narrative", "expense_policy", "budget_vs_actual", "cashflow_note", "ar_followup",
        "ap_prioritize", "payroll_summary", "tax_checklist", "audit_prep", "board_pack_fin",
        "fp_a_commentary", "unit_economics", "pricing_model", "discount_policy", "credit_memo_note",
        "collection_script", "vendor_payment_plan", "capex_request", "opex_review", "forecast_model",
        "scenario_plan", "sensitivity", "break_even", "margin_analysis", "cohort_revenue",
        "saas_metrics", "arr_bridge", "deferred_revenue", "rev_rec_note", "close_checklist",
        "reconciliation_note", "bank_match_help", "fx_summary", "treasury_note", "debt_schedule",
        "investor_update_fin", "grant_report", "nonprofit_fin", "cost_center", "allocation_key",
        "transfer_pricing", "intercompany", "lease_accounting_note", "inventory_value", "cogs_analysis",
        "procurement_fin", "contract_value", "milestone_billing", "dunning_email", "fin_weekly",
    ]),
    ("06_legal", "legal", "leg", "Legal & compliance", [
        "nda_checklist", "msa_redline_notes", "dpa_checklist", "tos_summary", "privacy_policy_snip",
        "cookie_notice", "gdpr_dsar", "ccpa_request", "vendor_risk", "contract_summary",
        "clause_compare", "liability_note", "ip_assignment_check", "employment_clause", "offer_letter_notes",
        "termination_checklist", "dispute_timeline", "litigation_hold", "regulatory_scan", "license_review",
        "open_source_policy", "export_control", "sanctions_screen", "marketing_claim_legal", "promo_terms",
        "sweepstakes_rules", "affiliate_terms", "partner_agreement", "sla_legal", "data_processing",
        "subprocessor_list", "security_addendum", "insurance_req", "board_resolution", "cap_table_note",
        "fundraising_docs", "option_grant_note", "trademark_search_brief", "copyright_notice", "dmca_response",
        "whistleblower_policy", "code_of_conduct", "anti_bribery", "conflict_interest", "records_retention",
        "incident_legal", "breach_notify", "law_enforcement_req", "legal_faq", "leg_weekly",
    ]),
    ("07_hr", "hr", "hr", "HR & people", [
        "job_description", "job_scorecard", "interview_plan", "interview_questions", "scorecard_rubric",
        "offer_comp_range", "offer_email", "reject_email", "onboarding_30_60_90", "orientation_agenda",
        "performance_review", "pip_draft", "promotion_case", "comp_review_note", "equity_explain",
        "benefits_summary", "policy_update", "handbook_section", "leave_policy_explain", "remote_policy",
        "dei_initiative", "engagement_survey", "pulse_analysis", "exit_interview", "retention_plan",
        "org_design_note", "headcount_plan", "hiring_forecast", "agency_brief", "internal_mobility",
        "learning_path", "manager_coaching", "1on1_agenda", "team_offsite", "culture_values",
        "recognition_program", "referral_program_hr", "background_check_note", "visa_checklist", "relocate_package",
        "contractor_vs_employee", "workforce_plan", "succession_plan", "critical_role", "skills_matrix",
        "hris_change", "payroll_issue_note", "harassment_report_path", "investigation_plan", "hr_weekly",
    ]),
    ("08_operations", "ops", "ops", "Operations", [
        "sop_write", "process_map", "raci_matrix", "sla_ops", "capacity_plan",
        "shift_roster", "incident_runbook", "postmortem", "change_request", "vendor_ops_score",
        "inventory_count", "reorder_point", "warehouse_layout", "quality_checklist", "safety_brief",
        "facility_plan", "office_move", "travel_policy_ops", "expense_ops", "tooling_stack",
        "automation_opportunity", "kpi_ops", "daily_standup_ops", "war_room_agenda", "continuity_plan",
        "disaster_recovery", "backup_verify", "access_review_ops", "asset_inventory", "procurement_ops",
        "contract_ops", "sla_breach_ops", "customer_ops_escalation", "field_service_plan", "route_plan",
        "maintenance_schedule", "equipment_checklist", "supplier_scorecard", "make_vs_buy", "cost_to_serve",
        "process_mining_note", "bottleneck_analysis", "throughput_plan", "queue_theory_note", "lean_waste",
        "kaizen_event", "5s_checklist", "ops_dashboard", "ops_weekly", "ops_play_custom",
    ]),
    ("09_product", "ops", "prd", "Product", [
        "prd_write", "user_story", "acceptance_criteria", "roadmap_theme", "prioritization_rice",
        "prioritization_ice", "opportunity_solution_tree", "jtbd", "persona_product", "problem_statement",
        "competitive_analysis_prd", "feature_spec", "api_spec_outline", "migration_plan_prd", "deprecation_plan",
        "beta_plan", "ga_checklist", "experiment_design", "success_metrics", "north_star",
        "funnel_analysis", "activation_metric", "retention_curve_note", "pricing_experiment", "packaging_options",
        "launch_readiness", "sales_enablement_prd", "support_enablement", "docs_outline", "changelog_prd",
        "stakeholder_update_prd", "exec_one_pager", "tech_debt_case", "build_vs_buy_prd", "discovery_interview",
        "synthesis_research", "usability_test_plan", "prototype_brief", "design_critique", "accessibility_prd",
        "localization_plan", "platform_strategy", "integration_roadmap", "data_model_note", "analytics_events",
        "privacy_by_design", "security_requirements", "sla_product", "product_weekly", "prd_custom",
    ]),
    ("10_engineering", "code", "eng", "Engineering", [
        "tech_design", "adr_write", "api_design", "schema_design", "threat_model",
        "load_test_plan", "perf_budget", "code_review_checklist", "refactor_plan", "migration_eng",
        "rollback_plan", "feature_flag_plan", "ci_cd_pipeline", "observability_plan", "slo_sli",
        "oncall_runbook", "incident_command", "debug_playbook", "root_cause", "hotfix_plan",
        "dependency_upgrade", "security_patch", "secret_rotation", "iac_plan", "k8s_topology",
        "cost_optimization_eng", "data_pipeline", "etl_design", "ml_serving_note", "sdk_design",
        "client_sdk_changelog", "backward_compat", "versioning_policy", "error_budget", "capacity_eng",
        "chaos_experiment", "dr_drill", "backup_restore_test", "multi_region", "edge_strategy",
        "mobile_release", "web_perf", "accessibility_eng", "i18n_eng", "test_strategy",
        "e2e_plan", "contract_test", "docs_eng", "eng_weekly", "eng_custom",
    ]),
    ("11_data", "data", "dat", "Data & analytics", [
        "metric_definition", "kpi_tree", "dashboard_spec", "sql_query_help", "data_dict",
        "lineage_note", "quality_rule", "anomaly_explain", "cohort_analysis", "funnel_query",
        "ab_analysis", "experiment_readout", "forecast_data", "segmentation", "rfm_model",
        "ltv_model", "churn_model_note", "attribution", "mix_model_note", "geo_analysis",
        "time_series_note", "outlier_review", "sampling_plan", "survey_analysis", "nps_analysis",
        "data_contract", "warehouse_model", "dbt_model_plan", "stream_design", "batch_sla",
        "pii_classification", "retention_policy_data", "access_request_data", "bi_tool_choice", "viz_best_practice",
        "executive_data_story", "board_metrics", "okrs_data", "self_serve_bi", "training_data_team",
        "data_incident", "backfill_plan", "schema_evolution", "cdc_plan", "lakehouse_note",
        "feature_store_note", "ml_eval", "bias_check", "data_weekly", "dat_custom",
    ]),
    ("12_content", "content", "cnt", "Content writing", [
        "longform_article", "thought_leadership", "ghostwrite_post", "speech_draft", "whitepaper_outline",
        "ebook_chapter", "newsletter_long", "script_explainer", "how_to_guide", "comparison_post",
        "listicle", "opinion_piece", "interview_questions_cnt", "transcript_clean", "summary_exec",
        "rewrite_clarity", "tone_shift", "shorten_copy", "expand_copy", "headline_options",
        "subhead_options", "cta_variants", "product_description", "category_copy", "microcopy_ui",
        "error_message_copy", "empty_state_copy", "onboarding_copy", "in_app_message", "push_copy",
        "sms_copy_cnt", "chatbot_script", "faq_long", "glossary_entry", "style_guide_cnt",
        "edit_pass", "fact_check_list", "source_list", "citation_format", "translation_brief",
        "localization_adapt", "accessibility_alt_text", "caption_write", "transcript_chapters", "content_repurpose",
        "series_plan", "editorial_calendar_cnt", "content_audit", "content_weekly", "cnt_custom",
    ]),
    ("13_social", "social", "soc", "Social media", [
        "social_calendar", "tweet_thread", "linkedin_post_soc", "instagram_caption", "tiktok_script",
        "youtube_title", "youtube_desc", "shorts_script", "reel_hook", "story_sequence",
        "carousel_copy", "hashtag_set", "community_reply", "crisis_social", "influencer_list",
        "ugc_brief", "contest_rules_soc", "live_stream_plan", "social_listening", "sentiment_summary",
        "competitor_social", "brand_mention_reply", "employee_advocacy", "social_proof_post", "launch_social",
        "meme_brief", "gif_caption", "poll_ideas", "ama_prep", "twitter_spaces_plan",
        "linkedin_newsletter", "pin_description", "reddit_post", "discord_announce", "slack_community",
        "social_report", "engagement_boost", "dark_post_copy", "boost_budget_note", "creator_contract_note",
        "rights_management", "takedown_request", "platform_policy_check", "geo_social", "language_social",
        "event_social", "hiring_social", "csr_social", "social_weekly", "soc_custom",
    ]),
    ("14_project", "ops", "pm", "Project management", [
        "project_charter", "scope_statement", "wbs", "gantt_outline", "milestone_plan",
        "risk_register", "issue_log", "raid_log", "status_report_pm", "steering_pack",
        "kickoff_deck", "raci_pm", "resource_plan", "budget_pm", "change_control",
        "dependency_map", "critical_path_note", "sprint_plan", "retro_facilitate", "standup_notes",
        "backlog_groom", "estimation_note", "velocity_note", "release_train", "cutover_plan",
        "comms_plan_pm", "stakeholder_map_pm", "rasci", "decision_log", "action_tracker",
        "lessons_learned", "closure_report", "vendor_pm", "statement_of_work", "acceptance_signoff",
        "quality_gate", "test_entry_exit", "uat_plan", "training_plan_pm", "hypercare",
        "war_room_pm", "escalation_pm", "portfolio_view", "program_sync", "okr_align_pm",
        "capacity_pm", "holiday_plan", "pm_template", "pm_weekly", "pm_custom",
    ]),
    ("15_procurement", "commerce", "prc", "Procurement", [
        "rfp_write", "rfi_write", "rfq_write", "vendor_scorecard", "bid_analysis",
        "negotiation_prc", "contract_prc", "sla_prc", "msa_prc", "sow_prc",
        "po_narrative", "three_way_match_note", "supplier_onboard", "supplier_exit", "dual_source",
        "make_buy_prc", "tco_model", "should_cost", "price_benchmark", "index_clause",
        "volume_commitment", "rebate_structure", "payment_terms_prc", "incoterms_note", "import_export",
        "customs_checklist", "quality_agreement", "audit_supplier", "csr_supplier", "conflict_minerals",
        "sustainability_prc", "diversity_spend", "preferred_vendor", "catalog_manage", "tail_spend",
        "maverick_spend", "p2p_process", "approval_matrix", "budget_check_prc", "savings_track",
        "risk_supplier", "geo_risk", "force_majeure_note", "inventory_prc", "consignment",
        "vmi_plan", "edi_note", "prc_weekly", "prc_playbook", "prc_custom",
    ]),
    ("16_logistics", "ops", "log", "Logistics", [
        "ship_plan", "route_optimize", "carrier_select", "sla_log", "eta_comms",
        "delay_comms", "damage_claim", "returns_process", "warehouse_slotting", "pick_pack",
        "cycle_count", "cold_chain", "hazmat_note", "last_mile", "cross_dock",
        "milk_run", "network_design", "dc_location", "inventory_position", "safety_stock",
        "abc_analysis", "demand_plan_log", "s_and_op", "capacity_log", "peak_plan",
        "port_congestion", "customs_log", "bol_checklist", "pod_process", "track_trace",
        "iot_fleet", "fuel_surcharge", "rate_card", "tender_log", "3pl_scorecard",
        "4pl_note", "reverse_logistics", "sustainability_log", "carbon_estimate", "packaging_opt",
        "label_compliance", "temp_excursion", "security_cargo", "insurance_log", "claim_timeline",
        "kpi_log", "control_tower", "log_weekly", "log_playbook", "log_custom",
    ]),
    ("17_real_estate", "ops", "re", "Real estate", [
        "listing_description", "cma_brief", "offer_strategy", "negotiation_re", "showing_script",
        "open_house_plan", "buyer_persona_re", "seller_prep", "staging_checklist", "photo_brief_re",
        "virtual_tour_script", "lease_abstract", "rent_roll_note", "noi_commentary", "cap_rate_note",
        "proforma", "investment_memo_re", "dd_checklist_re", "title_issues", "inspection_response",
        "repair_request", "closing_checklist", "move_in_letter", "tenant_screening", "eviction_process_note",
        "cam_reconcile", "lease_renewal", "rent_increase", "amenity_plan", "property_ops",
        "maintenance_re", "vendor_re", "insurance_re", "tax_appeal_note", "zoning_note",
        "entitlement_plan", "construction_draw", "punch_list", "hoa_rules_summary", "neighborhood_report",
        "school_district_note", "commute_analysis", "market_update_re", "flyer_copy", "email_drip_re",
        "referral_re", "agent_bio", "re_weekly", "re_playbook", "re_custom",
    ]),
    ("18_healthcare", "ops", "hc", "Healthcare ops", [
        "patient_comms", "appointment_remind", "no_show_reduce", "intake_form_help", "referral_process",
        "care_pathway", "discharge_summary_help", "medication_reconcile_note", "prior_auth_packet", "appeal_letter",
        "coding_query", "denial_management", "billing_explain", "eligibility_check_note", "hipaa_checklist",
        "privacy_incident_hc", "quality_measure", "hcahps_improve", "staffing_hc", "credentialing_note",
        "provider_onboard", "clinic_schedule", "or_block_time", "supply_clinical", "formulary_note",
        "telehealth_script", "triage_protocol", "escalation_clinical", "infection_control_note", "emergency_plan_hc",
        "emr_workflow", "interop_note", "patient_portal_copy", "education_material", "consent_plain_language",
        "research_recruit", "irb_checklist", "clinical_trial_note", "population_health", "risk_stratify",
        "value_based_care", "aco_report_note", "payer_contract_note", "medical_policy_summary", "guideline_digest",
        "cme_plan", "hc_weekly", "hc_playbook", "hc_compliance", "hc_custom",
    ]),
    ("19_education", "hr", "edu", "Education & training", [
        "curriculum_outline", "lesson_plan", "learning_objectives", "quiz_bank", "rubric_edu",
        "syllabus", "workshop_agenda", "bootcamp_plan", "onboarding_edu", "microlearning",
        "video_lesson_script", "slide_outline_edu", "handout", "case_method", "discussion_prompt",
        "facilitator_guide", "student_feedback", "grade_explain", "accommodation_plan", "accessibility_edu",
        "lms_structure", "badge_design", "certification_path", "assessment_blueprint", "item_analysis",
        "cohort_plan", "mentorship_program", "office_hours_edu", "parent_comms", "student_success",
        "at_risk_student", "tutoring_plan", "lab_safety", "field_trip_plan", "guest_speaker",
        "research_proposal_edu", "thesis_outline", "citation_help", "plagiarism_policy", "ai_use_policy_edu",
        "faculty_dev", "peer_review_edu", "program_review", "accreditation_note", "catalog_entry",
        "marketing_program", "alumni_comms", "edu_weekly", "edu_playbook", "edu_custom",
    ]),
    ("20_executive", "ops", "exec", "Executive & strategy", [
        "strategy_memo", "okr_set", "okr_review", "board_deck_outline", "board_minutes_help",
        "investor_update", "fundraising_narrative", "pitch_deck_outline", "market_sizing", "tam_sam_som",
        "competitive_strategy", "porter_five", "swot", "pestle", "scenario_strategy",
        "m_and_a_thesis", "diligence_list", "integration_plan_exec", "org_redesign", "operating_cadence",
        "exec_comms", "all_hands_script", "crisis_comms_exec", "media_statement", "policy_position",
        "government_affairs", "partnership_strategy", "pricing_strategy_exec", "geo_expansion", "product_portfolio",
        "capital_allocation", "budget_guidance", "hiring_plan_exec", "culture_memo", "values_refresh",
        "risk_appetite", "enterprise_risk", "audit_committee_note", "esg_report_outline", "sustainability_strategy",
        "customer_advisory", "analyst_day", "ipo_readiness", "exit_strategy", "succession_exec",
        "ceo_letter", "weekly_ceo_note", "exec_dashboard", "exec_weekly", "exec_custom",
    ]),
]


def titleize(slug: str, domain_label: str) -> str:
    words = slug.replace("_", " ").strip()
    # prettier short titles
    return words[:1].upper() + words[1:] if words else domain_label


def desc_for(slug: str, domain_label: str) -> str:
    nice = slug.replace("_", " ")
    return (
        f"Execute the {domain_label} skill '{nice}': produce a complete, usable deliverable "
        f"with clear structure, recommendations, and next actions."
    )


def args_for(slug: str) -> list[str]:
    base = ["context", "goal", "audience", "constraints"]
    if any(x in slug for x in ("email", "comms", "reply", "script", "letter")):
        return ["recipient", "tone", "key_points", "cta"]
    if any(x in slug for x in ("plan", "roadmap", "calendar", "agenda")):
        return ["period", "goals", "owners", "constraints"]
    if any(x in slug for x in ("report", "analysis", "review", "audit")):
        return ["data", "period", "focus", "audience"]
    if any(x in slug for x in ("checklist", "runbook", "sop")):
        return ["process", "systems", "owners"]
    return base


def build_domain_pack(pack_id: str, category: str, prefix: str, label: str, slugs: list[str]) -> list[dict]:
    skills = []
    for i, slug in enumerate(slugs[:50], 1):
        sid = f"{prefix}_{slug}" if not slug.startswith(prefix) else slug
        # ensure unique prefix
        if not sid.startswith(prefix + "_") and not sid.startswith(prefix):
            sid = f"{prefix}_{slug}"
        skills.append(
            _skill(
                sid,
                titleize(slug, label),
                desc_for(slug, label),
                args_for(slug),
                ALL_ROLES if i % 7 != 0 else LEAD_ROLES,
                category,
                False,
                0,
                pack_id,
            )
        )
    # pad
    while len(skills) < 50:
        n = len(skills) + 1
        sid = f"{prefix}_extra_{n:02d}"
        skills.append(
            _skill(
                sid,
                f"{label} extra skill {n}",
                f"Additional {label} deliverable skill #{n}.",
                ["context", "goal"],
                ALL_ROLES,
                category,
                False,
                0,
                pack_id,
            )
        )
    return skills[:50]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_skills = []
    index = []

    # Packs 1-2 handcrafted
    for pack_id, meta in PACKS.items():
        skills = expand_pack_to_50(pack_id, meta["category"], meta["skills"])
        path = OUT / f"{pack_id}.json"
        path.write_text(json.dumps({"pack": pack_id, "category": meta["category"], "label": meta["label"], "skills": skills}, indent=2), encoding="utf-8")
        all_skills.extend(skills)
        index.append({"pack": pack_id, "file": path.name, "count": len(skills), "category": meta["category"]})
        print(f"Wrote {path.name}: {len(skills)}")

    # Packs 3-20 domain specs
    for pack_id, category, prefix, label, slugs in DOMAIN_SPECS:
        skills = build_domain_pack(pack_id, category, prefix, label, slugs)
        path = OUT / f"{pack_id}.json"
        path.write_text(json.dumps({"pack": pack_id, "category": category, "label": label, "skills": skills}, indent=2), encoding="utf-8")
        all_skills.extend(skills)
        index.append({"pack": pack_id, "file": path.name, "count": len(skills), "category": category})
        print(f"Wrote {path.name}: {len(skills)}")

    # Master catalog + id uniqueness check
    ids = [s["id"] for s in all_skills]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    master = {
        "total": len(all_skills),
        "unique": len(set(ids)),
        "duplicates": dupes,
        "packs": index,
        "skills": all_skills,
    }
    master_path = OUT / "MEGA_CATALOG.json"
    master_path.write_text(json.dumps(master, indent=2), encoding="utf-8")

    # Compact list for humans
    list_path = OUT / "SKILL_LIST_1000.md"
    lines = [f"# Skill list ({len(all_skills)} skills, {len(set(ids))} unique)", ""]
    for p in index:
        lines.append(f"## {p['pack']} ({p['count']})")
        for s in all_skills:
            if s.get("pack") == p["pack"]:
                lines.append(f"- `{s['id']}` — {s['name']}")
        lines.append("")
    list_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"TOTAL={len(all_skills)} UNIQUE={len(set(ids))} DUPES={len(dupes)}")
    if dupes:
        print("DUPLICATES:", dupes[:20])
    print(f"Master: {master_path}")


if __name__ == "__main__":
    main()
