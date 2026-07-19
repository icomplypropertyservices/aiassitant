"""Per-agent crypto + credit wallets."""
from __future__ import annotations

import json
import secrets
import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .crypto import encrypt_secret, decrypt_secret, mask_secret


CHAINS = ("eth", "sol", "btc", "xrp")


def _public_id() -> str:
    return f"wlt_{secrets.token_hex(8)}"


def _gen_eth_address(priv_hex: str) -> str:
    """Deterministic pseudo-address when full crypto libs unavailable (display + ledger)."""
    h = hashlib.sha256(bytes.fromhex(priv_hex)).hexdigest()
    return "0x" + h[:40]


def _gen_sol_address(seed: bytes) -> str:
    # Base58-ish placeholder using hex (real SOL needs solders/ed25519)
    return "sol" + hashlib.sha256(seed).hexdigest()[:40]


def _gen_btc_address(seed: bytes) -> str:
    return "bc1q" + hashlib.sha256(seed + b"btc").hexdigest()[:38]


def _gen_xrp_address(seed: bytes) -> str:
    return "r" + hashlib.sha256(seed + b"xrp").hexdigest()[:24].upper()


def generate_key_material() -> dict[str, Any]:
    priv = secrets.token_hex(32)
    seed = bytes.fromhex(priv)
    return {
        "eth_private_key": priv,
        "eth_address": _gen_eth_address(priv),
        "sol_address": _gen_sol_address(seed),
        "btc_address": _gen_btc_address(seed),
        "xrp_address": _gen_xrp_address(seed),
        "xrp_dest_tag": int(secrets.randbelow(900_000_000) + 100_000),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Custodial material encrypted at rest. Prefer linking hardware/external addresses for large funds.",
    }


def wallet_out(w: models.AgentWallet, *, reveal_hint: bool = True) -> dict:
    return {
        "id": w.id,
        "public_id": w.public_id,
        "agent_id": w.agent_id,
        "company_id": w.company_id,
        "label": w.label or "",
        "status": w.status,
        "credits_usd": round(float(w.credits_usd or 0), 4),
        "addresses": {
            "eth": w.eth_address or "",
            "sol": w.sol_address or "",
            "btc": w.btc_address or "",
            "xrp": w.xrp_address or "",
            "xrp_dest_tag": w.xrp_dest_tag,
        },
        "balances": {
            "eth": float(w.bal_eth or 0),
            "sol": float(w.bal_sol or 0),
            "btc": float(w.bal_btc or 0),
            "xrp": float(w.bal_xrp or 0),
        },
        "has_encrypted_keys": bool(w.encrypted_keys),
        "key_hint": mask_secret("••••keys") if reveal_hint and w.encrypted_keys else None,
        "created_at": w.created_at.isoformat() + "Z" if w.created_at else None,
        "updated_at": w.updated_at.isoformat() + "Z" if w.updated_at else None,
    }


def get_or_create_wallet(
    db: Session,
    user: models.User,
    agent: models.Agent,
    *,
    generate_keys: bool = True,
) -> models.AgentWallet:
    w = db.query(models.AgentWallet).filter_by(agent_id=agent.id).first()
    if w:
        return w
    material = generate_key_material() if generate_keys else {}
    enc = encrypt_secret(json.dumps(material)) if material else ""
    w = models.AgentWallet(
        public_id=_public_id(),
        user_id=user.id,
        agent_id=agent.id,
        company_id=agent.company_id,
        credits_usd=0.0,
        eth_address=material.get("eth_address") or "",
        sol_address=material.get("sol_address") or "",
        btc_address=material.get("btc_address") or "",
        xrp_address=material.get("xrp_address") or "",
        xrp_dest_tag=material.get("xrp_dest_tag"),
        encrypted_keys=enc,
        label=f"{agent.name} wallet",
        status="active",
        meta_json=json.dumps({"source": "auto"}),
    )
    db.add(w)
    db.flush()
    _ledger(
        db, w, user.id, "adjust", "usd", 0.0, 0.0,
        note="Wallet created",
    )
    db.commit()
    db.refresh(w)
    return w


def _ledger(
    db: Session,
    w: models.AgentWallet,
    user_id: int,
    kind: str,
    asset: str,
    amount: float,
    balance_after: float,
    *,
    note: str = "",
    tx_hash: str = "",
    counterparty_wallet_id: int | None = None,
):
    db.add(
        models.AgentWalletTx(
            wallet_id=w.id,
            user_id=user_id,
            kind=kind,
            asset=asset,
            amount=amount,
            balance_after=balance_after,
            counterparty_wallet_id=counterparty_wallet_id,
            tx_hash=tx_hash or "",
            note=note or "",
        )
    )


def credit_usd(db: Session, w: models.AgentWallet, amount: float, note: str = "") -> models.AgentWallet:
    amount = float(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    w.credits_usd = round(float(w.credits_usd or 0) + amount, 4)
    _ledger(db, w, w.user_id, "deposit", "usd", amount, w.credits_usd, note=note)
    db.commit()
    db.refresh(w)
    return w


def transfer_usd(
    db: Session,
    from_w: models.AgentWallet,
    to_w: models.AgentWallet,
    amount: float,
    note: str = "",
) -> tuple[models.AgentWallet, models.AgentWallet]:
    amount = float(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    if float(from_w.credits_usd or 0) < amount:
        raise ValueError("insufficient agent wallet credits")
    from_w.credits_usd = round(float(from_w.credits_usd or 0) - amount, 4)
    to_w.credits_usd = round(float(to_w.credits_usd or 0) + amount, 4)
    _ledger(
        db, from_w, from_w.user_id, "transfer_out", "usd", -amount, from_w.credits_usd,
        note=note, counterparty_wallet_id=to_w.id,
    )
    _ledger(
        db, to_w, to_w.user_id, "transfer_in", "usd", amount, to_w.credits_usd,
        note=note, counterparty_wallet_id=from_w.id,
    )
    db.commit()
    db.refresh(from_w)
    db.refresh(to_w)
    return from_w, to_w


def link_address(db: Session, w: models.AgentWallet, chain: str, address: str) -> models.AgentWallet:
    chain = (chain or "").lower().strip()
    address = (address or "").strip()
    if chain not in CHAINS:
        raise ValueError(f"unsupported chain: {chain}")
    if not address:
        raise ValueError("address required")
    setattr(w, f"{chain}_address", address)
    w.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(w)
    return w


def export_keys_once(db: Session, w: models.AgentWallet) -> dict:
    """Decrypt keys for owner export — CLI only with explicit confirm."""
    if not w.encrypted_keys:
        return {}
    try:
        raw = decrypt_secret(w.encrypted_keys)
        return json.loads(raw) if raw else {}
    except Exception:
        return {"error": "decrypt_failed"}
