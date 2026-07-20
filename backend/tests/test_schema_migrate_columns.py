"""Guardrails: critical runtime columns must stay in schema_migrate.COLUMN_ADDS."""
from __future__ import annotations


def _col_map(table: str) -> dict[str, str]:
    from app.schema_migrate import COLUMN_ADDS

    return {name: decl for name, decl in COLUMN_ADDS.get(table, [])}


def test_column_adds_agents_permission_level():
    cols = _col_map("agents")
    assert "permission_level" in cols
    assert "operator" in cols["permission_level"] or "TEXT" in cols["permission_level"].upper()


def test_column_adds_tasks_human_id():
    cols = _col_map("tasks")
    assert "human_id" in cols
    assert "INTEGER" in cols["human_id"].upper()


def test_column_adds_tasks_assignee_type():
    cols = _col_map("tasks")
    assert "assignee_type" in cols


def test_column_adds_customers_lead_fields():
    """Sales AI lead qualification columns on customers."""
    cols = _col_map("customers")
    for name in (
        "lead_status",
        "lead_score",
        "qualified_at",
        "budget",
        "company_size",
        "linkedin_url",
        "icp_notes",
        "disqualified_reason",
    ):
        assert name in cols, f"customers.{name} missing from COLUMN_ADDS"


def test_customer_model_has_lead_columns():
    from app.models import Customer

    model_cols = {c.name for c in Customer.__table__.columns}
    for name in (
        "lead_status",
        "lead_score",
        "qualified_at",
        "budget",
        "company_size",
        "linkedin_url",
        "icp_notes",
        "disqualified_reason",
    ):
        assert name in model_cols, f"Customer.{name} missing from models.py"


