"""Catalog of connectable third-party apps (OAuth + API key).

All apps with fields and/or oauth are connectable:
  - OAuth 1-click when platform client env vars are set (oauth_ready)
  - API key / token connect always available when auth_modes includes api_key
  - coming_soon=True only for apps that are intentionally not wired yet
"""

# Preferred order in Connected apps UI (Google family first, then comms, then rest)
OAUTH_ONE_CLICK_ORDER = [
    "google",
    "gmail",
    "google_sheets",
    "google_business",
    "youtube",
    "twilio",
    "slack",
    "x",
    "linkedin",
    "meta",
    "instagram",
    "shopify",
    "hubspot",
    "notion",
    "dropbox",
    "microsoft",
    "tiktok",
]

GOOGLE_FAMILY = frozenset({
    "google", "gmail", "google_sheets", "google_business", "youtube",
})

# Each app:
#   id, name, category, description, auth_modes, fields (for API connect),
#   oauth (optional env client ids), scopes, coming_soon, family

INTEGRATION_APPS = {
    "shopify": {
        "id": "shopify",
        "name": "Shopify",
        "category": "commerce",
        "description": "Products, orders, customers, and storefront data for sales & ops agents.",
        "auth_modes": ["api_key", "oauth"],
        "color": "#96bf48",
        "docs_url": "https://shopify.dev/docs/api/admin-rest",
        "fields": [
            {"name": "shop_domain", "label": "Shop domain", "placeholder": "your-store.myshopify.com", "secret": False, "required": True},
            {"name": "access_token", "label": "Admin API access token", "placeholder": "shpat_…", "secret": True, "required": True},
            {"name": "api_version", "label": "API version (optional)", "placeholder": "2024-10", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://{shop}/admin/oauth/authorize",
            "token_url": "https://{shop}/admin/oauth/access_token",
            "client_id_env": "SHOPIFY_CLIENT_ID",
            "client_secret_env": "SHOPIFY_CLIENT_SECRET",
            "scopes": (
                "read_products,write_products,read_orders,write_orders,"
                "read_customers,write_customers,read_fulfillments,write_fulfillments"
            ),
            "needs_shop": True,
        },
        "agent_capabilities": [
            "List products & customers with tags",
            "Sync Shopify catalogue into Business CRM (company-linked)",
            "Update product/customer tags",
            "Summarise orders",
            "Fulfill orders",
        ],
    },
    "google": {
        "id": "google",
        "name": "Google (Workspace)",
        "category": "productivity",
        "description": "One-click Google sign-in: profile, Calendar, and Drive context for agents.",
        "auth_modes": ["oauth"],
        "color": "#4285F4",
        "docs_url": "https://console.cloud.google.com/",
        "family": "google",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [
            {"name": "api_key", "label": "Google API key (optional extras)", "placeholder": "AIza…", "secret": True, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
            "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
            "scopes": "openid email profile https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/drive.readonly",
            "needs_shop": False,
            "access_type": "offline",
            "prompt": "consent",
        },
        "agent_capabilities": ["Read calendar context", "Summarise Drive docs", "Confirm Google identity"],
    },
    "gmail": {
        "id": "gmail",
        "name": "Gmail",
        "category": "communication",
        "description": "One-click Gmail for send, draft, and inbox summaries.",
        "auth_modes": ["oauth"],
        "color": "#EA4335",
        "docs_url": "https://developers.google.com/gmail/api",
        "family": "google",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [
            {"name": "from_email", "label": "From address (optional)", "placeholder": "you@company.com", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
            "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
            # gmail.modify covers send + read + draft + reply + archive/labels
            "scopes": (
                "openid email profile "
                "https://www.googleapis.com/auth/gmail.modify "
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.compose"
            ),
            "needs_shop": False,
            "access_type": "offline",
            "prompt": "consent",
        },
        "agent_capabilities": [
            "Send email (To / Cc / Bcc)",
            "Read inbox and search",
            "Reply to threads",
            "Create drafts",
            "Archive messages",
        ],
    },
    "google_sheets": {
        "id": "google_sheets",
        "name": "Google Sheets",
        "category": "productivity",
        "description": "One-click Sheets for ops tables and reporting agents.",
        "auth_modes": ["oauth"],
        "color": "#0F9D58",
        "docs_url": "https://developers.google.com/sheets/api",
        "family": "google",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [
            {"name": "spreadsheet_id", "label": "Default spreadsheet ID (optional)", "placeholder": "1BxiM…", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
            "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
            "scopes": "openid email profile https://www.googleapis.com/auth/spreadsheets",
            "needs_shop": False,
            "access_type": "offline",
            "prompt": "consent",
        },
        "agent_capabilities": ["Read rows", "Append rows", "Build reports from sheet data"],
    },
    "google_business": {
        "id": "google_business",
        "name": "Google Business Profile",
        "category": "reviews",
        "description": "One-click Business Profile for reviews and local replies.",
        "auth_modes": ["oauth"],
        "color": "#34A853",
        "docs_url": "https://developers.google.com/my-business",
        "family": "google",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [
            {"name": "account_id", "label": "Account / location ID (optional)", "placeholder": "accounts/123/locations/456", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
            "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
            "scopes": "openid email profile https://www.googleapis.com/auth/business.manage",
            "needs_shop": False,
            "access_type": "offline",
            "prompt": "consent",
        },
        "agent_capabilities": ["List reviews", "Draft review replies", "Flag low ratings"],
    },
    "twilio": {
        "id": "twilio",
        "name": "Twilio",
        "category": "communication",
        "description": (
            "SMS, WhatsApp, and voice calls for agents. "
            "Use your own Account SID / Auth Token / From number, or rely on platform TWILIO_* env."
        ),
        "auth_modes": ["api_key"],
        "color": "#F22F46",
        "docs_url": "https://www.twilio.com/docs",
        "coming_soon": False,
        "one_click_oauth": False,
        "fields": [
            {
                "name": "twilio_sid",
                "label": "Account SID",
                "placeholder": "ACxxxxxxxx",
                "secret": True,
                "required": True,
            },
            {
                "name": "twilio_token",
                "label": "Auth Token",
                "placeholder": "your auth token",
                "secret": True,
                "required": True,
            },
            {
                "name": "twilio_from",
                "label": "From number (E.164)",
                "placeholder": "+15551234567",
                "secret": False,
                "required": True,
            },
            {
                "name": "twilio_whatsapp_from",
                "label": "WhatsApp From (optional)",
                "placeholder": "whatsapp:+14155238886",
                "secret": False,
                "required": False,
            },
        ],
        "oauth": None,
        "agent_capabilities": [
            "Send SMS (send_sms / initiate_text)",
            "WhatsApp messages (send_whatsapp)",
            "Outbound voice with TTS (make_voice_call)",
            "Notify humans on escalation",
        ],
    },
    "slack": {
        "id": "slack",
        "name": "Slack",
        "category": "communication",
        "description": "Post updates and alerts into Slack channels.",
        "auth_modes": ["api_key", "oauth"],
        "color": "#4A154B",
        "docs_url": "https://api.slack.com/apps",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [
            {"name": "bot_token", "label": "Bot user OAuth token", "placeholder": "xoxb-…", "secret": True, "required": True},
            {"name": "default_channel", "label": "Default channel", "placeholder": "#ops", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://slack.com/oauth/v2/authorize",
            "token_url": "https://slack.com/api/oauth.v2.access",
            "client_id_env": "SLACK_CLIENT_ID",
            "client_secret_env": "SLACK_CLIENT_SECRET",
            "scopes": "chat:write,channels:read,channels:history,groups:read,im:write,users:read",
            "needs_shop": False,
        },
        "agent_capabilities": ["Post channel messages", "Notify on task completion"],
    },
    "hubspot": {
        "id": "hubspot",
        "name": "HubSpot",
        "category": "crm",
        "description": "CRM contacts, deals, and pipeline context for sales agents.",
        "auth_modes": ["api_key", "oauth"],
        "color": "#FF7A59",
        "docs_url": "https://developers.hubspot.com/",
        "fields": [
            {"name": "access_token", "label": "Private app access token", "placeholder": "pat-…", "secret": True, "required": True},
            {"name": "portal_id", "label": "Portal ID (optional)", "placeholder": "12345678", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://app.hubspot.com/oauth/authorize",
            "token_url": "https://api.hubapi.com/oauth/v1/token",
            "client_id_env": "HUBSPOT_CLIENT_ID",
            "client_secret_env": "HUBSPOT_CLIENT_SECRET",
            "scopes": "crm.objects.contacts.read crm.objects.deals.read",
            "needs_shop": False,
        },
        "agent_capabilities": ["Lookup contacts", "Summarise deals", "Draft follow-ups"],
    },
    "stripe_connect": {
        "id": "stripe_connect",
        "name": "Stripe (your account)",
        "category": "payments",
        "description": "Your Stripe account for payment/ops agents (separate from platform billing).",
        "auth_modes": ["api_key"],
        "color": "#635BFF",
        "docs_url": "https://dashboard.stripe.com/apikeys",
        "fields": [
            {"name": "secret_key", "label": "Secret key", "placeholder": "sk_live_… or sk_test_…", "secret": True, "required": True},
            {"name": "publishable_key", "label": "Publishable key (optional)", "placeholder": "pk_…", "secret": False, "required": False},
        ],
        "oauth": None,
        "agent_capabilities": ["List recent charges", "Summarise revenue", "Flag failed payments"],
    },
    "woocommerce": {
        "id": "woocommerce",
        "name": "WooCommerce",
        "category": "commerce",
        "description": "WordPress store orders and products.",
        "auth_modes": ["api_key"],
        "color": "#96588A",
        "docs_url": "https://woocommerce.github.io/woocommerce-rest-api-docs/",
        "fields": [
            {"name": "store_url", "label": "Store URL", "placeholder": "https://shop.example.com", "secret": False, "required": True},
            {"name": "consumer_key", "label": "Consumer key", "placeholder": "ck_…", "secret": True, "required": True},
            {"name": "consumer_secret", "label": "Consumer secret", "placeholder": "cs_…", "secret": True, "required": True},
        ],
        "oauth": None,
        "agent_capabilities": ["List orders", "Product summaries", "Customer order lookups"],
    },
    "mailchimp": {
        "id": "mailchimp",
        "name": "Mailchimp",
        "category": "marketing",
        "description": "Email campaigns and audience lists for marketing agents.",
        "auth_modes": ["api_key"],
        "color": "#FFE01B",
        "docs_url": "https://mailchimp.com/developer/",
        "fields": [
            {"name": "api_key", "label": "API key", "placeholder": "xxxx-us21", "secret": True, "required": True},
            {"name": "server_prefix", "label": "Server prefix", "placeholder": "us21", "secret": False, "required": False},
        ],
        "oauth": None,
        "agent_capabilities": ["List audiences", "Draft campaign copy", "Summarise list growth"],
    },
    "zapier": {
        "id": "zapier",
        "name": "Zapier / Webhooks",
        "category": "automation",
        "description": "Outbound webhooks so agents can trigger Zaps and custom automations.",
        "auth_modes": ["api_key"],
        "color": "#FF4A00",
        "docs_url": "https://zapier.com/apps/webhook/integrations",
        "fields": [
            {"name": "webhook_url", "label": "Catch Hook URL", "placeholder": "https://hooks.zapier.com/hooks/catch/…", "secret": True, "required": True},
        ],
        "oauth": None,
        "agent_capabilities": ["Fire webhook with JSON payload", "Trigger multi-step automations"],
    },
    "notion": {
        "id": "notion",
        "name": "Notion",
        "category": "productivity",
        "description": "Pages and databases for knowledge & ops agents.",
        "auth_modes": ["api_key", "oauth"],
        "color": "#000000",
        "docs_url": "https://developers.notion.com/",
        "fields": [
            {"name": "integration_token", "label": "Internal integration token", "placeholder": "secret_… or ntn_…", "secret": True, "required": True},
            {"name": "default_database_id", "label": "Default database ID", "placeholder": "uuid", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://api.notion.com/v1/oauth/authorize",
            "token_url": "https://api.notion.com/v1/oauth/token",
            "client_id_env": "NOTION_CLIENT_ID",
            "client_secret_env": "NOTION_CLIENT_SECRET",
            "scopes": "",
            "needs_shop": False,
        },
        "agent_capabilities": ["Search pages", "Create task pages", "Summarise databases"],
    },
    "dropbox": {
        "id": "dropbox",
        "name": "Dropbox",
        "category": "storage",
        "description": "Store and train agents on files from your Dropbox (Training library).",
        "auth_modes": ["api_key", "oauth"],
        "color": "#0061FF",
        "docs_url": "https://www.dropbox.com/developers",
        "fields": [
            {"name": "access_token", "label": "Access token", "placeholder": "sl.B…", "secret": True, "required": True},
            {"name": "root_path", "label": "Training root path", "placeholder": "/AI-Training", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://www.dropbox.com/oauth2/authorize",
            "token_url": "https://api.dropboxapi.com/oauth2/token",
            "client_id_env": "DROPBOX_APP_KEY",
            "client_secret_env": "DROPBOX_APP_SECRET",
            "scopes": "",
            "needs_shop": False,
        },
        "agent_capabilities": ["Read training files", "Import docs into library", "Store agent deliverables"],
    },
    "google_cloud_storage": {
        "id": "google_cloud_storage",
        "name": "Google Cloud Storage",
        "category": "storage",
        "description": "Bucket storage for training files and agent knowledge (GCS).",
        "auth_modes": ["api_key"],
        "color": "#4285F4",
        "docs_url": "https://cloud.google.com/storage/docs",
        "fields": [
            {"name": "bucket", "label": "Bucket name", "placeholder": "my-training-bucket", "secret": False, "required": True},
            {"name": "prefix", "label": "Object prefix (folder)", "placeholder": "ai-training", "secret": False, "required": False},
            {"name": "access_token", "label": "OAuth access token (optional)", "placeholder": "ya29.…", "secret": True, "required": False},
            {"name": "client_email", "label": "Service account email", "placeholder": "sa@project.iam.gserviceaccount.com", "secret": False, "required": False},
            {"name": "private_key", "label": "Service account private key", "placeholder": "-----BEGIN PRIVATE KEY-----", "secret": True, "required": False},
            {"name": "service_account_json", "label": "Full service account JSON (optional)", "placeholder": "{ \"type\": \"service_account\", … }", "secret": True, "required": False},
        ],
        "oauth": None,
        "agent_capabilities": ["Read training objects", "Upload knowledge files", "Browse bucket prefixes"],
    },
    # ── Socials ──────────────────────────────────────────────────────────
    "x": {
        "id": "x",
        "name": "X (Twitter)",
        "category": "social",
        "description": "Post updates and read profile via X API v2.",
        "auth_modes": ["oauth", "api_key"],
        "color": "#000000",
        "docs_url": "https://developer.x.com/",
        "fields": [
            {"name": "bearer_token", "label": "Bearer token (app)", "placeholder": "AAAA…", "secret": True, "required": False},
            {"name": "access_token", "label": "User access token (OAuth 2)", "placeholder": "…", "secret": True, "required": False},
            {"name": "access_token_secret", "label": "Token secret (OAuth 1 optional)", "placeholder": "…", "secret": True, "required": False},
            {"name": "api_key", "label": "API key", "placeholder": "…", "secret": True, "required": False},
            {"name": "api_secret", "label": "API secret", "placeholder": "…", "secret": True, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://twitter.com/i/oauth2/authorize",
            "token_url": "https://api.twitter.com/2/oauth2/token",
            "client_id_env": "X_CLIENT_ID",
            "client_secret_env": "X_CLIENT_SECRET",
            "scopes": "tweet.read tweet.write users.read offline.access",
            "needs_shop": False,
        },
        "agent_capabilities": ["Post tweets", "Check account", "Draft social copy"],
    },
    "linkedin": {
        "id": "linkedin",
        "name": "LinkedIn",
        "category": "social",
        "description": "Company and personal LinkedIn posts for marketing agents.",
        "auth_modes": ["oauth", "api_key"],
        "color": "#0A66C2",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/",
        "fields": [
            {"name": "access_token", "label": "Access token", "placeholder": "…", "secret": True, "required": False},
            {"name": "person_urn", "label": "Person URN (for posts)", "placeholder": "urn:li:person:…", "secret": False, "required": False},
            {"name": "organization_urn", "label": "Org URN (optional)", "placeholder": "urn:li:organization:…", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
            "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
            "client_id_env": "LINKEDIN_CLIENT_ID",
            "client_secret_env": "LINKEDIN_CLIENT_SECRET",
            "scopes": "openid profile email w_member_social",
            "needs_shop": False,
        },
        "agent_capabilities": ["Post updates", "Verify identity", "Draft B2B posts"],
    },
    "meta": {
        "id": "meta",
        "name": "Meta (Facebook Pages)",
        "category": "social",
        "description": "Facebook Pages feed posts and insights.",
        "auth_modes": ["oauth", "api_key"],
        "color": "#1877F2",
        "docs_url": "https://developers.facebook.com/",
        "fields": [
            {"name": "access_token", "label": "User/Page access token", "placeholder": "EAAB…", "secret": True, "required": True},
            {"name": "page_id", "label": "Page ID", "placeholder": "123456789", "secret": False, "required": False},
            {"name": "page_token", "label": "Page token (optional)", "placeholder": "…", "secret": True, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://www.facebook.com/v19.0/dialog/oauth",
            "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
            "client_id_env": "META_APP_ID",
            "client_secret_env": "META_APP_SECRET",
            "scopes": "pages_show_list,pages_manage_posts,pages_read_engagement,public_profile",
            "needs_shop": False,
        },
        "agent_capabilities": ["Post to Page", "Check connection", "Draft social replies"],
    },
    "instagram": {
        "id": "instagram",
        "name": "Instagram",
        "category": "social",
        "description": "Instagram Business account via Meta Graph API.",
        "auth_modes": ["oauth", "api_key"],
        "color": "#E1306C",
        "docs_url": "https://developers.facebook.com/docs/instagram-api/",
        "fields": [
            {"name": "access_token", "label": "Access token", "placeholder": "EAAB…", "secret": True, "required": True},
            {"name": "ig_user_id", "label": "IG business user ID", "placeholder": "1784…", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://www.facebook.com/v19.0/dialog/oauth",
            "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
            "client_id_env": "META_APP_ID",
            "client_secret_env": "META_APP_SECRET",
            "scopes": "instagram_basic,instagram_content_publish,pages_show_list",
            "needs_shop": False,
        },
        "agent_capabilities": ["Check IG account", "Draft captions", "Publish via Graph (media flow)"],
    },
    "youtube": {
        "id": "youtube",
        "name": "YouTube",
        "category": "social",
        "description": "One-click YouTube for channel stats and content planning.",
        "auth_modes": ["oauth"],
        "color": "#FF0000",
        "docs_url": "https://developers.google.com/youtube/v3",
        "family": "google",
        "coming_soon": False,
        "one_click_oauth": True,
        "fields": [],
        "oauth": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
            "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
            # youtube.upload is restricted — start with readonly so connect works for all clients
            "scopes": "openid email profile https://www.googleapis.com/auth/youtube.readonly",
            "needs_shop": False,
            "access_type": "offline",
            "prompt": "consent",
        },
        "agent_capabilities": ["List channels", "Plan video titles", "Read stats"],
    },
    "discord": {
        "id": "discord",
        "name": "Discord",
        "category": "social",
        "description": "Post alerts via Discord webhook or bot.",
        "auth_modes": ["api_key"],
        "color": "#5865F2",
        "docs_url": "https://discord.com/developers/docs",
        "fields": [
            {"name": "webhook_url", "label": "Webhook URL", "placeholder": "https://discord.com/api/webhooks/…", "secret": True, "required": False},
            {"name": "bot_token", "label": "Bot token (optional)", "placeholder": "…", "secret": True, "required": False},
            {"name": "default_channel_id", "label": "Default channel ID", "placeholder": "…", "secret": False, "required": False},
        ],
        "oauth": None,
        "agent_capabilities": ["Post webhook messages", "Notify team channels"],
    },
    "microsoft": {
        "id": "microsoft",
        "name": "Microsoft 365",
        "category": "productivity",
        "description": "Outlook mail and Graph profile via Microsoft identity.",
        "auth_modes": ["oauth", "api_key"],
        "color": "#00A4EF",
        "docs_url": "https://learn.microsoft.com/en-us/graph/",
        "fields": [
            {"name": "access_token", "label": "Access token", "placeholder": "…", "secret": True, "required": False},
            {"name": "refresh_token", "label": "Refresh token", "placeholder": "…", "secret": True, "required": False},
            {"name": "tenant_id", "label": "Tenant ID", "placeholder": "common", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "client_id_env": "MICROSOFT_CLIENT_ID",
            "client_secret_env": "MICROSOFT_CLIENT_SECRET",
            "scopes": "openid profile email offline_access User.Read Mail.Send Mail.Read",
            "needs_shop": False,
        },
        "agent_capabilities": ["Send Outlook mail", "Read profile", "Coordinate with M365"],
    },
    "tiktok": {
        "id": "tiktok",
        "name": "TikTok",
        "category": "social",
        "description": "TikTok content planning and posting (Login Kit / Content Posting API).",
        "auth_modes": ["oauth", "api_key"],
        "color": "#010101",
        "docs_url": "https://developers.tiktok.com/",
        "fields": [
            {"name": "access_token", "label": "Access token", "placeholder": "…", "secret": True, "required": False},
            {"name": "open_id", "label": "Open ID", "placeholder": "…", "secret": False, "required": False},
        ],
        "oauth": {
            "authorize_url": "https://www.tiktok.com/v2/auth/authorize/",
            "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
            "client_id_env": "TIKTOK_CLIENT_KEY",
            "client_secret_env": "TIKTOK_CLIENT_SECRET",
            "scopes": "user.info.basic,video.list,video.upload",
            "needs_shop": False,
        },
        "agent_capabilities": ["Verify account", "Draft short-form scripts", "Plan post calendar"],
    },
}


def _is_coming_soon(app: dict) -> bool:
    """Only explicitly flagged apps are coming soon (default: available)."""
    if "coming_soon" in app:
        return bool(app.get("coming_soon"))
    return False


def _oauth_sort_index(app_id: str) -> int:
    try:
        return OAUTH_ONE_CLICK_ORDER.index(app_id)
    except ValueError:
        return 1000 + hash(app_id) % 100


def list_apps(*, oauth_ready_fn=None) -> list[dict]:
    apps = []
    for a in INTEGRATION_APPS.values():
        ready = None
        if oauth_ready_fn and a.get("oauth"):
            ready = bool(oauth_ready_fn(a))
        apps.append(public_app(a, oauth_ready=ready))
    # Available first (by preferred order), then coming soon by name
    apps.sort(
        key=lambda x: (
            1 if x.get("coming_soon") else 0,
            x.get("oauth_sort", 999),
            x.get("name") or "",
        )
    )
    return apps


def get_app(app_id: str) -> dict | None:
    return INTEGRATION_APPS.get((app_id or "").strip().lower())


def public_app(app: dict, *, oauth_ready: bool | None = None) -> dict:
    """Safe catalog entry for the frontend (no secrets)."""
    oauth = app.get("oauth")
    aid = app["id"]
    coming = _is_coming_soon(app)
    # 1-click when OAuth block exists and not coming soon; UI greys out until oauth_ready
    has_oauth = bool(oauth)
    one_click = (
        not coming
        and has_oauth
        and (
            bool(app.get("one_click_oauth"))
            or aid in GOOGLE_FAMILY
            or app.get("family") == "google"
            or has_oauth
        )
    )
    supports_api = "api_key" in (app.get("auth_modes") or [])
    status = "Coming soon"
    if not coming:
        if oauth_ready:
            status = "1-click OAuth"
        elif supports_api:
            status = "Connect with API key"
        elif has_oauth:
            status = "OAuth (server credentials needed)"
        else:
            status = "Available"
    return {
        "id": aid,
        "name": app["name"],
        "category": app["category"],
        "description": app["description"],
        "auth_modes": list(app.get("auth_modes") or []),
        "color": app.get("color"),
        "docs_url": app.get("docs_url"),
        "family": app.get("family") or ("google" if aid in GOOGLE_FAMILY else None),
        "coming_soon": coming,
        "one_click_oauth": one_click and bool(oauth_ready),
        "oauth_sort": _oauth_sort_index(aid),
        "fields": [
            {
                "name": f["name"],
                "label": f["label"],
                "placeholder": f.get("placeholder", ""),
                "secret": bool(f.get("secret")),
                "required": bool(f.get("required")),
            }
            for f in (app.get("fields") or [])
        ],
        "supports_oauth": has_oauth and not coming,
        "supports_api_key": supports_api and not coming,
        "oauth_ready": False if coming else bool(oauth_ready) if oauth_ready is not None else False,
        "oauth_scopes": (oauth or {}).get("scopes") if oauth else None,
        "oauth_needs_shop": bool((oauth or {}).get("needs_shop")),
        "agent_capabilities": list(app.get("agent_capabilities") or []),
        "status_label": status,
    }


def one_click_oauth_list(*, oauth_ready_fn=None) -> list[dict]:
    """Ordered list of apps that support 1-click OAuth (ready or not)."""
    out = []
    for aid in OAUTH_ONE_CLICK_ORDER:
        app = INTEGRATION_APPS.get(aid)
        if not app or not app.get("oauth"):
            continue
        if _is_coming_soon(app):
            continue
        ready = oauth_ready_fn(app) if oauth_ready_fn else None
        entry = public_app(app, oauth_ready=ready)
        out.append(entry)
    # Also include any other oauth apps not in the preferred order
    seen = {e["id"] for e in out}
    for aid, app in INTEGRATION_APPS.items():
        if aid in seen or not app.get("oauth") or _is_coming_soon(app):
            continue
        ready = oauth_ready_fn(app) if oauth_ready_fn else None
        out.append(public_app(app, oauth_ready=ready))
    return out
