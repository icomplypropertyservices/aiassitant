"""
Agent CLI + workspace API:
- Orchestrator bootstrap (3 companies)
- Agent wallets (crypto)
- Git repos
- Local machines
- CLI helpers (list agents, run skill, status)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth_utils import get_current_user
from ..agent_serialize import agent_out
from ..agent_hierarchy import build_hierarchy_payload, ensure_main_orchestrator
from ..agent_wallets import (
    get_or_create_wallet,
    wallet_out,
    credit_usd,
    transfer_usd,
    link_address,
    export_keys_once,
    CHAINS,
)
from ..git_workspace import (
    connect_github_repo,
    connect_local_repo,
    list_repos,
    repo_out,
    github_list_user_repos,
)
from ..local_machine import (
    register_or_heartbeat,
    list_machines,
    machine_out,
    collect_local_snapshot,
)
from ..orchestrator_bootstrap import bootstrap_workspace, DEFAULT_COMPANIES
from ..usage_billing import meter_snapshot

router = APIRouter(prefix="/cli", tags=["cli"])


# ── Status / bootstrap ────────────────────────────────────────────────────


@router.get("/status")
def cli_status(db: Session = Depends(get_db), user=Depends(get_current_user)):
    meter = meter_snapshot(db, user)
    cos = db.query(models.Company).filter_by(owner_user_id=user.id).count()
    agents = db.query(models.Agent).filter_by(user_id=user.id).count()
    repos = db.query(models.GitRepoConnection).filter_by(user_id=user.id).count()
    machines = db.query(models.MachineNode).filter_by(user_id=user.id).count()
    wallets = db.query(models.AgentWallet).filter_by(user_id=user.id).count()
    hier = build_hierarchy_payload(db, user.id)
    return {
        "ok": True,
        "user": {"id": user.id, "email": user.email, "name": user.name, "plan": user.plan},
        "meter": meter,
        "counts": {
            "companies": cos,
            "agents": agents,
            "repos": repos,
            "machines": machines,
            "wallets": wallets,
        },
        "orchestrator": hier.get("orchestrator"),
        "guidance_companies": [c["name"] for c in DEFAULT_COMPANIES],
        "cli": {
            "commands": [
                "aba login",
                "aba status",
                "aba bootstrap",
                "aba agents",
                "aba wallets",
                "aba git list|connect|local",
                "aba machine register|list",
            ],
        },
    }


@router.post("/bootstrap")
def cli_bootstrap(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Orchestrator sets up the 3 guided companies + leads + wallets."""
    if not user.subscription_active and user.role != "admin":
        raise HTTPException(402, "Active subscription required")
    return bootstrap_workspace(db, user)


@router.get("/guidance")
def cli_guidance(user=Depends(get_current_user)):
    return {
        "companies": DEFAULT_COMPANIES,
        "summary": (
            "Main Orchestrator coordinates Fire Alarms Dublin, iComply Property Services, "
            "and iComply Products. Connect GitHub repos and register your local machine via CLI."
        ),
    }


@router.get("/agents")
def cli_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    agents = (
        db.query(models.Agent)
        .filter_by(user_id=user.id)
        .order_by(models.Agent.id)
        .all()
    )
    return [agent_out(a, db) for a in agents]


