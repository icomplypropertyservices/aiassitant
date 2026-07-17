from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean
from .database import Base


class User(Base):
    """Subscriber account (the person who pays / owns the workspace)."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")  # user | admin
    # none = must pick plan; trial | starter | pro | business | pay_as_you_go
    plan = Column(String, default="none")
    subscription_active = Column(Boolean, default=False)
    # When set, access ends after this UTC time (null = no time limit while active)
    subscription_expires_at = Column(DateTime, nullable=True)
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
    title = Column(String, default="")
    description = Column(Text)
    result = Column(Text, default="")
    status = Column(String, default="queued")  # todo | queued | in_progress | review | completed | failed
    priority = Column(String, default="medium")  # low | medium | high | urgent
    labels = Column(String, default="")  # comma-separated
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
    name = Column(String, nullable=False)
    role_title = Column(String, default="")  # e.g. Sales Manager
    skills = Column(Text, default="")  # free text / tags
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    # active | away | offline
    status = Column(String, default="active")
    capacity = Column(Integer, default=5)  # open work items preferred max
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    owner_human_id = Column(Integer, ForeignKey("humans.id"), nullable=True, index=True)
    owner_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    annual_value = Column(Float, default=0.0)
    notes = Column(Text, default="")
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
