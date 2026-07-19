# Meeting rooms

Multi-party human + agent brainstorm / war-room threads.

**API base:** `/api` (auth: `Authorization: Bearer …`)

**Enums**

| Field | Values |
|-------|--------|
| `room_type` | `brainstorm`, `task_war_room`, `standup`, `review` |
| `status` | `open`, `active`, `closed` |
| participant `kind` | `user`, `agent`, `human` |
| participant `role` | `chair`, `member`, `observer` |
| `msg_type` | `chat`, `decision`, `task_created`, `system` |

---

## Endpoints

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/api/meetings` | List rooms. Query: `status`, `room_type`, `project_id`, `task_id`, `limit` |
| `POST` | `/api/meetings` | Create room |
| `GET` | `/api/meetings/{id}` | Room + participants (+ messages by default) |
| `PATCH` | `/api/meetings/{id}` | Update title/purpose/type/status/links/settings/summary |
| `POST` | `/api/meetings/{id}/participants` | Add participant |
| `DELETE` | `/api/meetings/{id}/participants/{pid}` | Remove participant |
| `GET` | `/api/meetings/{id}/messages` | List messages (`limit`, `after_id`) |
| `POST` | `/api/meetings/{id}/messages` | Post message |
| `POST` | `/api/meetings/{id}/round` | Run one multi-agent discussion round |
| `POST` | `/api/meetings/{id}/summarize` | LLM summary → `summary_text` |
| `POST` | `/api/meetings/{id}/extract-tasks` | Extract action items → Tasks |
| `POST` | `/api/meetings/{id}/close` | Set status `closed` |

Owner-scoped: rooms belong to the authenticated user.

---

## Create a room

```http
POST /api/meetings
Content-Type: application/json

{
  "title": "Q3 pipeline brainstorm",
  "purpose": "Prioritize pipeline work",
  "room_type": "brainstorm",
  "company_id": null,
  "project_id": null,
  "task_id": null,
  "chair_agent_id": 12,
  "settings": {},
  "participants": [
    { "kind": "agent", "agent_id": 15, "role": "member" },
    { "kind": "human", "human_id": 3, "role": "observer" }
  ]
}
```

**What happens**

1. Room opens with `status=open`.
2. Owner is added as participant `kind=user` (chair unless a chair agent is set).
3. Optional `chair_agent_id` joins as agent chair.
4. Extra `participants` are validated (agent/human must be owned by you).
5. A system message is posted (`event: created`).

First chat or round moves status to `active`.

---

## Run a round

Agents take turns (chair first, max 5 agents). Each posts a short chat reply from purpose + linked task + last ~20 messages.

```http
POST /api/meetings/{id}/round
Content-Type: application/json

{
  "prompt": "Focus on blockers for launch",
  "max_turns": 1
}
```

- Optional `prompt` is posted as a user message before agents speak.
- Requires credits (`ensure_credits`); uses user LLM credentials.
- Room must not be `closed`; needs at least one agent participant (or chair agent).
- Response: `{ ok, room_id, messages, count, meeting }` — new agent messages for this round.
- Implementation: `backend/app/meeting_runner.py` → `run_meeting_round`.

---

## Extract tasks

Pull action items from transcript (and summary) into `Task` rows linked via `meeting_id`.

```http
POST /api/meetings/{id}/extract-tasks
Content-Type: application/json

{
  "model": "fast",
  "create": true,
  "assign_to_chair": true
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `model` | `fast` | LLM used for JSON extraction |
| `create` | `true` | Persist tasks; `false` = dry-run titles only |
| `assign_to_chair` | `true` | Prefer `chair_agent_id` as assignee |

**Flow**

1. Prefer LLM JSON array of `{ title, description, priority, … }`.
2. If LLM fails/empty → heuristic (`meeting_extract.extract_tasks_from_room`): action-looking lines, else 1–3 from summary, else purpose/title fallback.
3. Status: `queued` if an agent is assigned, else `todo`. Labels: `meeting,extracted`.
4. Posts `msg_type=task_created` system message(s).
5. Response: `{ ok, room_id, created, tasks, count, source }` (`source`: `llm` or `heuristic`).

Also useful: `POST /api/meetings/{id}/summarize` with `{ "style": "concise"|"detailed"|"decisions" }` before extract.

---

## UI paths

| Path | Page | Actions |
|------|------|---------|
| `/meetings` | List | Refresh; **New meeting** modal (title, purpose, type, chair, agent participants) → navigates to room |
| `/meetings/:id` | Room | Thread; send message; **Create task** modal; **Close**; **Refresh**; back to list |
| Nav | Sidebar **Meetings** | `AppLayout` → `/meetings` |

**Entry from elsewhere**

- **Tasks board** — discuss task → `POST /meetings` with `title` + `task_id` → `/meetings/:id`
- **Agent detail** — open meeting with agent → `POST /meetings` → `/meetings/:id`

**Frontend API calls (current UI)**

- List/create: `GET|POST /meetings/`
- Room: `GET /meetings/:id`
- Message: `POST /meetings/:id/messages`
- Close: `POST /meetings/:id/close`

Round / summarize / extract-tasks are available on the API; wire them from the room page when adding agent-run or extract buttons.

**Source**

- API: `backend/app/routers/meetings.py`
- Round: `backend/app/meeting_runner.py`
- Heuristic extract: `backend/app/meeting_extract.py`
- UI: `frontend/src/pages/Meetings.jsx`, `MeetingRoom.jsx`
- Routes: `frontend/src/App.jsx` → `meetings`, `meetings/:id`
- Smoke: `python scripts/smoke_meetings.py` (optional token)
