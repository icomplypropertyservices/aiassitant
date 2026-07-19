# Agent CLI, API, wallets, Git & local machines

## API base

`https://www.aibusinessagent.xyz/api`

Auth: `Authorization: Bearer aba_…` (from login).

## Orchestrator + 3 companies

```http
POST /api/cli/bootstrap
POST /api/agents/ensure-orchestrator   # bootstrap=true by default
GET  /api/cli/guidance
GET  /api/cli/status
```

Creates / ensures:

1. **Fire Alarms Dublin** — service, certificates, installs  
2. **iComply Property Services** — property compliance  
3. **iComply Products** — Shopify / SEO catalogue  

Plus Main AI Orchestrator, company leads, starter projects/tasks, **agent crypto wallets**.

## Wallets (crypto)

```http
GET  /api/cli/wallets
POST /api/cli/wallets/ensure/{agent_id}
POST /api/cli/wallets/{agent_id}/credit
POST /api/cli/wallets/{agent_id}/transfer
POST /api/cli/wallets/{agent_id}/link-address
GET  /api/cli/wallets/{agent_id}/export-keys?confirm=EXPORT
```

Chains: ETH, SOL, BTC, XRP (+ platform USD credits slice).

## Git repos

```http
GET  /api/cli/git/repos
POST /api/cli/git/connect/github   { "full_name": "owner/repo", "token": "ghp_…" }
POST /api/cli/git/connect/local    { "name": "app", "local_path": "C:\\…" }
POST /api/cli/git/github/list      { "token": "ghp_…" }
DELETE /api/cli/git/repos/{id}
```

## Local machines

```http
GET  /api/cli/machines
POST /api/cli/machines/register   # send snapshot from CLI for real laptop
GET  /api/cli/machines/local-snapshot  # API host only
```

## CLI

From `backend/`:

```bash
# Login (saves ~/.aba/config.json)
python -m cli.aba login --email firealarmsdublin@gmail.com --password '***'

python -m cli.aba status
python -m cli.aba bootstrap
python -m cli.aba agents
python -m cli.aba wallets
python -m cli.aba machine register
python -m cli.aba machine list
python -m cli.aba git connect icomplypropertyservices/products.icomplypropertyservices.co.uk --token ghp_...
python -m cli.aba git local icomply-products --path C:\Users\E-Store\icomply-products-seo
python -m cli.aba git list
```

Env:

- `ABA_BASE` (default `https://www.aibusinessagent.xyz`)
- `ABA_TOKEN` or `~/.aba/config.json`
- `GITHUB_TOKEN` optional for git connect
