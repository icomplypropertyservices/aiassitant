/**
 * Live probe: ask orchestrator for status_update / human-facing open work summary.
 * Also checks ops live feed + agent activity, screenshots chat + ops UI.
 *
 * node scripts/live_status_update_probe.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SHOTS = path.join(__dirname, 'live-screenshots')
const CREDS = path.join(__dirname, '.demo_login.json')
const REPORT = path.join(__dirname, 'live_status_update_report.json')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`

const MSG =
  'Send me a status_update skill or clear human-facing summary of open work.'

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  if (!fs.existsSync(CREDS)) throw new Error(`Missing ${CREDS}`)
  return JSON.parse(fs.readFileSync(CREDS, 'utf8'))
}

function persistCreds(creds) {
  try {
    fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
  } catch {
    /* ignore */
  }
}

async function forceLogin(creds) {
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const r = await fetch(`${BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: creds.email, password: creds.password }),
      })
      const j = await r.json().catch(() => null)
      const key = j?.api_key || j?.token
      if (r.ok && key) {
        creds.api_key = key
        if (j.user?.id != null) creds.user_id = j.user.id
        persistCreds(creds)
        console.log(`Login ok (attempt ${attempt + 1})`)
        return creds
      }
      if (r.status === 429) {
        const m = /Try again in (\d+)/i.exec(JSON.stringify(j || ''))
        const waitSec = m ? Math.min(120, parseInt(m[1], 10) + 2) : Math.min(90, 12 + attempt * 15)
        console.warn(`Login 429; wait ${waitSec}s`)
        await new Promise((res) => setTimeout(res, waitSec * 1000))
        continue
      }
      console.warn(`Login failed ${r.status}`, typeof j === 'object' ? JSON.stringify(j).slice(0, 160) : j)
      await new Promise((res) => setTimeout(res, 2000 * (attempt + 1)))
    } catch (e) {
      console.warn(`Login error: ${e.message}`)
      await new Promise((res) => setTimeout(res, 2000 * (attempt + 1)))
    }
  }
  return creds
}

async function refreshCreds(creds, { force = false } = {}) {
  if (!force && creds.api_key) {
    try {
      const r = await fetch(`${BASE}/api/auth/me`, {
        headers: {
          Authorization: `Bearer ${creds.api_key}`,
          Accept: 'application/json',
          'X-API-Key': creds.api_key,
        },
      })
      if (r.ok) {
        const j = await r.json().catch(() => null)
        if (j?.id != null) creds.user_id = j.id
        console.log('Reusing valid api_key')
        return creds
      }
    } catch {
      /* fall through */
    }
  }
  return forceLogin(creds)
}

async function api(creds, pathName, { method = 'GET', body = null, timeoutMs = 180000 } = {}) {
  async function once(key) {
    const headers = {
      Authorization: `Bearer ${key}`,
      'X-API-Key': key,
      Accept: 'application/json',
    }
    if (body != null) headers['Content-Type'] = 'application/json'
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const r = await fetch(`${BASE}${pathName}`, {
        method,
        headers,
        body: body != null ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      })
      const text = await r.text()
      let json
      try {
        json = JSON.parse(text)
      } catch {
        json = text.slice(0, 2000)
      }
      return { status: r.status, body: json, path: pathName }
    } finally {
      clearTimeout(t)
    }
  }

  let res = await once(creds.api_key)
  // Shared demo key can rotate under swarm load — force re-login and retry up to 3x
  for (let i = 0; i < 3 && res.status === 401; i++) {
    console.warn(`401 on ${pathName}; force login retry ${i + 1}/3`)
    await forceLogin(creds)
    res = await once(creds.api_key)
  }
  return res
}

function extractReply(body) {
  if (!body) return ''
  if (typeof body === 'string') return body
  return (
    body.reply ||
    body.message ||
    body.content ||
    body.text ||
    (body.messages && body.messages[body.messages.length - 1]?.content) ||
    ''
  )
}

function analyzeHumanFacing(reply) {
  const text = String(reply || '')
  const lower = text.toLowerCase()
  // Patterns that address the human owner / stakeholder
  const humanSignals = [
    /\byou\b/i,
    /\byour\b/i,
    /\bfor you\b/i,
    /\bowner\b/i,
    /\bstakeholder/i,
    /\bhere(?:'s| is)\b/i,
    /\bsummary\b/i,
    /\bstatus\b/i,
    /\bopen work\b/i,
    /\bin progress\b/i,
    /\bblocked\b/i,
    /\brag\b/i,
    /\bgreen\b|\bamber\b|\bred\b/i,
    /\bnext steps?\b/i,
  ]
  // Patterns that wrongly talk as if the recipient is the AI itself
  const aiSelfSignals = [
    /\bas an ai\b/i,
    /\bi am (?:an? )?(?:language model|ai)\b/i,
    /\byou the ai\b/i,
    /\byou(?:'re| are) (?:an? )?(?:ai|assistant|language model)\b/i,
    /\byour (?:model|prompt|system)\b/i,
    /\byou should (?:call|invoke|use) the skill\b/i,
  ]
  const humanHits = humanSignals.filter((re) => re.test(text)).map((re) => re.source)
  const aiHits = aiSelfSignals.filter((re) => re.test(text)).map((re) => re.source)
  const addressesHuman =
    text.length > 40 &&
    aiHits.length === 0 &&
    (humanHits.length >= 1 || /\b(status|summary|open|task|work|progress)\b/i.test(text))
  return {
    addresses_human: addressesHuman,
    human_signal_count: humanHits.length,
    human_signals: humanHits.slice(0, 12),
    ai_self_signals: aiHits,
    length: text.length,
    looks_like_status:
      /\b(status|rag|green|amber|red|open work|in progress|blocked|summary)\b/i.test(lower),
  }
}

async function main() {
  const report = {
    generated_at: new Date().toISOString(),
    base_url: BASE,
    message: MSG,
    steps: {},
    chat: null,
    ops: null,
    activity: null,
    human_facing: null,
    screenshots: [],
    summary: {},
  }

  let creds = loadCreds()
  // Always force password login so we are not racing on a stale rotated key
  creds = await forceLogin(creds)
  report.email = creds.email
  report.user_id = creds.user_id
  report.agent_id = creds.agent_id

  // health
  try {
    const h = await fetch(`${BASE}/api/health`, { headers: { Accept: 'application/json' } })
    report.steps.health = { status: h.status, body: await h.json().catch(() => null) }
    console.log('HEALTH', h.status)
  } catch (e) {
    report.steps.health = { error: e.message }
  }

  // ensure orchestrator
  let agentId = creds.agent_id
  const agentsRes = await api(creds, '/api/agents/')
  const list = Array.isArray(agentsRes.body)
    ? agentsRes.body
    : agentsRes.body?.agents || agentsRes.body?.items || []
  report.steps.agents = {
    status: agentsRes.status,
    count: list.length,
    ids: list.slice(0, 12).map((a) => ({
      id: a.id,
      name: a.name,
      hierarchy_role: a.hierarchy_role,
      is_orchestrator: a.is_orchestrator,
    })),
  }
  const orch =
    list.find((a) => a.is_orchestrator || a.hierarchy_role === 'orchestrator') || list[0]
  if (orch) agentId = orch.id
  if (!agentId) {
    const ensure = await api(creds, '/api/agents/ensure-orchestrator', {
      method: 'POST',
      body: {},
    })
    agentId = ensure.body?.id
    report.steps.ensure_orchestrator = { status: ensure.status, id: agentId }
  }
  creds.agent_id = agentId
  persistCreds(creds)
  report.agent_id = agentId
  console.log('AGENT', agentId)

  // open tasks snapshot before chat
  const tasksBefore = await api(creds, '/api/org/tasks')
  let tasksList = []
  if (tasksBefore.status === 200) {
    tasksList = Array.isArray(tasksBefore.body)
      ? tasksBefore.body
      : tasksBefore.body?.tasks || tasksBefore.body?.items || []
  } else {
    const t2 = await api(creds, `/api/agents/${agentId}/tasks`)
    tasksList = Array.isArray(t2.body) ? t2.body : t2.body?.tasks || []
    report.steps.tasks_path = t2.path
  }
  const openTasks = tasksList.filter((t) =>
    !['completed', 'done', 'cancelled', 'canceled', 'failed'].includes(
      String(t.status || '').toLowerCase(),
    ),
  )
  report.steps.open_tasks_before = {
    total: tasksList.length,
    open: openTasks.length,
    sample: openTasks.slice(0, 8).map((t) => ({
      id: t.id,
      title: t.title || t.description?.slice?.(0, 80),
      status: t.status,
      agent_id: t.agent_id,
    })),
  }
  console.log('OPEN_TASKS', openTasks.length)

  // ops live before
  const opsBefore = await api(creds, '/api/ops/live?limit=30')
  report.steps.ops_before = {
    status: opsBefore.status,
    events: (opsBefore.body?.events || []).slice(0, 8),
    snapshot: opsBefore.body?.snapshot || null,
  }
  console.log('OPS_BEFORE', opsBefore.status, (opsBefore.body?.events || []).length, 'events')

  // activity before
  const actBefore = await api(creds, `/api/agents/${agentId}/activity`)
  report.steps.activity_before = {
    status: actBefore.status,
    sample: Array.isArray(actBefore.body)
      ? actBefore.body.slice(0, 5)
      : actBefore.body?.activity?.slice?.(0, 5) || actBefore.body,
  }

  // Chat via API (reliable for reply text)
  console.log('CHAT sending…', MSG)
  const chat = await api(creds, `/api/agents/${agentId}/chat`, {
    method: 'POST',
    body: { message: MSG, content: MSG, text: MSG },
    timeoutMs: 240000,
  })
  const reply = extractReply(chat.body)
  const skills = chat.body?.skills || chat.body?.skill_results || null
  report.chat = {
    status: chat.status,
    path: chat.path,
    reply,
    skills,
    goal_chain: chat.body?.goal_chain || null,
    conversation_id: chat.body?.conversation_id || null,
    tokens: chat.body?.tokens,
    cost: chat.body?.cost,
    raw_keys: chat.body && typeof chat.body === 'object' ? Object.keys(chat.body) : null,
  }
  console.log('CHAT', chat.status, 'reply_len=', reply.length)
  console.log('REPLY_PREVIEW', reply.slice(0, 500))

  report.human_facing = analyzeHumanFacing(reply)
  console.log('HUMAN_FACING', JSON.stringify(report.human_facing))

  // ops + activity after
  await new Promise((r) => setTimeout(r, 1500))
  const opsAfter = await api(creds, '/api/ops/live?limit=40')
  report.ops = {
    status: opsAfter.status,
    events: (opsAfter.body?.events || []).slice(0, 15),
    snapshot: opsAfter.body?.snapshot || null,
    event_count: (opsAfter.body?.events || []).length,
  }
  const actAfter = await api(creds, `/api/agents/${agentId}/activity`)
  const actList = Array.isArray(actAfter.body)
    ? actAfter.body
    : actAfter.body?.activity || actAfter.body?.items || []
  report.activity = {
    status: actAfter.status,
    recent: (Array.isArray(actList) ? actList : []).slice(0, 12),
  }
  console.log('OPS_AFTER', opsAfter.status, report.ops.event_count, 'events')

  // Persist API-only result early so a browser hang still leaves evidence
  const midOk =
    report.chat?.status >= 200 &&
    report.chat?.status < 300 &&
    !!report.chat?.reply &&
    report.human_facing?.addresses_human === true
  report.summary = {
    ok: midOk,
    phase: 'api_done',
    chat_status: report.chat?.status,
    reply_preview: (report.chat?.reply || '').slice(0, 800),
    full_reply: report.chat?.reply || '',
    addresses_human: report.human_facing?.addresses_human,
    looks_like_status: report.human_facing?.looks_like_status,
    ops_events: report.ops?.event_count ?? 0,
    ops_api_ok: report.ops?.status === 200,
    activity_ok: report.activity?.status === 200,
    screenshots: [],
    skills_used: report.chat?.skills,
  }
  fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
  console.log('Mid-report written after chat/ops')

  // Browser screenshots: chat UI + ops banner (no second LLM UI send — API reply is source of truth)
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  try {
    await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.evaluate(
      ({ apiKey, user }) => {
        localStorage.setItem('api_key', apiKey)
        localStorage.setItem('token', apiKey)
        if (user) localStorage.setItem('user', JSON.stringify(user))
      },
      {
        apiKey: creds.api_key,
        user: {
          id: creds.user_id,
          email: creds.email,
          name: 'Live Demo',
          role: 'user',
          plan: 'trial',
          subscription_active: true,
        },
      },
    )

    // Agent chat page — show thread with API reply already stored
    await page.goto(`${APP}/agents/${agentId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForTimeout(4000)
    try {
      await page
        .locator('.agent-chat-messages, .chat-messages, [class*="message"]')
        .last()
        .scrollIntoViewIfNeeded({ timeout: 3000 })
    } catch {
      /* ignore */
    }
    // Scroll chat to bottom for latest assistant reply
    await page.evaluate(() => {
      const sc =
        document.querySelector('.agent-chat-messages, .chat-scroll, main, [class*="messages"]') ||
        document.scrollingElement
      if (sc) sc.scrollTop = sc.scrollHeight
    })
    await page.waitForTimeout(800)
    const chatShot = path.join(SHOTS, 'status_update_chat.png')
    await page.screenshot({ path: chatShot, fullPage: true })
    report.screenshots.push(chatShot)
    console.log('SHOT chat', chatShot)

    const bannerText = await page.evaluate(() => {
      const els = [
        ...document.querySelectorAll(
          '.live-ops-banner, [class*="LiveOps"], [class*="ops-banner"], [class*="opsBanner"]',
        ),
      ]
      return els.map((el) => (el.innerText || '').slice(0, 600))
    })
    report.steps.ops_banner_dom = { texts: bannerText }
    report.steps.chat_page_snippet = (await page.locator('body').innerText()).slice(-2000)

    // Dashboard for ops banner
    await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.waitForTimeout(2500)
    const dashShot = path.join(SHOTS, 'status_update_dashboard_ops.png')
    await page.screenshot({ path: dashShot, fullPage: true })
    report.screenshots.push(dashShot)
    report.steps.ops_banner_dashboard = await page.evaluate(() => {
      const candidates = [
        ...document.querySelectorAll(
          '.live-ops-banner, [class*="LiveOps"], [class*="ops-banner"], [class*="opsBanner"]',
        ),
      ]
      return candidates.map((el) => (el.innerText || '').slice(0, 500))
    })
    console.log('SHOT dashboard', dashShot)

    // Try /ops route if exists
    try {
      await page.goto(`${APP}/ops`, { waitUntil: 'domcontentloaded', timeout: 20000 })
      await page.waitForTimeout(1500)
      if (!/login/i.test(page.url())) {
        const opsShot = path.join(SHOTS, 'status_update_ops_page.png')
        await page.screenshot({ path: opsShot, fullPage: true })
        report.screenshots.push(opsShot)
        report.steps.ops_page = {
          url: page.url(),
          body: (await page.locator('body').innerText()).slice(0, 1500),
        }
      }
    } catch {
      /* optional */
    }
  } catch (e) {
    report.steps.browser = { error: e.message }
    console.error('Browser error', e)
  } finally {
    await browser.close()
  }

  const ok =
    report.chat?.status >= 200 &&
    report.chat?.status < 300 &&
    report.chat?.reply &&
    report.human_facing?.addresses_human === true

  report.summary = {
    ok,
    phase: 'complete',
    chat_status: report.chat?.status,
    reply_preview: (report.chat?.reply || '').slice(0, 800),
    full_reply: report.chat?.reply || '',
    addresses_human: report.human_facing?.addresses_human,
    looks_like_status: report.human_facing?.looks_like_status,
    ops_events: report.ops?.event_count ?? 0,
    ops_api_ok: report.ops?.status === 200,
    activity_ok: report.activity?.status === 200,
    screenshots: report.screenshots,
    skills_used: report.chat?.skills,
  }

  fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
  console.log('\n=== SUMMARY ===')
  console.log(JSON.stringify(report.summary, null, 2))
  console.log('Report written', REPORT)
  process.exit(ok ? 0 : 2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
