"""
Self-custody crypto payments: ETH, SOL, XRP.

Flow
----
1. Create invoice with USD amount → convert via CoinGecko → unique on-chain amount / XRP dest tag
2. User sends to platform receive address
3. User pastes tx hash (or we poll) → verify on public RPC → activate plan / credits

Never store or use private keys. Configure receive addresses only.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from . import config

log = logging.getLogger("crypto_payments")

CHAINS = {
    "eth": {
        "id": "eth",
        "symbol": "ETH",
        "name": "Ethereum",
        "coingecko_id": "ethereum",
        "decimals": 18,
        "explorer_tx": "https://etherscan.io/tx/{tx}",
        "network": "Ethereum mainnet",
    },
    "sol": {
        "id": "sol",
        "symbol": "SOL",
        "name": "Solana",
        "coingecko_id": "solana",
        "decimals": 9,
        "explorer_tx": "https://solscan.io/tx/{tx}",
        "network": "Solana mainnet",
    },
    "xrp": {
        "id": "xrp",
        "symbol": "XRP",
        "name": "XRP Ledger",
        "coingecko_id": "ripple",
        "decimals": 6,
        "explorer_tx": "https://xrpscan.com/tx/{tx}",
        "network": "XRP Ledger mainnet",
    },
}

# Price cache: {symbol: (usd_price, fetched_at)}
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_TTL = 60.0


def crypto_enabled() -> bool:
    return bool(
        config.CRYPTO_ETH_ADDRESS
        or config.CRYPTO_SOL_ADDRESS
        or config.CRYPTO_XRP_ADDRESS
    )


def receive_address(chain: str) -> str:
    chain = (chain or "").lower().strip()
    if chain == "eth":
        return config.CRYPTO_ETH_ADDRESS
    if chain == "sol":
        return config.CRYPTO_SOL_ADDRESS
    if chain == "xrp":
        return config.CRYPTO_XRP_ADDRESS
    return ""


def available_chains() -> list[dict[str, Any]]:
    out = []
    for cid, meta in CHAINS.items():
        addr = receive_address(cid)
        if not addr:
            continue
        out.append({
            **meta,
            "address": addr,
            "configured": True,
        })
    return out


def fetch_usd_prices() -> dict[str, float]:
    """Return {eth, sol, xrp} → USD price. Cached ~60s."""
    now = time.time()
    needed = []
    for cid, meta in CHAINS.items():
        cached = _price_cache.get(cid)
        if not cached or (now - cached[1]) > _PRICE_TTL:
            needed.append(meta["coingecko_id"])
    if needed:
        ids = ",".join(sorted(set(needed)))
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        try:
            with httpx.Client(timeout=12.0) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
            for cid, meta in CHAINS.items():
                row = data.get(meta["coingecko_id"]) or {}
                px = float(row.get("usd") or 0)
                if px > 0:
                    _price_cache[cid] = (px, now)
        except Exception as e:
            log.warning("price fetch failed: %s", e)
            # Fallback static-ish mid prices if API down (invoice still works; amount may be off)
            defaults = {"eth": 3500.0, "sol": 150.0, "xrp": 0.60}
            for cid, px in defaults.items():
                if cid not in _price_cache:
                    _price_cache[cid] = (px, now - _PRICE_TTL + 10)
    return {cid: _price_cache[cid][0] for cid in CHAINS if cid in _price_cache}


def usd_to_crypto(chain: str, amount_usd: float) -> float:
    prices = fetch_usd_prices()
    px = prices.get(chain)
    if not px or px <= 0:
        raise RuntimeError(f"No price available for {chain}")
    raw = amount_usd / px
    decimals = CHAINS[chain]["decimals"]
    # Keep extra precision for uniqueness adjustment later
    places = min(8, decimals)
    return round(raw, places)


def unique_amount(chain: str, base: float, invoice_id: int) -> float:
    """
    Nudge amount by a tiny unique fraction so on-chain match is unambiguous.
    XRP uses destination tags instead; amount still rounded cleanly.
    """
    if chain == "xrp":
        # XRP has 6 decimal drops; keep 6 places
        return round(base, 6)
    if chain == "eth":
        # ~ 0.00000001 – 0.00009999 ETH unique tail
        nudge = ((invoice_id * 17) % 9999 + 1) * 1e-8
        return round(base + nudge, 8)
    if chain == "sol":
        # lamport-level uniqueness (~1e-9 SOL)
        nudge = ((invoice_id * 13) % 9999 + 1) * 1e-9
        return round(base + nudge, 9)
    return base


def new_public_id() -> str:
    return "cry_" + secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12]


def invoice_expires_at() -> datetime:
    mins = max(15, int(getattr(config, "CRYPTO_INVOICE_TTL_MIN", 60) or 60))
    return datetime.utcnow() + timedelta(minutes=mins)


def serialize_invoice(inv) -> dict[str, Any]:
    chain = (inv.chain or "").lower()
    meta = CHAINS.get(chain, {})
    tx = (inv.tx_hash or "").strip()
    explorer = ""
    if tx and meta.get("explorer_tx"):
        explorer = meta["explorer_tx"].format(tx=tx)
    return {
        "id": inv.id,
        "public_id": inv.public_id,
        "chain": chain,
        "asset_symbol": inv.asset_symbol or meta.get("symbol", chain.upper()),
        "network": meta.get("network", chain),
        "kind": inv.kind,
        "plan": inv.plan or None,
        "amount_usd": inv.amount_usd,
        "amount_crypto": inv.amount_crypto,
        "receive_address": inv.receive_address,
        "dest_tag": inv.dest_tag,
        "status": inv.status,
        "tx_hash": inv.tx_hash or None,
        "explorer_url": explorer or None,
        "expires_at": inv.expires_at.isoformat() + "Z" if inv.expires_at else None,
        "paid_at": inv.paid_at.isoformat() + "Z" if inv.paid_at else None,
        "created_at": inv.created_at.isoformat() + "Z" if inv.created_at else None,
        "instructions": _instructions(inv, meta),
    }


def _instructions(inv, meta: dict) -> list[str]:
    sym = inv.asset_symbol or meta.get("symbol", "")
    lines = [
        f"Send exactly {inv.amount_crypto} {sym} on {meta.get('network', inv.chain)}.",
        f"To address: {inv.receive_address}",
    ]
    if inv.chain == "xrp" and inv.dest_tag is not None:
        lines.append(f"REQUIRED destination tag: {inv.dest_tag} (payment will not match without it)")
    lines.append("After sending, paste the transaction hash / signature below and click Verify.")
    if inv.expires_at:
        lines.append(f"Invoice expires at {inv.expires_at.isoformat()}Z UTC.")
    return lines


# ---------------------------------------------------------------------------
# On-chain verification
# ---------------------------------------------------------------------------

def verify_payment(chain: str, *, receive_address: str, amount_crypto: float,
                   dest_tag: int | None, tx_hash: str) -> dict[str, Any]:
    chain = chain.lower().strip()
    tx_hash = (tx_hash or "").strip()
    if not tx_hash:
        return {"ok": False, "error": "tx_hash required"}
    if chain == "eth":
        return _verify_eth(receive_address, amount_crypto, tx_hash)
    if chain == "sol":
        return _verify_sol(receive_address, amount_crypto, tx_hash)
    if chain == "xrp":
        return _verify_xrp(receive_address, amount_crypto, dest_tag, tx_hash)
    return {"ok": False, "error": f"Unsupported chain {chain}"}


def _amount_match(actual: float, expected: float, rel_tol: float = 0.005, abs_tol: float = 0.0) -> bool:
    if expected <= 0:
        return False
    if abs_tol and abs(actual - expected) <= abs_tol:
        return True
    return abs(actual - expected) / expected <= rel_tol or actual >= expected * (1 - rel_tol)


def _verify_eth(to_addr: str, amount_eth: float, tx_hash: str) -> dict[str, Any]:
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    rpc = config.CRYPTO_ETH_RPC
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getTransactionByHash",
        "params": [tx_hash],
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(rpc, json=payload)
            r.raise_for_status()
            tx = (r.json() or {}).get("result")
    except Exception as e:
        return {"ok": False, "error": f"ETH RPC error: {e}"}
    if not tx:
        return {"ok": False, "error": "Transaction not found (pending or invalid hash)"}
    to = (tx.get("to") or "").lower()
    if to != to_addr.lower():
        return {"ok": False, "error": f"TX sends to {to}, expected {to_addr.lower()}"}
    try:
        value_wei = int(tx.get("value") or "0x0", 16)
    except Exception:
        return {"ok": False, "error": "Invalid value field"}
    actual = value_wei / 1e18
    if not _amount_match(actual, amount_eth, rel_tol=0.01, abs_tol=1e-8):
        return {
            "ok": False,
            "error": f"Amount mismatch: got {actual} ETH, expected ~{amount_eth} ETH",
            "actual": actual,
        }
    # Confirmations (optional)
    conf = _eth_confirmations(tx_hash, tx.get("blockNumber"))
    return {"ok": True, "actual": actual, "confirmations": conf, "tx_hash": tx_hash}


def _eth_confirmations(tx_hash: str, block_hex: str | None) -> int:
    if not block_hex:
        return 0
    try:
        with httpx.Client(timeout=12.0) as client:
            head = client.post(config.CRYPTO_ETH_RPC, json={
                "jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": [],
            }).json().get("result")
        if not head:
            return 0
        return max(0, int(head, 16) - int(block_hex, 16) + 1)
    except Exception:
        return 0


def _verify_sol(to_addr: str, amount_sol: float, signature: str) -> dict[str, Any]:
    rpc = config.CRYPTO_SOL_RPC
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ],
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(rpc, json=payload)
            r.raise_for_status()
            result = (r.json() or {}).get("result")
    except Exception as e:
        return {"ok": False, "error": f"SOL RPC error: {e}"}
    if not result:
        return {"ok": False, "error": "Transaction not found (pending or invalid signature)"}
    meta = result.get("meta") or {}
    if meta.get("err"):
        return {"ok": False, "error": f"Transaction failed on-chain: {meta.get('err')}"}

    # Prefer balance delta for recipient
    message = (result.get("transaction") or {}).get("message") or {}
    account_keys = message.get("accountKeys") or []
    keys = []
    for k in account_keys:
        if isinstance(k, dict):
            keys.append(k.get("pubkey") or "")
        else:
            keys.append(str(k))
    try:
        idx = keys.index(to_addr)
    except ValueError:
        # Sometimes only in instructions
        idx = -1
        for ix, k in enumerate(keys):
            if k == to_addr:
                idx = ix
                break
    actual = None
    if idx >= 0:
        pre = (meta.get("preBalances") or [])
        post = (meta.get("postBalances") or [])
        if idx < len(pre) and idx < len(post):
            delta_lamports = int(post[idx]) - int(pre[idx])
            if delta_lamports > 0:
                actual = delta_lamports / 1e9

    if actual is None:
        # Parse system transfer instructions
        instructions = message.get("instructions") or []
        for ins in instructions:
            parsed = ins.get("parsed") if isinstance(ins, dict) else None
            if not parsed:
                continue
            if parsed.get("type") == "transfer":
                info = parsed.get("info") or {}
                if info.get("destination") == to_addr:
                    actual = int(info.get("lamports") or 0) / 1e9
                    break

    if actual is None:
        return {"ok": False, "error": "Could not find transfer to our SOL address in this tx"}
    if not _amount_match(actual, amount_sol, rel_tol=0.01, abs_tol=1e-9):
        return {
            "ok": False,
            "error": f"Amount mismatch: got {actual} SOL, expected ~{amount_sol} SOL",
            "actual": actual,
        }
    return {"ok": True, "actual": actual, "confirmations": 1 if result.get("slot") else 0, "tx_hash": signature}


def _verify_xrp(to_addr: str, amount_xrp: float, dest_tag: int | None, tx_hash: str) -> dict[str, Any]:
    rpc = config.CRYPTO_XRP_RPC.rstrip("/")
    # Accept with or without uppercase
    tx_hash = tx_hash.strip()
    payload = {
        "method": "tx",
        "params": [{"transaction": tx_hash, "binary": False}],
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(rpc, json=payload)
            r.raise_for_status()
            body = r.json() or {}
            result = body.get("result") or body
    except Exception as e:
        return {"ok": False, "error": f"XRP RPC error: {e}"}

    if result.get("error") or result.get("status") == "error":
        return {"ok": False, "error": result.get("error_message") or result.get("error") or "tx not found"}

    # validated true when ledger validated
    if result.get("validated") is False:
        return {"ok": False, "error": "Transaction not yet validated on XRPL"}

    tx = result.get("tx_json") or result
    if (tx.get("TransactionType") or "") != "Payment":
        # some nodes nest differently
        if result.get("TransactionType") == "Payment":
            tx = result
        else:
            return {"ok": False, "error": f"Not a Payment transaction ({tx.get('TransactionType')})"}

    destination = tx.get("Destination") or ""
    if destination != to_addr:
        return {"ok": False, "error": f"Destination {destination} != {to_addr}"}

    tag = tx.get("DestinationTag")
    if dest_tag is not None:
        if tag is None or int(tag) != int(dest_tag):
            return {
                "ok": False,
                "error": f"Destination tag mismatch: got {tag}, expected {dest_tag}",
            }

    # Amount can be string drops (XRP) or object (IOU — reject IOU)
    amt = tx.get("Amount") or result.get("Amount")
    if isinstance(amt, dict):
        return {"ok": False, "error": "IOU payments not accepted — send native XRP only"}
    try:
        actual = int(amt) / 1_000_000.0  # drops → XRP
    except Exception:
        return {"ok": False, "error": f"Could not parse amount: {amt}"}

    meta = result.get("meta") or result.get("metaData") or {}
    if str(meta.get("TransactionResult") or "tesSUCCESS") not in ("tesSUCCESS",):
        # if missing, still check amount
        if meta.get("TransactionResult") and meta.get("TransactionResult") != "tesSUCCESS":
            return {"ok": False, "error": f"TX result {meta.get('TransactionResult')}"}

    if not _amount_match(actual, amount_xrp, rel_tol=0.01, abs_tol=0.000001):
        return {
            "ok": False,
            "error": f"Amount mismatch: got {actual} XRP, expected ~{amount_xrp} XRP",
            "actual": actual,
        }
    return {"ok": True, "actual": actual, "confirmations": 1 if result.get("validated") else 0, "tx_hash": tx_hash}


def scan_recent_for_invoice(chain: str, *, receive_address: str, amount_crypto: float,
                            dest_tag: int | None, since: datetime | None = None) -> dict[str, Any] | None:
    """
    Best-effort poll without a user-supplied hash.
    XRP: account_tx by destination tag.
    ETH/SOL: limited without indexer — returns None (user must paste hash).
    """
    if chain != "xrp":
        return None
    rpc = config.CRYPTO_XRP_RPC.rstrip("/")
    payload = {
        "method": "account_tx",
        "params": [{
            "account": receive_address,
            "ledger_index_min": -1,
            "ledger_index_max": -1,
            "limit": 30,
            "forward": False,
        }],
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(rpc, json=payload)
            r.raise_for_status()
            result = (r.json() or {}).get("result") or {}
    except Exception as e:
        log.warning("xrp account_tx failed: %s", e)
        return None

    for row in result.get("transactions") or []:
        tx = row.get("tx") or row.get("tx_json") or {}
        if tx.get("TransactionType") != "Payment":
            continue
        if tx.get("Destination") != receive_address:
            continue
        if dest_tag is not None and int(tx.get("DestinationTag") or -1) != int(dest_tag):
            continue
        amt = tx.get("Amount")
        if isinstance(amt, dict):
            continue
        try:
            actual = int(amt) / 1_000_000.0
        except Exception:
            continue
        if _amount_match(actual, amount_crypto, rel_tol=0.01):
            h = tx.get("hash") or row.get("hash")
            if h:
                return {"ok": True, "actual": actual, "tx_hash": h, "confirmations": 1}
    return None
