# Twilio + Gmail (Google Cloud) — full setup

Agents can **SMS / WhatsApp / voice (Twilio)** and **send / read / reply / Cc / Bcc email (Gmail OAuth or Resend)**.

## Gmail via Google Cloud OAuth (recommended)

### 1. Google Cloud Console
1. Create/select a project at [console.cloud.google.com](https://console.cloud.google.com)
2. Enable **Gmail API**
3. OAuth consent screen (External or Internal)
4. Create **OAuth 2.0 Client ID** (Web application)
5. Authorized redirect URI (production):
   - `https://www.aibusinessagent.xyz/api/integrations/oauth/callback`
   - (and local if needed) `http://127.0.0.1:8000/api/integrations/oauth/callback`

### 2. Platform env (Vercel)
```
GOOGLE_OAUTH_CLIENT_ID=….apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=…
```

### 3. User connects Gmail
**Settings → Connected apps → Gmail → Connect (1-click OAuth)**

Scopes requested (full mailbox work):
- `gmail.modify` (send, draft, reply, archive, labels)
- `gmail.send`, `gmail.readonly`, `gmail.compose`

**Re-connect** if you connected before these scopes were expanded.

### 4. Agent skills
| Skill | What it does |
|--------|----------------|
| `gmail_send` | Send with **to / cc / bcc** |
| `gmail_reply` | Reply / reply-all on thread |
| `gmail_draft` | Create draft (cc/bcc) |
| `gmail_list` | List inbox |
| `gmail_search` | Search (Gmail query syntax) |
| `gmail_get_thread` | Full thread |
| `gmail_archive` | Remove from inbox |
| `send_email` | Prefers Gmail if connected, else Resend |

Allocate the Gmail connection to agents under Connected apps if required by your setup.

---

## Twilio (SMS text + phone speech calls)

Agents can **initiate SMS texts** and **outbound phone calls that speak** a message (Twilio TTS).

### Platform env (Vercel)
```
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_FROM_NUMBER=+15551234567
```
`TWILIO_FROM_NUMBER` must be a Twilio number that supports **SMS** and/or **Voice**.

### Or per-user BYOK (Settings → API keys)
| Key | Value |
|-----|--------|
| `twilio_sid` | Account SID |
| `twilio_token` | Auth Token |
| `twilio_from` | E.164 from number |

User keys override platform env when both exist.

### Skills (agents use these)
| Skill | Action |
|--------|--------|
| `send_sms` / `initiate_text` | **Start SMS** — body is the text message |
| `make_voice_call` / `initiate_call` | **Start phone call** — `message` is spoken with TTS when they answer |
| `send_whatsapp` | WhatsApp text via Twilio |

**Voice call args:** `to`, `message` (speech script), optional `voice` (`alice`/`man`/`woman`), `language` (`en-US`), `loop` (1–3).

Example skill block:
```skill
{"skill":"make_voice_call","to":"+15551234567","message":"Hi, this is your AI assistant. Your appointment is confirmed for tomorrow at 3 PM."}
```
```skill
{"skill":"send_sms","to":"+15551234567","body":"Reminder: appointment tomorrow 3pm."}
```

### WhatsApp notes
- Sandbox: use Twilio WhatsApp sandbox “from” number (`whatsapp:+14155238886` style)
- Optional: set `twilio_whatsapp_from` in credentials for a dedicated WhatsApp sender

---

## Resend (email without Gmail)

```
RESEND_API_KEY=re_…
RESEND_FROM=AI Assistant <noreply@yourdomain.com>
```

Used when Gmail is not connected. Supports **to / cc / bcc**.

---

## Notify human (always SMS + email shortcut)

When agents call **`notify_human`**, **`status_update`** (default), **`escalate_to_human`**, or assign work to a human, the platform **always tries**:

1. **Short SMS** via Twilio (with deep link to `/agents/tasks`)
2. **Email** via **SMTP** (preferred) or Resend

### Requirements
| Requirement | Detail |
|-------------|--------|
| **Active human** | Team human with `status=active` |
| **Email** | Set on human record |
| **Phone** | E.164 on human record (for SMS) |
| **SMTP or Resend** | Platform env (see below) |
| **Twilio** | For SMS shortcuts |

### SMTP env (preferred for notify email)
```
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=…
SMTP_PASSWORD=…
SMTP_FROM=AI Assistant <noreply@yourdomain.com>
SMTP_TLS=1
```
If SMTP is not set, **RESEND_API_KEY** + **RESEND_FROM** are used as fallback.

### Skills
```skill
{"skill":"notify_human","title":"Need approval","message":"Budget request ready","human_id":1}
```
```skill
{"skill":"status_update","project":"Launch","status":"green","highlights":"Ship ready","notify":true}
```

### Notification branding & links
- Email is **HTML** with product **logo + favicon** and a blue **Open notification →** button
- Link always points at the private SPA, e.g.  
  `https://www.aibusinessagent.xyz/agents/tasks`  
  (meetings: `/agents/meetings/123`, agents: `/agents/agents/9`, …)
- SMS includes the same short URL
- Mobile push (if FCM configured) sends `icon` + `path`/`url` so tap opens the right screen

---

## Quick verification checklist

1. Twilio: save keys → agent skill `send_sms` to your phone → SID in result  
2. Gmail: OAuth connect → `gmail_list` → `gmail_send` with cc → appears in Sent  
3. Reply: `gmail_list` → pick `thread_id` / `message_id` → `gmail_reply`  
4. Notify human: active human with email+phone → `notify_human` → SMS + email both fire  

Code paths:
- `backend/app/channels.py` — Twilio + SMTP + Resend
- `backend/app/human_notify.py` — always email+SMS shortcuts
- `backend/app/integration_actions.py` — Gmail API
- `backend/app/agent_skills.py` — skills
- `backend/app/integrations_catalog.py` — OAuth scopes
