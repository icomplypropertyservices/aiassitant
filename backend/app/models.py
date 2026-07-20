from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, ForeignKey, Boolean
from .database import Base


class User(Base):
    """Subscriber account (the person who pays / owns the workspace)."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    # Bumped on password change/reset so existing JWTs (claim "tv") become invalid
    token_version = Column(Integer, default=0, nullable=False)
    role = Column(String, default="user")  # user | admin
    # none = inactive; new registers get trial via auth.register → _activate_plan
    # trial | starter | pro | business | pay_as_you_go
    plan = Column(String, default="none")
    subscription_active = Column(Boolean, default=False)
    # When set, access ends after this UTC time (null = no time limit while active).
    # Free trial stamps a 14-day window on register / choose_plan(trial).
    subscription_expires_at = Column(DateTime, nullable=True)
    # Email ownership confirmed via /auth/verify-email (admins/dev seed may start True)
    email_verified = Column(Boolean, default=False)
    # Email-based two-factor auth (OTP to registered email on login)
    twofa_enabled = Column(Boolean, default=False)
    # Session API key (aba_…) — preferred auth site-wide (no JWT for sessions)
    api_key_hash = Column(String, nullable=True, index=True)
    api_key_prefix = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailToken(Base):
    """One-time tokens for email verification and password reset (unified)."""
    __tablename__ = "email_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # verify | reset
    purpose = Column(String, nullable=False, index=True, default="verify")
    # SHA-256 hex of the raw token sent to the user (never store raw token)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    """Dedicated password-reset tokens (optional; EmailToken.purpose=reset also works)."""
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailVerificationToken(Base):
    """Dedicated email-verify tokens (optional; EmailToken.purpose=verify also works)."""
    __tablename__ = "email_verification_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Balance(Base):
    __tablename__ = "balances"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    credits = Column(Float, default=0.0)  # USD wallet for overage / PAYG
    # Monthly token pool (included in plan)
    tokens_included = Column(Integer, default=0)
    tokens_used_period = Column(Integer, default=0)
    period_start = Column(DateTime, default=datetime.utcnow)
    # Auto top-up (wallet) — fires checkout when credits/tokens low
    auto_topup_enabled = Column(Boolean, default=False)
    auto_topup_amount = Column(Float, default=25.0)  # USD per top-up
    auto_topup_threshold_credits = Column(Float, default=5.0)  # when credits below this
    auto_topup_token_pct = Column(Integer, default=85)  # when usage_percent >= this
    auto_topup_last_at = Column(DateTime, nullable=True)
    # Permanent training-library storage purchased via storage add-ons (bytes).
    # BIGINT: multi-GB packs exceed signed int32 on Postgres.
    storage_bonus_bytes = Column(BigInteger, default=0)


class Company(Base):
    """Companies owned by a subscriber."""
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String, nullable=False)
    industry = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """Projects live under a company."""
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="active")  # active | paused | done
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    type = Column(String)
    description = Column(Text)
    unique_fields = Column(Text, default="[]")
    est_cost = Column(String, default="~$0.50 / day")


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    # Hierarchy: orchestrator (top) | lead | member | specialist; members report via parent_id
    parent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    hierarchy_role = Column(String, default="member")  # orchestrator | lead | member | specialist
    is_lead = Column(Boolean, default=False)
    name = Column(String)
    template_type = Column(String)
    personality = Column(Text, default="Professional, friendly and concise.")
    model = Column(String, default="vps-fast")
    status = Column(String, default="active")
    idle_mode = Column(String, default="allow_idle")
    # Permission: viewer | operator | lead | admin
    permission_level = Column(String, default="operator")
    # When to escalate: never | on_failure | on_blocked | high_priority | sla_breach |
    # customer_vip | value_threshold | always_review | custom
    escalate_when = Column(String, default="on_failure")
    escalate_reason = Column(Text, default="")  # free-text / custom rule detail
    # parent | orchestrator | human | owner
    escalate_to = Column(String, default="parent")
    escalate_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    config = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    title = Column(String, default="New conversation")
    mode = Column(String, default="general")
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class TokenUsage(Base):
    __tablename__ = "token_usage"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    model = Column(String)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    bill_source = Column(String, default="included")  # included | credits
    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    """Tasks under a project (optionally run by an agent or assigned to a human)."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    # When set, work is allocated to a human teammate (agents may still assist)
    human_id = Column(Integer, ForeignKey("humans.id"), nullable=True, index=True)
    # agent | human | unassigned
    assignee_type = Column(String, default="agent")
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    # Task DAG + meeting origin
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    # use_alter: circular with MeetingRoom.task_id → tasks.id; constraint via ALTER after both tables exist
    meeting_id = Column(
        Integer,
        ForeignKey("meeting_rooms.id", use_alter=True, name="fk_tasks_meeting_id"),
        nullable=True,
        index=True,
    )
    title = Column(String, default="")
    description = Column(Text)
    result = Column(Text, default="")
    status = Column(String, default="queued")  # todo | queued | in_progress | review | completed | failed
    priority = Column(String, default="medium")  # low | medium | high | urgent
    labels = Column(String, default="")  # comma-separated
    # Structured acceptance: done_when, checklist, check statuses (JSON)
    acceptance_json = Column(Text, default="{}")
    tokens_used = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True)
    type = Column(String, default="info")
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserApiKey(Base):
    """Subscriber-owned API keys. Value is Fernet-encrypted at rest; never return plaintext via API."""
    __tablename__ = "user_api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # anthropic | xai | openai | google | resend | twilio_sid | twilio_token | custom
    provider = Column(String, nullable=False, index=True)
    label = Column(String, default="")  # optional display name
    encrypted_value = Column(Text, nullable=False)
    # last 4 chars for UI mask verification (not secret)
    hint = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntegrationConnection(Base):
    """Third-party app connection (Shopify, Google, Slack, etc.) for a subscriber."""
    __tablename__ = "integration_connections"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # Catalog id: shopify | google | google_business | gmail | sheets | slack | hubspot | ...
    app_id = Column(String, nullable=False, index=True)
    display_name = Column(String, default="")
    # disconnected | pending | connected | error
    status = Column(String, default="disconnected", index=True)
    # oauth | api_key | both
    auth_mode = Column(String, default="api_key")
    # Encrypted JSON blob: tokens, api keys, shop domain, etc.
    encrypted_secrets = Column(Text, default="")
    # Non-secret metadata JSON: shop domain, account email, scopes, expires_at hint
    meta_json = Column(Text, default="{}")
    # Last successful test / error message (safe for UI)
    last_error = Column(Text, default="")
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentIntegration(Base):
    """Which agents may use a given app connection."""
    __tablename__ = "agent_integrations"
    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("integration_connections.id"), index=True, nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    # read | write | full
    permission = Column(String, default="full")


