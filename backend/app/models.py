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
    # Hierarchy: lead agents have hierarchy_role="lead"; members report via parent_id
    parent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    hierarchy_role = Column(String, default="member")  # lead | member | specialist
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
    """Tasks under a project (optionally run by an agent)."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
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