@router.post("/ensure-orchestrator")
def cli_ensure_orch(db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = ensure_main_orchestrator(db, user)
    return agent_out(a, db, include_team=True)


# ── Wallets ───────────────────────────────────────────────────────────────


class WalletCreditIn(BaseModel):
    amount_usd: float = Field(..., gt=0, le=100_000)
    note: str = ""


class WalletTransferIn(BaseModel):
    to_agent_id: int
    amount_usd: float = Field(..., gt=0)
    note: str = ""


class WalletLinkIn(BaseModel):
    chain: str
    address: str


@router.get("/wallets")
def cli_wallets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(models.AgentWallet).filter_by(user_id=user.id).order_by(models.AgentWallet.id).all()
    return [wallet_out(w) for w in rows]


@router.post("/wallets/ensure/{agent_id}")
def cli_wallet_ensure(agent_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    w = get_or_create_wallet(db, user, a)
    return wallet_out(w)


@router.post("/wallets/{agent_id}/credit")
def cli_wallet_credit(
    agent_id: int,
    data: WalletCreditIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    # Move from user platform wallet if available
    bal = db.query(models.Balance).filter_by(user_id=user.id).first()
    if not bal or float(bal.credits or 0) < data.amount_usd:
        raise HTTPException(400, "Insufficient platform wallet credits — top up on Billing first")
    bal.credits = round(float(bal.credits or 0) - data.amount_usd, 4)
    w = get_or_create_wallet(db, user, a)
    w = credit_usd(db, w, data.amount_usd, note=data.note or "From platform wallet")
    db.commit()
    return {"ok": True, "wallet": wallet_out(w), "platform_credits": round(bal.credits, 4)}


@router.post("/wallets/{agent_id}/transfer")
def cli_wallet_transfer(
    agent_id: int,
    data: WalletTransferIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    b = db.get(models.Agent, data.to_agent_id)
    if not a or a.user_id != user.id or not b or b.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    wa = get_or_create_wallet(db, user, a)
    wb = get_or_create_wallet(db, user, b)
    try:
        wa, wb = transfer_usd(db, wa, wb, data.amount_usd, note=data.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "from": wallet_out(wa), "to": wallet_out(wb)}


@router.post("/wallets/{agent_id}/link-address")
def cli_wallet_link(
    agent_id: int,
    data: WalletLinkIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    w = get_or_create_wallet(db, user, a)
    try:
        w = link_address(db, w, data.chain, data.address)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return wallet_out(w)


@router.get("/wallets/{agent_id}/export-keys")
def cli_wallet_export_keys(
    agent_id: int,
    confirm: str = Query("", description="Must be EXPORT"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if confirm != "EXPORT":
        raise HTTPException(400, "Pass confirm=EXPORT to reveal encrypted key material")
    a = db.get(models.Agent, agent_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Agent not found")
    w = get_or_create_wallet(db, user, a)
    keys = export_keys_once(db, w)
    return {"agent_id": agent_id, "wallet_id": w.id, "keys": keys, "warning": "Store offline. Never commit secrets."}


@router.get("/wallets/chains")
def cli_wallet_chains(user=Depends(get_current_user)):
    return {"chains": list(CHAINS)}


# ── Git ───────────────────────────────────────────────────────────────────


class GitHubConnectIn(BaseModel):
    full_name: str = Field(..., description="owner/repo")
    token: str = Field(..., min_length=8)
    company_id: int | None = None
    agent_id: int | None = None
    local_path: str = ""
    machine_id: int | None = None


class LocalRepoIn(BaseModel):
    name: str
    local_path: str
    machine_id: int | None = None
    company_id: int | None = None
    agent_id: int | None = None
    default_branch: str = "main"


class GitHubListIn(BaseModel):
    token: str
    limit: int = 30


@router.get("/git/repos")
def cli_git_list(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [repo_out(r) for r in list_repos(db, user.id)]


@router.post("/git/connect/github")
def cli_git_github(data: GitHubConnectIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        row = connect_github_repo(
            db,
            user,
            full_name=data.full_name,
            token=data.token,
            company_id=data.company_id,
            agent_id=data.agent_id,
            local_path=data.local_path,
            machine_id=data.machine_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return repo_out(row)


@router.post("/git/connect/local")
def cli_git_local(data: LocalRepoIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        row = connect_local_repo(
            db,
            user,
            name=data.name,
            local_path=data.local_path,
            machine_id=data.machine_id,
            company_id=data.company_id,
            agent_id=data.agent_id,
            default_branch=data.default_branch,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return repo_out(row)


@router.post("/git/github/list")
def cli_git_github_list(data: GitHubListIn, user=Depends(get_current_user)):
    try:
        return {"repos": github_list_user_repos(data.token, limit=data.limit)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/git/repos/{repo_id}")
def cli_git_delete(repo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.get(models.GitRepoConnection, repo_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Repo not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Machines ──────────────────────────────────────────────────────────────


class MachineRegisterIn(BaseModel):
    name: str | None = None
    kind: str = "local"
    public_id: str | None = None
    labels: str = ""
    agent_version: str = "cli-1.0"
    snapshot: dict | None = None


@router.get("/machines")
def cli_machines(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [machine_out(m) for m in list_machines(db, user.id)]


@router.post("/machines/register")
def cli_machine_register(
    data: MachineRegisterIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # If no snapshot provided, capture server-side (API host); CLI should send client snapshot
    snap = data.snapshot
    m = register_or_heartbeat(
        db,
        user,
        name=data.name,
        kind=data.kind,
        public_id=data.public_id,
        snapshot=snap,
        labels=data.labels,
        agent_version=data.agent_version,
    )
    return machine_out(m)


@router.get("/machines/local-snapshot")
def cli_local_snapshot(user=Depends(get_current_user)):
    """Snapshot of the API host (Vercel = limited). Prefer CLI for real laptop."""
    return collect_local_snapshot()


@router.get("/machines/{machine_id}")
def cli_machine_get(machine_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    m = db.get(models.MachineNode, machine_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Machine not found")
    return machine_out(m)