class StripeCheckout(Base):
    """Idempotency record for fulfilled Stripe Checkout sessions."""
    __tablename__ = "stripe_checkouts"
    id = Column(Integer, primary_key=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    kind = Column(String, default="")  # plan | topup
    plan = Column(String, default="")
    amount_usd = Column(Float, default=0.0)
    mode = Column(String, default="")  # test | live
    created_at = Column(DateTime, default=datetime.utcnow)


class CryptoInvoice(Base):
    """Crypto payment invoice (ETH / SOL / XRP) for plan subscription or credit top-up."""
    __tablename__ = "crypto_invoices"
    id = Column(Integer, primary_key=True)
    public_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # eth | sol | xrp
    chain = Column(String, nullable=False, index=True)
    # plan | topup
    kind = Column(String, nullable=False, default="plan")
    plan = Column(String, default="")  # plan id when kind=plan
    company_name = Column(String, default="")
    amount_usd = Column(Float, default=0.0)
    amount_crypto = Column(Float, default=0.0)  # exact amount user should send
    asset_symbol = Column(String, default="")  # ETH | SOL | XRP
    receive_address = Column(String, nullable=False)
    dest_tag = Column(Integer, nullable=True)  # XRP destination tag
    # pending | paid | expired | cancelled
    status = Column(String, default="pending", index=True)
    tx_hash = Column(String, default="", index=True)
    expires_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class KnowledgeFolder(Base):
    """Training library folders (user-scoped)."""
    __tablename__ = "knowledge_folders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    parent_id = Column(Integer, ForeignKey("knowledge_folders.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class KnowledgeFile(Base):
    """Training files / notes stored locally or on cloud (GCS / Dropbox)."""
    __tablename__ = "knowledge_files"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    folder_id = Column(Integer, ForeignKey("knowledge_folders.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    tags = Column(String, default="")  # comma-separated
    # note | upload | cloud
    kind = Column(String, default="upload")
    # local | gcs | dropbox
    storage = Column(String, default="local")
    storage_path = Column(String, default="")
    connection_id = Column(Integer, ForeignKey("integration_connections.id"), nullable=True)
    mime_type = Column(String, default="text/plain")
    size_bytes = Column(Integer, default=0)
    content_text = Column(Text, default="")
    # draft | ready | archived
    status = Column(String, default="ready")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentKnowledgeAccess(Base):
    """Which agents may read which training files or whole folders."""
    __tablename__ = "agent_knowledge_access"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    # file | folder | all
    resource_type = Column(String, default="file", nullable=False)
    resource_id = Column(Integer, nullable=True, index=True)
    permission = Column(String, default="read")
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentProgram(Base):
    """Standing instructions + allowed apps/files policy for an agent."""
    __tablename__ = "agent_programs"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, nullable=False, index=True)
    instructions = Column(Text, default="")
    # {"allow_all_files": false, "allow_all_apps": false, "max_file_chars": 12000}
    policy_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class Human(Base):
    """Human teammates who can receive allocated work from agents/orchestrator."""
    __tablename__ = "humans"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    email = Column(String, default="")
    # E.164 phone for SMS notify shortcuts (Twilio)
    phone = Column(String, default="")
    name = Column(String, nullable=False)
    role_title = Column(String, default="")  # e.g. Sales Manager
    skills = Column(Text, default="")  # free text / tags
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    # active | away | offline
    status = Column(String, default="active")
    capacity = Column(Integer, default=5)  # open work items preferred max
    # Permission: viewer | operator | lead | admin
    permission_level = Column(String, default="operator")
    # When to escalate / re-escalate their work
    escalate_when = Column(String, default="on_blocked")
    escalate_reason = Column(Text, default="")
    # parent | orchestrator | human | owner
    escalate_to = Column(String, default="orchestrator")
    notes = Column(Text, default="")
    # Exactly one "My Human" per account (primary operator who delegates with agents)
    is_my_human = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HumanMessage(Base):
    """Message box for a human teammate (owner, agents, and the human themselves)."""
    __tablename__ = "human_messages"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    human_id = Column(Integer, ForeignKey("humans.id"), index=True, nullable=False)
    # owner | agent | human | system
    sender_role = Column(String, default="owner", index=True)
    sender_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    # Optional peer human when My Human delegates / threads with another human
    related_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    # Optional linked task for delegation threads
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    content = Column(Text, default="")
    # message | task_delegate | status | system
    kind = Column(String, default="message")
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WorkspaceSettings(Base):
    """Per-subscriber automation / self-running system settings."""
    __tablename__ = "workspace_settings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    # When true, autonomy loop processes tasks, escalations, idle agents
    autonomy_enabled = Column(Boolean, default=True)
    # Seconds between local loop ticks (serverless uses cron/tick endpoint)
    autonomy_interval_sec = Column(Integer, default=45)
    # Minutes a task may stay in_progress before escalate
    task_stuck_minutes = Column(Integer, default=30)
    last_autonomy_run = Column(DateTime, nullable=True)
    last_autonomy_summary = Column(Text, default="")
    # JSON extras
    policy_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class EscalationLog(Base):
    """Record of escalations between agents / humans / owner."""
    __tablename__ = "escalation_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    from_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    from_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    to_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    to_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    # failure | blocked | high_priority | sla | vip | value | review | custom | autonomy
    reason_code = Column(String, default="custom")
    reason_text = Column(Text, default="")
    status = Column(String, default="open")  # open | acknowledged | resolved
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentMemory(Base):
    """Structured data agents save for themselves (facts, CRM notes, deliverables)."""
    __tablename__ = "agent_memories"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # note | fact | deliverable | training_candidate | crm | other
    kind = Column(String, default="note")
    title = Column(String, default="")
    content = Column(Text, default="")
    tags = Column(String, default="")
    # optional link when promoted into training library
    knowledge_file_id = Column(Integer, ForeignKey("knowledge_files.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentMessage(Base):
    """Agent-to-agent conversation messages."""
    __tablename__ = "agent_messages"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    from_agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    to_agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    # thread key = min(id)-max(id) pair or explicit thread id
    thread_key = Column(String, index=True, default="")
    content = Column(Text, default="")
    status = Column(String, default="sent")  # sent | delivered | read | failed
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class PlatformSetting(Base):
    """
    Global staff settings (fleet connection, model map, etc.).
    Survives Vercel cold starts when DATABASE_URL is Postgres.
    """
    __tablename__ = "platform_settings"
    key = Column(String, primary_key=True)
    value = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String, default="")  # admin email


class DevicePushToken(Base):
    """Mobile device tokens for push notifications (FCM / APNs via Capacitor)."""
    __tablename__ = "device_push_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(String, nullable=False, index=True)
    platform = Column(String, default="")  # ios | android | web
    device_label = Column(String, default="")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    # open | acknowledged | closed
    status = Column(String, default="open")
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveOpsEvent(Base):
    """Real-time plan/action stream for the live banner + ops visual."""
    __tablename__ = "live_ops_events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # plan | step | action | skill | agent | human | app | system
    kind = Column(String, default="action", index=True)
    # queued | running | done | failed | info
    status = Column(String, default="info")
    title = Column(String, default="")
    detail = Column(Text, default="")
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    human_id = Column(Integer, ForeignKey("humans.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    plan_id = Column(String, default="", index=True)  # groups steps
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentSkillState(Base):
    """Per-agent enabled skills (JSON list). Missing row = all default skills enabled."""
    __tablename__ = "agent_skill_states"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, nullable=False, index=True)
    # JSON list of skill ids enabled
    enabled_json = Column(Text, default="[]")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreatedSkill(Base):
    """
    Skills invented by agents (or the owner) for this workspace.

    skill_key is the runtime id (e.g. custom_42_outreach_playbook).
    Agents can share privately (workspace) or list for sale on AgentBay.
    """
    __tablename__ = "created_skills"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # Creator agent (who invented it)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=True)
    skill_key = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    # JSON list of arg names
    args_json = Column(Text, default="[]")
    # Standing instructions / prompt for deliverable execution
    instructions = Column(Text, default="")
    category = Column(String, default="custom")
    # draft | active | archived
    status = Column(String, default="active", index=True)
    # Shared with all agents in this workspace
    shared = Column(Boolean, default=True)
    # Listed for sale on AgentBay
    listed_on_bay = Column(Boolean, default=False, index=True)
    list_price = Column(Float, default=29.0)
    bay_listing_id = Column(Integer, nullable=True)
    bay_external_id = Column(String, default="")
    bay_url = Column(String, default="")
    # times used / sold (bookkeeping)
    use_count = Column(Integer, default=0)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Business CRM ──────────────────────────────────────────────────────────

class Pipeline(Base):
    """Sales / delivery pipeline (kanban board)."""
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    # sales | support | onboarding | custom
    kind = Column(String, default="sales")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    # open | won | lost
    stage_type = Column(String, default="open")
    color = Column(String, default="#1668dc")
    position = Column(Integer, default=0)
    probability = Column(Integer, default=0)  # 0-100 win likelihood


class Customer(Base):
    """Customer / contact / account record."""
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    # Person
    name = Column(String, nullable=False)
    email = Column(String, default="", index=True)
    phone = Column(String, default="")
    job_title = Column(String, default="")
    # Organisation they represent
    account_name = Column(String, default="")
    website = Column(String, default="")
    industry = Column(String, default="")
    address = Column(Text, default="")
    city = Column(String, default="")
    country = Column(String, default="")
    # CRM fields
    status = Column(String, default="active")  # active | inactive | churned
    source = Column(String, default="")  # website | referral | cold | import | agent
    tags = Column(String, default="")  # comma-separated
    # Lead qualification (sales AI)
    # new | contacted | nurturing | qualified | disqualified | converted
    lead_status = Column(String, default="", index=True)
    lead_score = Column(Float, default=0.0)
    qualified_at = Column(DateTime, nullable=True)
    # ICP / qualification enrichment
    budget = Column(Float, default=0.0)  # stated or estimated deal budget (USD)
    company_size = Column(String, default="")  # e.g. 1-10 | 11-50 | enterprise
    linkedin_url = Column(String, default="")
    icp_notes = Column(Text, default="")  # fit notes vs ideal customer profile
    disqualified_reason = Column(Text, default="")
    owner_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True, index=True)
    owner_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    annual_value = Column(Float, default=0.0)
    notes = Column(Text, default="")
    # e.g. shopify / woocommerce external key for two-way sync
    external_source = Column(String, default="", index=True)
    external_id = Column(String, default="", index=True)
    meta_json = Column(Text, default="{}")
    last_contacted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Deal(Base):
    """Opportunity sitting in a pipeline stage, linked to a customer."""
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), index=True, nullable=False)
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    value = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    # open | won | lost
    status = Column(String, default="open", index=True)
    priority = Column(String, default="medium")
    expected_close = Column(DateTime, nullable=True)
    owner_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    owner_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    position = Column(Integer, default=0)
    description = Column(Text, default="")
    lost_reason = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class CustomerActivity(Base):
    """Notes, calls, emails, stage changes on a customer."""
    __tablename__ = "customer_activities"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # note | call | email | meeting | stage | deal | system
    kind = Column(String, default="note")
    title = Column(String, default="")
    body = Column(Text, default="")
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    """Sellable product / service / SKU owned by the subscriber, linked to a company."""
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    sku = Column(String, default="", index=True)
    description = Column(Text, default="")
    # product | service | digital | subscription | other
    kind = Column(String, default="product")
    price = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    # active | draft | archived
    status = Column(String, default="active", index=True)
    tags = Column(String, default="")  # comma-separated
    benefits = Column(Text, default="")
    audience = Column(String, default="")
    offer = Column(String, default="")
    image_url = Column(String, default="")
    # e.g. shopify product id for two-way sync
    external_source = Column(String, default="", index=True)
    external_id = Column(String, default="", index=True)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Diary / Appointments (arrange diaries for customers) ─────────────────

class DiaryEntry(Base):
    """Scheduled meetings, calls, site visits, follow-ups for customers."""
    __tablename__ = "diary_entries"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True, nullable=False)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    # ISO datetime strings or real datetimes
    start_at = Column(DateTime, nullable=True)
    end_at = Column(DateTime, nullable=True)
    location = Column(String, default="")
    notes = Column(Text, default="")
    # scheduled | completed | cancelled | no_show
    status = Column(String, default="scheduled")
    # Who owns / runs this appointment
    owner_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    owner_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