def test_column_adds_workspace_settings():
    """Autonomy settings table must be patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import WorkspaceSettings

    assert "workspace_settings" in COLUMN_ADDS
    cols = _col_map("workspace_settings")
    for name in (
        "user_id",
        "autonomy_enabled",
        "autonomy_interval_sec",
        "task_stuck_minutes",
        "last_autonomy_run",
        "last_autonomy_summary",
        "policy_json",
        "updated_at",
        "created_at",
    ):
        assert name in cols, f"workspace_settings.{name} missing from COLUMN_ADDS"
    model_cols = {c.name for c in WorkspaceSettings.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_column_adds_escalation_logs():
    """Escalation audit trail must be patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import EscalationLog

    assert "escalation_logs" in COLUMN_ADDS
    cols = _col_map("escalation_logs")
    for name in (
        "user_id",
        "task_id",
        "from_agent_id",
        "from_human_id",
        "to_agent_id",
        "to_human_id",
        "reason_code",
        "reason_text",
        "status",
        "created_at",
    ):
        assert name in cols, f"escalation_logs.{name} missing from COLUMN_ADDS"
    model_cols = {c.name for c in EscalationLog.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_column_adds_knowledge_files():
    """Training library files must be fully patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import KnowledgeFile

    assert "knowledge_files" in COLUMN_ADDS
    cols = _col_map("knowledge_files")
    for name in (
        "user_id",
        "folder_id",
        "name",
        "description",
        "tags",
        "kind",
        "storage",
        "storage_path",
        "connection_id",
        "mime_type",
        "size_bytes",
        "content_text",
        "status",
        "created_at",
        "updated_at",
    ):
        assert name in cols, f"knowledge_files.{name} missing from COLUMN_ADDS"
    assert "INTEGER" in cols["user_id"].upper()
    model_cols = {c.name for c in KnowledgeFile.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_column_adds_knowledge_folders():
    """Training library folders must be patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import KnowledgeFolder

    assert "knowledge_folders" in COLUMN_ADDS
    cols = _col_map("knowledge_folders")
    for name in ("user_id", "parent_id", "name", "description", "created_at"):
        assert name in cols, f"knowledge_folders.{name} missing from COLUMN_ADDS"
    model_cols = {c.name for c in KnowledgeFolder.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_column_adds_agent_knowledge_access():
    """Agent training ACL must be patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import AgentKnowledgeAccess

    assert "agent_knowledge_access" in COLUMN_ADDS
    cols = _col_map("agent_knowledge_access")
    for name in ("agent_id", "resource_type", "resource_id", "permission", "created_at"):
        assert name in cols, f"agent_knowledge_access.{name} missing from COLUMN_ADDS"
    model_cols = {c.name for c in AgentKnowledgeAccess.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_column_adds_agent_skill_states():
    """Per-agent skill enablement must be patchable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS
    from app.models import AgentSkillState

    assert "agent_skill_states" in COLUMN_ADDS
    cols = _col_map("agent_skill_states")
    for name in ("agent_id", "enabled_json", "updated_at"):
        assert name in cols, f"agent_skill_states.{name} missing from COLUMN_ADDS"
    assert "INTEGER" in cols["agent_id"].upper()
    model_cols = {c.name for c in AgentSkillState.__table__.columns} - {"id"}
    assert model_cols <= set(cols), f"model cols not in COLUMN_ADDS: {sorted(model_cols - set(cols))}"


def test_critical_cols_include_market_leading_fields():
    """Runtime re-check list must cover hierarchy, human tasks, CRM leads, knowledge."""
    from app.schema_migrate import CRITICAL_COLS

    assert "permission_level" in CRITICAL_COLS["agents"]
    assert "human_id" in CRITICAL_COLS["tasks"]
    assert "assignee_type" in CRITICAL_COLS["tasks"]
    for name in (
        "lead_status",
        "lead_score",
        "qualified_at",
        "budget",
        "company_size",
        "linkedin_url",
        "icp_notes",
        "disqualified_reason",
    ):
        assert name in CRITICAL_COLS["customers"], f"CRITICAL_COLS.customers missing {name}"
    assert "user_id" in CRITICAL_COLS["knowledge_files"]
    assert "storage" in CRITICAL_COLS["knowledge_files"]
    assert "agent_id" in CRITICAL_COLS["agent_knowledge_access"]


def test_column_adds_never_drop_only_add():
    """Sanity: COLUMN_ADDS entries are (name, type) pairs for ADD COLUMN only."""
    from app.schema_migrate import COLUMN_ADDS

    for table, cols in COLUMN_ADDS.items():
        assert isinstance(cols, list), table
        for entry in cols:
            assert isinstance(entry, tuple) and len(entry) == 2, f"{table}: {entry!r}"
            name, decl = entry
            assert name and isinstance(name, str) and " " not in name
            assert decl and isinstance(decl, str)
            upper = decl.upper()
            assert "DROP" not in upper
            assert "RENAME" not in upper


def test_products_image_url_media_related():
    """Product catalog image_url is the only media-related persisted column (no media assets table)."""
    cols = _col_map("products")
    assert "image_url" in cols


# ── Market-leading CRM / auth / hierarchy schema paths ──────────────────────

def test_column_adds_users_auth_and_plan():
    """Auth + billing fields on users must migrate on older DBs.

    Trial is plan='trial' (no separate trial_* column) + subscription_expires_at.
    """
    cols = _col_map("users")
    for name in (
        "subscription_active",
        "subscription_expires_at",
        "plan",
        "role",
        "token_version",
        "email_verified",
        "twofa_enabled",
        "api_key_hash",
        "api_key_prefix",
        "created_at",
    ):
        assert name in cols, f"users.{name} missing from COLUMN_ADDS"
    # plan default documents inactive workspace until choose_plan / trial
    assert "none" in cols["plan"] or "TEXT" in cols["plan"].upper()


def test_column_adds_agents_hierarchy():
    """Multi-agent hierarchy + escalation columns on agents."""
    cols = _col_map("agents")
    for name in (
        "parent_id",
        "hierarchy_role",
        "is_lead",
        "permission_level",
        "escalate_when",
        "escalate_to",
        "escalate_human_id",
        "company_id",
        "project_id",
        "config",
        "model",
        "status",
    ):
        assert name in cols, f"agents.{name} missing from COLUMN_ADDS"


def test_column_adds_tasks_chain_and_acceptance():
    """Task chain + review acceptance columns for multi-agent goals."""
    cols = _col_map("tasks")
    for name in (
        "parent_task_id",
        "acceptance_json",
        "labels",
        "priority",
        "user_id",
        "agent_id",
        "meeting_id",
        "status",
        "result",
    ):
        assert name in cols, f"tasks.{name} missing from COLUMN_ADDS"


def test_column_adds_deals_and_pipelines_crm():
    """CRM board tables (deals + pipelines) remain patchable."""
    deals = _col_map("deals")
    for name in (
        "owner_user_id",
        "pipeline_id",
        "stage_id",
        "customer_id",
        "title",
        "value",
        "status",
        "priority",
        "lost_reason",
        "created_at",
        "closed_at",
    ):
        assert name in deals, f"deals.{name} missing from COLUMN_ADDS"

    pipes = _col_map("pipelines")
    for name in ("owner_user_id", "name", "kind", "is_default"):
        assert name in pipes, f"pipelines.{name} missing from COLUMN_ADDS"


def test_critical_cols_billing_and_lead_status():
    """Billing gates + lead_status must stay in CRITICAL_COLS post-migrate re-check."""
    from app.schema_migrate import CRITICAL_COLS, INDEX_HINTS

    users = CRITICAL_COLS["users"]
    assert "plan" in users
    assert "subscription_active" in users
    assert "subscription_expires_at" in users
    assert "lead_status" in CRITICAL_COLS["customers"]
    assert "created_at" in CRITICAL_COLS["deals"]
    # Index documentation for lead_status (model index=True; not auto-ALTERed)
    assert "lead_status" in INDEX_HINTS["customers"]


def test_column_adds_products_catalogue():
    """Business products catalogue columns for sales offers."""
    cols = _col_map("products")
    for name in (
        "owner_user_id",
        "name",
        "sku",
        "price",
        "currency",
        "status",
        "offer",
        "tags",
    ):
        assert name in cols, f"products.{name} missing from COLUMN_ADDS"


def test_deal_and_pipeline_models_match_column_adds():
    """SQLAlchemy CRM models stay aligned with COLUMN_ADDS (minus PK)."""
    from app.models import Deal, Pipeline, Product

    for model, table in (
        (Deal, "deals"),
        (Pipeline, "pipelines"),
        (Product, "products"),
    ):
        cols = set(_col_map(table))
        model_cols = {c.name for c in model.__table__.columns} - {"id"}
        missing = model_cols - cols
        assert not missing, f"{table}: model cols not in COLUMN_ADDS: {sorted(missing)}"


def test_customers_ownership_and_contact_columns():
    """Customer ownership FKs + contact fields for multi-tenant CRM."""
    cols = _col_map("customers")
    for name in (
        "owner_user_id",
        "owner_agent_id",
        "owner_human_id",
        "name",
        "email",
        "phone",
        "status",
        "tags",
        "notes",
        "last_contacted_at",
    ):
        assert name in cols, f"customers.{name} missing from COLUMN_ADDS"


def test_meeting_tables_in_column_adds():
    """Multi-agent meeting rooms stack is migratable on older DBs."""
    from app.schema_migrate import COLUMN_ADDS

    for table, required in (
        ("meeting_rooms", ("user_id", "title", "status", "chair_agent_id")),
        ("meeting_participants", ("room_id", "kind", "agent_id", "role")),
        ("meeting_messages", ("room_id", "content", "sender_kind", "created_at")),
    ):
        assert table in COLUMN_ADDS
        cols = _col_map(table)
        for name in required:
            assert name in cols, f"{table}.{name} missing from COLUMN_ADDS"


def test_ensure_schema_idempotent_sqlite():
    """ensure_schema is safe on fresh in-memory SQLite (cold-start path)."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.pool import StaticPool
    from app.schema_migrate import ensure_schema

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        report1 = ensure_schema(engine)
        assert report1.get("created_tables") is True
        assert not report1.get("errors"), report1.get("errors")
        report2 = ensure_schema(engine)
        assert not report2.get("errors"), report2.get("errors")
        assert not report2.get("critical_missing"), report2.get("critical_missing")
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        for need in (
            "users",
            "agents",
            "tasks",
            "customers",
            "deals",
            "pipelines",
            "products",
            "workspace_settings",
            "knowledge_files",
            "knowledge_folders",
        ):
            assert need in tables, f"ensure_schema did not create {need}"
        cust_cols = {c["name"] for c in insp.get_columns("customers")}
        for name in ("lead_status", "lead_score", "qualified_at", "created_at"):
            assert name in cust_cols
        user_cols = {c["name"] for c in insp.get_columns("users")}
        for name in ("plan", "subscription_active", "subscription_expires_at"):
            assert name in user_cols
        deal_cols = {c["name"] for c in insp.get_columns("deals")}
        assert "created_at" in deal_cols
    finally:
        engine.dispose()


def test_column_adds_covers_critical_runtime_tables():
    """Market tables must all appear in COLUMN_ADDS map."""
    from app.schema_migrate import COLUMN_ADDS

    required_tables = {
        "users",
        "agents",
        "tasks",
        "customers",
        "deals",
        "pipelines",
        "pipeline_stages",
        "products",
        "customer_activities",
        "workspace_settings",
        "escalation_logs",
        "agent_skill_states",
        "knowledge_files",
        "meeting_rooms",
        "balances",
    }
    missing = required_tables - set(COLUMN_ADDS)
    assert not missing, f"COLUMN_ADDS missing tables: {sorted(missing)}"
