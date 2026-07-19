# Product concepts

Three distinct “product” ideas appear in the product and codebase. They are **not** the same model. Keep them separate in UI, skills, and APIs.

---

## 1. Business Product (tenant catalogue)

**What it is:** An item in a workspace’s own catalogue — what the business sells or delivers to its customers.

**Where it lives:** Main Assistant app under Business / CRM (`backend/app/routers/business_products.py`, related CRM models).

**Who owns it:** The tenant (`owner_user_id` / company scope).

**Typical use:** SKUs, services, packages listed next to customers, deals, and pipelines. Agents may reference catalogue products when drafting proposals or syncing commerce apps (e.g. Shopify).

**Not:** A marketplace listing and not a one-off pitch object in a conversation.

---

## 2. AgentBay listing (marketplace sellable)

**What it is:** A sellable listing on the AgentBay marketplace — usually a skill, agent template, or digital good another subscriber can discover and buy.

**Where it lives:** AgentBay surface (`/bay`, `agentbay_backend/`), bridged from the Assistant via publish flows (e.g. `publish_skill_to_bay`).

**Who owns it:** The seller account on AgentBay; fulfillment is marketplace-side.

**Typical use:** An agent invents a skill, publishes it to the bay, and earns from installs/purchases.

**Not:** The tenant’s internal Business Product row, and not a practice pitch used only inside Comms.

---

## 3. Comms practice product (pitch object)

**What it is:** A lightweight product/offer description used while practicing or running outbound communications — a pitch object for drafts, roleplay, and message context.

**Where it lives:** Comms / training-style flows (`backend/app/routers/comms.py` and related practice UI), not the durable catalogue.

**Who owns it:** Ephemeral or practice-scoped to the user session/workspace context.

**Typical use:** “Sell this offer in a call script” or “draft an email about this package” without creating a Business Product or AgentBay listing.

**Not:** Inventory SKU management and not a public marketplace listing.

---

## Quick comparison

| Concept | Durable? | Audience | Primary surface |
|---------|----------|----------|-----------------|
| Business Product | Yes (tenant DB) | Internal team + customers | Business / CRM |
| AgentBay listing | Yes (marketplace) | Other subscribers | `/bay` |
| Comms practice product | Practice / pitch only | Agent + human in Comms | Comms practice |

When writing skills or LLM prompts: name the concept explicitly (e.g. “catalogue product”, “AgentBay listing”, “practice pitch”) so agents do not invent a fourth product type or mix write targets.