# ── Meeting rooms (multi-party human + agent brainstorm) ───────────────────

class MeetingRoom(Base):
    """Shared brainstorm / war-room thread for humans + agents about a task or topic."""
    __tablename__ = "meeting_rooms"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    title = Column(String, default="Meeting")
    purpose = Column(Text, default="")
    # brainstorm | task_war_room | standup | review
    room_type = Column(String, default="brainstorm", index=True)
    # open | active | closed
    status = Column(String, default="open", index=True)
    chair_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    settings_json = Column(Text, default="{}")
    summary_text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class MeetingParticipant(Base):
    """Who is in a meeting room (user / agent / human)."""
    __tablename__ = "meeting_participants"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("meeting_rooms.id"), index=True, nullable=False)
    # user | agent | human
    kind = Column(String, default="agent", index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    human_id = Column(Integer, ForeignKey("humans.id"), nullable=True, index=True)
    # chair | member | observer
    role = Column(String, default="member")
    last_read_at = Column(DateTime, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)


class MeetingMessage(Base):
    """One message in a meeting room thread."""
    __tablename__ = "meeting_messages"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("meeting_rooms.id"), index=True, nullable=False)
    # user | agent | human | system
    sender_kind = Column(String, default="user", index=True)
    sender_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    sender_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True)
    content = Column(Text, default="")
    # chat | decision | task_created | system
    msg_type = Column(String, default="chat")
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Agent CLI / crypto wallets / git / local machines ─────────────────────

