"""
Admin-facing RunPod / Ollama fleet control plane.

- Connection settings (Ollama URL, WebUI, API key) editable by admin without redeploy
- Model map, pull, delete, test chat
- Allowlisted console (ollama-style ops) for staff + Grok-assisted ops
- Never expose provider details to customer UI
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from . import config

_DATA = Path(__file__).resolve().parent.parent / "data"
_MAP_PATH = _DATA / "fleet_model_map.json"
_CONN_PATH = _DATA / "fleet_connection.json"
_LOG_PATH = _DATA / "fleet_ops_log.json"

# PlatformSetting keys
KEY_CONNECTION = "fleet_connection"
KEY_MODEL_MAP = "fleet_model_map"
KEY_OPS_LOG = "fleet_ops_log"

RECOMMENDED_MODELS = [
    {"tag": "qwen2.5:3b", "tier": "small/fast", "vram_gb": 3},
    {"tag": "qwen2.5:7b", "tier": "fast", "vram_gb": 8},
    {"tag": "qwen2.5:14b", "tier": "quality", "vram_gb": 14},
    {"tag": "qwen2.5:32b", "tier": "large", "vram_gb": 24},
    {"tag": "qwen2.5:72b", "tier": "large (A100/H100)", "vram_gb": 48},
    {"tag": "qwen2.5-coder:7b", "tier": "coder", "vram_gb": 8},
    {"tag": "qwen2.5-coder:14b", "tier": "coder", "vram_gb": 14},
    {"tag": "qwen3-coder:30b", "tier": "coder large", "vram_gb": 28},
    {"tag": "deepseek-r1:8b", "tier": "reasoning", "vram_gb": 8},
    {"tag": "deepseek-r1:14b", "tier": "reasoning", "vram_gb": 14},
    {"tag": "deepseek-r1:32b", "tier": "reasoning", "vram_gb": 24},
    {"tag": "deepseek-r1:70b", "tier": "reasoning large (A100/H100)", "vram_gb": 48},
]

# Console: only these verbs (maps to Ollama HTTP API — no free shell)
_CONSOLE_HELP = (
    "Allowed commands:\n"
    "  list | ps | tags\n"
    "  pull <model>\n"
    "  rm <model> | delete <model>\n"
    "  show <model>\n"
    "  test <model> [prompt...]\n"
    "  help\n"
)


def _db_get(key: str) -> str | None:
    try:
        from .database import SessionLocal
        from . import models

        db = SessionLocal()
        try:
            row = db.get(models.PlatformSetting, key)
            if row and row.value:
                return row.value
        finally:
            db.close()
    except Exception:
        pass
    return None


def _db_set(key: str, value: str, updated_by: str = "") -> None:
    try:
        from .database import SessionLocal
        from . import models

        db = SessionLocal()
        try:
            row = db.get(models.PlatformSetting, key)
            if not row:
                row = models.PlatformSetting(key=key, value=value, updated_by=updated_by or "")
                db.add(row)
            else:
                row.value = value
                row.updated_by = updated_by or row.updated_by or ""
                row.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
    except Exception:
        # File fallback only
        pass


def _file_load(path: Path) -> dict | list | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _file_save(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_json_setting(key: str, file_path: Path, default: Any) -> Any:
    raw = _db_get(key)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    file_data = _file_load(file_path)
    if file_data is not None:
        return file_data
    return default


def _save_json_setting(key: str, file_path: Path, data: Any, updated_by: str = "") -> None:
    text = json.dumps(data, indent=2)
    _db_set(key, text, updated_by=updated_by)
    _file_save(file_path, data)


# ─── Connection ─────────────────────────────────────────────────────────────

def _default_connection() -> dict[str, Any]:
    return {
        "ollama_url": (config.RUNPOD_OLLAMA_URL or "").rstrip("/"),
        "webui_url": (config.RUNPOD_WEBUI_URL or "").rstrip("/"),
        "api_key": config.RUNPOD_API_KEY or "",
        "openai_base_url": (getattr(config, "RUNPOD_OPENAI_BASE_URL", None) or "").rstrip("/"),
        "support_notes": "",
        "agent_terminal_enabled": True,
        "source": "env",
    }


def get_connection(include_secrets: bool = False) -> dict[str, Any]:
    """Admin connection: DB/file overrides env."""
    base = _default_connection()
    stored = _load_json_setting(KEY_CONNECTION, _CONN_PATH, {}) or {}
    if isinstance(stored, dict) and stored:
        for k in (
            "ollama_url",
            "webui_url",
            "api_key",
            "openai_base_url",
            "support_notes",
            "agent_terminal_enabled",
        ):
            if k in stored and stored[k] is not None and str(stored[k]).strip() != "":
                base[k] = stored[k]
        base["source"] = "admin"
        base["updated_at"] = stored.get("updated_at")
        base["updated_by"] = stored.get("updated_by")
    out = dict(base)
    if not include_secrets:
        key = out.get("api_key") or ""
        out["api_key_set"] = bool(key)
        out["api_key"] = ("***" + key[-4:]) if len(key) > 4 else ("***" if key else "")
    return out


def set_connection(updates: dict[str, Any], updated_by: str = "") -> dict[str, Any]:
    current = _load_json_setting(KEY_CONNECTION, _CONN_PATH, {}) or {}
    if not isinstance(current, dict):
        current = {}
    for k in (
        "ollama_url",
        "webui_url",
        "api_key",
        "openai_base_url",
        "support_notes",
        "agent_terminal_enabled",
    ):
        if k not in updates:
            continue
        val = updates[k]
        if k == "api_key" and isinstance(val, str) and val.strip().startswith("***"):
            continue  # do not wipe with masked value
        if k in ("ollama_url", "webui_url", "openai_base_url") and isinstance(val, str):
            val = val.strip().rstrip("/")
        if k == "agent_terminal_enabled":
            val = bool(val)
        current[k] = val
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    current["updated_by"] = updated_by or ""
    _save_json_setting(KEY_CONNECTION, _CONN_PATH, current, updated_by=updated_by)
    log_op("connection_update", f"by {updated_by or 'admin'}", ok=True)
    return get_connection(include_secrets=False)


def ollama_base() -> str:
    c = get_connection(include_secrets=True)
    url = (c.get("ollama_url") or "").rstrip("/")
    if url:
        return url
    # Env / local (non-prod loopback handled in config)
    managed = (getattr(config, "MANAGED_OLLAMA_URL", None) or "").rstrip("/")
    if managed:
        return managed
    local = (config.OLLAMA_URL or "").rstrip("/")
    return local


def webui_url() -> str:
    c = get_connection(include_secrets=True)
    return (c.get("webui_url") or config.RUNPOD_WEBUI_URL or "").rstrip("/")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    c = get_connection(include_secrets=True)
    key = (c.get("api_key") or config.RUNPOD_API_KEY or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


# ─── Model map ──────────────────────────────────────────────────────────────

def _load_map_file() -> dict[str, str]:
    data = _load_json_setting(KEY_MODEL_MAP, _MAP_PATH, {})
    return data if isinstance(data, dict) else {}


def _save_map_file(data: dict[str, str], updated_by: str = "") -> None:
    _save_json_setting(KEY_MODEL_MAP, _MAP_PATH, data, updated_by=updated_by)


def get_model_map() -> dict[str, str]:
    base = dict(config.RUNPOD_MODEL_MAP)
    base.update(_load_map_file())
    return base


def set_model_map(updates: dict[str, str], updated_by: str = "") -> dict[str, str]:
    current = _load_map_file()
    for k, v in updates.items():
        if not k or not v:
            continue
        current[str(k).strip().lower()] = str(v).strip()
    _save_map_file(current, updated_by=updated_by)
    log_op("model_map", f"updated keys={list(updates.keys())}", ok=True)
    return get_model_map()


def resolve_ollama_tag(neutral_or_raw: str) -> str:
    m = (neutral_or_raw or "fast").lower().strip()
    mapping = get_model_map()
    if m in mapping:
        return mapping[m]
    return neutral_or_raw


# ─── Ops log ────────────────────────────────────────────────────────────────

def log_op(action: str, detail: str, ok: bool = True) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "detail": (detail or "")[:500],
        "ok": ok,
    }
    log = _load_json_setting(KEY_OPS_LOG, _LOG_PATH, [])
    if not isinstance(log, list):
        log = []
    log.insert(0, entry)
    log = log[:100]
    _save_json_setting(KEY_OPS_LOG, _LOG_PATH, log)


def get_ops_log(limit: int = 40) -> list[dict]:
    log = _load_json_setting(KEY_OPS_LOG, _LOG_PATH, [])
    if not isinstance(log, list):
        return []
    return log[: max(1, min(limit, 100))]


# ─── Ollama HTTP ops ────────────────────────────────────────────────────────

async def probe_ollama() -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {
            "ok": False,
            "error": "Ollama URL not set — Admin → Fleet → Connection, or RUNPOD_OLLAMA_URL",
            "url": None,
            "models": [],
            "latency_ms": None,
            "webui_url": webui_url() or None,
        }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/api/tags", headers=_headers())
            r.raise_for_status()
            data = r.json()
            models = []
            for m in data.get("models") or []:
                models.append({
                    "name": m.get("name") or m.get("model"),
                    "size": m.get("size"),
                    "modified_at": m.get("modified_at"),
                    "details": m.get("details") or {},
                })
            ms = int((time.perf_counter() - t0) * 1000)
            return {
                "ok": True,
                "url": base,
                "models": models,
                "count": len(models),
                "latency_ms": ms,
                "webui_url": webui_url() or None,
            }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:300],
            "url": base,
            "models": [],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "webui_url": webui_url() or None,
        }


async def pull_model(tag: str) -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {"ok": False, "error": "Ollama URL not configured"}
    tag = (tag or "").strip()
    if not tag:
        return {"ok": False, "error": "tag required"}
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.post(
                f"{base}/api/pull",
                headers=_headers(),
                json={"name": tag, "stream": False},
            )
            if r.status_code >= 400:
                log_op("pull", f"{tag}: {r.text[:200]}", ok=False)
                return {"ok": False, "error": r.text[:400], "status": r.status_code}
            log_op("pull", tag, ok=True)
            return {"ok": True, "tag": tag, "detail": r.json() if r.content else {}}
    except Exception as e:
        log_op("pull", f"{tag}: {e}", ok=False)
        return {"ok": False, "error": str(e)[:400], "tag": tag}


async def delete_model(tag: str) -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {"ok": False, "error": "Ollama URL not configured"}
    tag = (tag or "").strip()
    if not tag:
        return {"ok": False, "error": "tag required"}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.request(
                "DELETE",
                f"{base}/api/delete",
                headers=_headers(),
                json={"name": tag},
            )
            if r.status_code >= 400:
                log_op("delete", f"{tag}: {r.text[:200]}", ok=False)
                return {"ok": False, "error": r.text[:400], "status": r.status_code}
            log_op("delete", tag, ok=True)
            return {"ok": True, "tag": tag}
    except Exception as e:
        log_op("delete", f"{tag}: {e}", ok=False)
        return {"ok": False, "error": str(e)[:400], "tag": tag}


async def show_model(tag: str) -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {"ok": False, "error": "Ollama URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{base}/api/show",
                headers=_headers(),
                json={"name": tag},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "tag": tag, "info": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:400]}


async def running_models() -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {"ok": False, "error": "Ollama URL not configured", "models": []}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/api/ps", headers=_headers())
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400], "models": []}
            data = r.json()
            return {"ok": True, "models": data.get("models") or data}
    except Exception as e:
        return {"ok": False, "error": str(e)[:400], "models": []}


async def test_generate(tag: str, prompt: str = "Say hello in one short sentence.") -> dict[str, Any]:
    base = ollama_base()
    if not base:
        return {"ok": False, "error": "Ollama URL not configured"}
    tag = resolve_ollama_tag(tag)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{base}/api/chat",
                headers=_headers(),
                json={
                    "model": tag,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            if r.status_code >= 400:
                log_op("test", f"{tag} failed", ok=False)
                return {"ok": False, "error": r.text[:400], "tag": tag}
            data = r.json()
            text = (data.get("message") or {}).get("content") or data.get("response") or ""
            log_op("test", f"{tag} ok", ok=True)
            return {"ok": True, "tag": tag, "reply": text[:2000]}
    except Exception as e:
        log_op("test", f"{tag}: {e}", ok=False)
        return {"ok": False, "error": str(e)[:400], "tag": tag}


# ─── Allowlisted console (staff terminal) ───────────────────────────────────

_TAG_RE = re.compile(r"^[a-zA-Z0-9_./:-]{1,120}$")


async def run_console(command: str) -> dict[str, Any]:
    """
    Restricted ops terminal — only Ollama management via HTTP API.
    No arbitrary shell. Safe for admin UI and Grok-assisted sessions.
    """
    conn = get_connection(include_secrets=True)
    if conn.get("agent_terminal_enabled") is False:
        return {
            "ok": False,
            "output": "Fleet terminal is disabled. Enable it in Connection settings.",
            "command": command,
        }

    raw = (command or "").strip()
    if not raw:
        return {"ok": False, "output": "Empty command.\n" + _CONSOLE_HELP, "command": command}

    # strip optional "ollama " prefix
    line = raw
    if line.lower().startswith("ollama "):
        line = line[7:].strip()

    parts = line.split()
    verb = (parts[0] if parts else "").lower()
    args = parts[1:]

    if verb in ("help", "?"):
        return {"ok": True, "output": _CONSOLE_HELP, "command": raw}

    if verb in ("list", "tags", "ls"):
        probe = await probe_ollama()
        if not probe.get("ok"):
            return {"ok": False, "output": probe.get("error") or "probe failed", "command": raw}
        lines = [f"{m.get('name')}\t{((m.get('size') or 0) / 1e9):.1f} GB" for m in (probe.get("models") or [])]
        out = f"{len(lines)} model(s) on {probe.get('url')}\n" + ("\n".join(lines) if lines else "(none)")
        return {"ok": True, "output": out, "command": raw}

    if verb == "ps":
        r = await running_models()
        return {
            "ok": r.get("ok", False),
            "output": json.dumps(r.get("models") or r.get("error"), indent=2)[:4000],
            "command": raw,
        }

    if verb == "pull":
        if not args or not _TAG_RE.match(args[0]):
            return {"ok": False, "output": "Usage: pull <model-tag>", "command": raw}
        r = await pull_model(args[0])
        return {
            "ok": r.get("ok", False),
            "output": json.dumps(r, indent=2)[:4000],
            "command": raw,
        }

    if verb in ("rm", "delete", "remove"):
        if not args or not _TAG_RE.match(args[0]):
            return {"ok": False, "output": "Usage: rm <model-tag>", "command": raw}
        r = await delete_model(args[0])
        return {
            "ok": r.get("ok", False),
            "output": json.dumps(r, indent=2)[:4000],
            "command": raw,
        }

    if verb == "show":
        if not args or not _TAG_RE.match(args[0]):
            return {"ok": False, "output": "Usage: show <model-tag>", "command": raw}
        r = await show_model(args[0])
        info = r.get("info") or r
        # trim huge blobs
        if isinstance(info, dict):
            slim = {k: info[k] for k in list(info)[:20] if k not in ("modelfile", "license")}
            text = json.dumps(slim, indent=2)[:4000]
        else:
            text = str(info)[:4000]
        return {"ok": r.get("ok", False), "output": text, "command": raw}

    if verb == "test":
        if not args:
            return {"ok": False, "output": "Usage: test <model-or-tier> [prompt...]", "command": raw}
        tag = args[0]
        prompt = " ".join(args[1:]) if len(args) > 1 else "Say hello in one short sentence."
        r = await test_generate(tag, prompt)
        if r.get("ok"):
            return {"ok": True, "output": f"[{r.get('tag')}]\n{r.get('reply')}", "command": raw}
        return {"ok": False, "output": r.get("error") or "test failed", "command": raw}

    return {
        "ok": False,
        "output": f"Unknown or blocked command: {verb!r}\n" + _CONSOLE_HELP,
        "command": raw,
    }


def support_bundle() -> dict[str, Any]:
    """Safe summary for pasting into Grok / support (no raw API keys)."""
    c = get_connection(include_secrets=False)
    probe_note = "Call Admin → Test connection or fleet/status for live probe."
    return {
        "ollama_url": c.get("ollama_url") or None,
        "webui_url": c.get("webui_url") or None,
        "api_key_set": c.get("api_key_set"),
        "openai_base_url": c.get("openai_base_url") or None,
        "model_map": get_model_map(),
        "agent_terminal_enabled": c.get("agent_terminal_enabled", True),
        "support_notes": c.get("support_notes") or "",
        "source": c.get("source"),
        "updated_at": c.get("updated_at"),
        "updated_by": c.get("updated_by"),
        "how_to_grant_grok": (
            "1) Save Connection in Admin → LLM Fleet.\n"
            "2) Enable Fleet terminal.\n"
            "3) Paste Ollama proxy URL here in chat, or ask Grok to use Admin console commands "
            "(list / pull / rm / test) while you run them, or open this app as admin in the same session.\n"
            "4) Grok with workspace access can also read backend/data/fleet_connection.json (API key masked in UI only)."
        ),
        "note": probe_note,
    }
