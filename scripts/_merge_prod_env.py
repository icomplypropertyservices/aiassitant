"""Merge filled secrets from backend/.env into .env.production.local (non-destructive)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / ".env"
PROD = ROOT / ".env.production.local"

# Never copy these from local dev into production pack (often wrong).
SKIP_COPY = {
    "APP_ENV",  # force production below
    "FRONTEND_URL",  # set from Vercel domain
    "CORS_ORIGINS",
    "OLLAMA_URL",  # local-only
    "OLLAMA_MODEL_FAST",
    "OLLAMA_MODEL_QUALITY",
    "OLLAMA_MODEL_QWEN_FAST",
    "OLLAMA_MODEL_QWEN_CODER",
    "OLLAMA_MODEL_QWEN_LARGE",
}

# Prefer production-generated secrets if already present (do not overwrite).
KEEP_IF_PRESENT = {"JWT_SECRET", "ENCRYPTION_KEY"}


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def is_filled(v: str) -> bool:
    if not v:
        return False
    low = v.lower()
    if low.startswith("your_") or low in {"changeme", "xxx", "todo", "replace_me"}:
        return False
    if v in {"sk_test_...", "whsec_..."}:
        return False
    return True


def main() -> None:
    be = parse(BACKEND)
    pl = parse(PROD)

    # Domain from Vercel project
    domain = "https://aiassitant-icomplypropertyservices-projects.vercel.app"
    pl["APP_ENV"] = "production"
    pl["FRONTEND_URL"] = domain
    pl["CORS_ORIGINS"] = domain
    pl.setdefault("XAI_BASE_URL", "https://api.x.ai/v1")
    pl.setdefault("XAI_MODEL_FAST", "grok-3-mini")
    pl.setdefault("XAI_MODEL_QUALITY", "grok-3")
    pl.setdefault(
        "API_PUBLIC_URL",
        f"{domain}/api",
    )
    pl.setdefault(
        "OAUTH_REDIRECT_URI",
        f"{domain}/api/integrations/oauth/callback",
    )

    # Process-level XAI if available
    import os

    if is_filled(os.environ.get("XAI_API_KEY", "")) and not is_filled(pl.get("XAI_API_KEY", "")):
        pl["XAI_API_KEY"] = os.environ["XAI_API_KEY"]

    copied = []
    for k, v in be.items():
        if k in SKIP_COPY:
            continue
        if not is_filled(v):
            continue
        if k in KEEP_IF_PRESENT and is_filled(pl.get(k, "")):
            continue
        if is_filled(pl.get(k, "")) and k not in {"DATABASE_URL"}:
            # keep existing prod pack value unless empty
            continue
        # For DATABASE_URL: only copy if looks remote (not sqlite/local)
        if k == "DATABASE_URL":
            low = v.lower()
            if "sqlite" in low or "localhost" in low or "127.0.0.1" in low:
                continue
            # normalize driver for SQLAlchemy if plain postgres URL
            if v.startswith("postgresql://") and "+psycopg2" not in v:
                v = v.replace("postgresql://", "postgresql+psycopg2://", 1)
            elif v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+psycopg2://", 1)
        pl[k] = v
        copied.append(k)

    # Stable key order for readability
    preferred = [
        "APP_ENV",
        "JWT_SECRET",
        "ENCRYPTION_KEY",
        "DATABASE_URL",
        "FRONTEND_URL",
        "CORS_ORIGINS",
        "API_PUBLIC_URL",
        "OAUTH_REDIRECT_URI",
        "XAI_API_KEY",
        "XAI_BASE_URL",
        "XAI_MODEL_FAST",
        "XAI_MODEL_QUALITY",
        "ANTHROPIC_API_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STARTER",
        "STRIPE_PRICE_PRO",
        "STRIPE_PRICE_BUSINESS",
        "RESEND_API_KEY",
        "RESEND_FROM",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
    ]
    lines = [
        "# Production env pack for Vercel (gitignored).",
        "# Generated/merged automatically — do not commit.",
        "",
    ]
    seen = set()
    for k in preferred:
        if k in pl:
            lines.append(f"{k}={pl[k]}")
            seen.add(k)
    for k in sorted(pl.keys()):
        if k not in seen:
            lines.append(f"{k}={pl[k]}")

    PROD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def status(k: str) -> str:
        v = pl.get(k, "")
        if not is_filled(v):
            return "MISSING"
        return f"SET ({len(v)} chars)"

    required = [
        "APP_ENV",
        "JWT_SECRET",
        "ENCRYPTION_KEY",
        "DATABASE_URL",
        "FRONTEND_URL",
        "CORS_ORIGINS",
        "XAI_API_KEY",
    ]
    print("=== Production env status ===")
    for k in required:
        print(f"  {k}: {status(k)}")
    optional = [
        "ANTHROPIC_API_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STARTER",
        "STRIPE_PRICE_PRO",
        "STRIPE_PRICE_BUSINESS",
        "RESEND_API_KEY",
        "TWILIO_ACCOUNT_SID",
    ]
    print("--- optional ---")
    for k in optional:
        print(f"  {k}: {status(k)}")
    print("copied_from_backend:", ", ".join(copied) if copied else "(none new)")
    print("wrote", PROD)


if __name__ == "__main__":
    main()