class AgentWallet(Base):
    """Per-agent multi-chain crypto wallet + platform credit slice."""
    __tablename__ = "agent_wallets"
    id = Column(Integer, primary_key=True)
    public_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    # Platform credits attributed to this agent (USD)
    credits_usd = Column(Float, default=0.0)
    # On-chain linked or generated addresses
    eth_address = Column(String, default="")
    sol_address = Column(String, default="")
    btc_address = Column(String, default="")
    xrp_address = Column(String, default="")
    xrp_dest_tag = Column(Integer, nullable=True)
    # Encrypted JSON of private material (optional custodial keys) — never returned raw
    encrypted_keys = Column(Text, default="")
    # Virtual chain balances (bookkeeping; on-chain verified separately)
    bal_eth = Column(Float, default=0.0)
    bal_sol = Column(Float, default=0.0)
    bal_btc = Column(Float, default=0.0)
    bal_xrp = Column(Float, default=0.0)
    label = Column(String, default="")
    status = Column(String, default="active")  # active | frozen | archived
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentWalletTx(Base):
    """Ledger for agent wallet movements."""
    __tablename__ = "agent_wallet_txs"
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey("agent_wallets.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # deposit | withdraw | transfer_in | transfer_out | skill_spend | topup | adjust
    kind = Column(String, default="adjust", index=True)
    asset = Column(String, default="usd")  # usd | eth | sol | btc | xrp
    amount = Column(Float, default=0.0)
    balance_after = Column(Float, default=0.0)
    counterparty_wallet_id = Column(Integer, nullable=True)
    tx_hash = Column(String, default="", index=True)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class GitRepoConnection(Base):
    """Connected git repository for agents (GitHub / GitLab / local path)."""
    __tablename__ = "git_repo_connections"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    # github | gitlab | bitbucket | local
    provider = Column(String, default="github", index=True)
    name = Column(String, nullable=False)
    full_name = Column(String, default="")  # owner/repo
    clone_url = Column(String, default="")
    html_url = Column(String, default="")
    default_branch = Column(String, default="main")
    local_path = Column(String, default="")  # absolute path on machine node
    machine_id = Column(Integer, ForeignKey("machine_nodes.id"), nullable=True, index=True)
    # Encrypted PAT / deploy key material
    encrypted_token = Column(Text, default="")
    token_hint = Column(String, default="")
    scopes = Column(String, default="")
    status = Column(String, default="connected")  # connected | error | revoked
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MachineNode(Base):
    """Registered local / remote machine visible to orchestrator and CLI."""
    __tablename__ = "machine_nodes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    public_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    # local | remote | ci | laptop | server
    kind = Column(String, default="local")
    hostname = Column(String, default="")
    os_name = Column(String, default="")
    arch = Column(String, default="")
    # agent-reported status
    status = Column(String, default="online")  # online | offline | unknown
    agent_version = Column(String, default="")
    # Encrypted JSON snapshot from last heartbeat
    snapshot_json = Column(Text, default="{}")
    labels = Column(String, default="")  # comma tags
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
