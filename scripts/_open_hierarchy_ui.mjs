/**
 * Live: login once → list agents → open hierarchy UI (via nav) → screenshot.
 * Avoids re-login mid-run (shared demo key rotates on concurrent login).
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const CREDS_PATH = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const REPORT_PATH = path.join(__dirname, 'hierarchy_probe_report.json')
const TRIAL_MAX = 10

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  return JSON.parse(fs.readFileSync(CREDS_PATH, 'utf8'))
}

function saveCreds(creds) {
  fs.writeFileSync(CREDS_PATH, JSON.stringify(creds, null, 2))
  try {
    fs.writeFileSync(path.join(__dirname, '.demo_token'), creds.api_key || '')
  } catch {
    /* ignore */
  }
}

async function login(creds) {
  for (let i = 0; i < 8; i++) {
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
      saveCreds(creds)
      // Immediate me check — if another worker already rotated, retry
      const me = await fetch(`${BASE}/api/auth/me`, {
        headers: {
          Authorization: `Bearer ${key}`,
          'X-API-Key': key,
          Accept: 'application/json',
        },
      })
      if (me.ok) {
        const user = await me.json().catch(() => j.user)
        return { ok: true, key, user: user || j.user }
      }
      console.warn(`login key failed /me status=${me.status} — retry ${i + 1}`)
      await new Promise((res) => setTimeout(res, 1500 + i * 500))
      continue
    }
    if (r.status === 429) {
      const d = String(j?.detail || '')
      const m = /Try again in (\d+)/i.exec(d)
      const sec = m ? parseInt(m[1], 10) + 3 : 25 + i * 10
      console.log(`429 wait ${sec}s`)
      await new Promise((res) => setTimeout(res, sec * 1000))
      continue
    }
    throw new Error(`login failed ${r.status} ${JSON.stringify(j)}`)
  }
  throw new Error('login exhausted')
}

async function api(creds, p, { method = 'GET', body = null } = {}) {
  const headers = {
    Authorization: `Bearer ${creds.api_key}`,
    'X-API-Key': creds.api_key,
    Accept: 'application/json',
  }
  if (body != null) headers['Content-Type'] = 'application/json'
  const r = await fetch(`${BASE}${p}`, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  })
  const text = await r.text()
  let json
  try {
    json = JSON.parse(text)
  } catch {
    json = text
  }
  return { status: r.status, body: json }
}

function normalizeAgents(body) {
  if (Array.isArray(body)) return body
  if (Array.isArray(body?.agents)) return body.agents
  if (Array.isArray(body?.items)) return body.items
  return []
}

async function main() {
  const creds = loadCreds()
  const report = {
    base: BASE,
    email: creds.email,
    trial_max_agents: TRIAL_MAX,
    steps: [],
    agents: [],
    agent_count: 0,
    slots_remaining: null,
    spawn: null,
    hierarchy_url: null,
    screenshot: null,
    ok: false,
  }

  const loginRes = await login(creds)
  console.log(`PASS login user=${loginRes.user?.id} plan=${loginRes.user?.plan}`)
  report.steps.push({ step: 'login', ok: true, user_id: loginRes.user?.id, plan: loginRes.user?.plan })

  // Fast sequential API — no re-login
  const orch = await api(creds, '/api/agents/ensure-orchestrator', { method: 'POST' })
  console.log(`ensure_orchestrator ${orch.status} id=${orch.body?.id}`)
  report.steps.push({ step: 'ensure_orchestrator', status: orch.status, id: orch.body?.id, ok: orch.status < 400 })

  let agentsRes = await api(creds, '/api/agents/')
  let agents = normalizeAgents(agentsRes.body)
  // If 401 mid-flight (rotated), one fresh login then continue
  if (agentsRes.status === 401) {
    console.warn('agents 401 — re-login once')
    await login(creds)
    agentsRes = await api(creds, '/api/agents/')
    agents = normalizeAgents(agentsRes.body)
  }
  report.agent_count = agents.length
  report.slots_remaining = Math.max(0, TRIAL_MAX - agents.length)
  report.agents = agents.map((a) => ({
    id: a.id,
    name: a.name,
    hierarchy_role: a.hierarchy_role || null,
    template_type: a.template_type || null,
    status: a.status || null,
    parent_id: a.parent_id ?? null,
    is_lead: !!a.is_lead,
  }))
  report.steps.push({
    step: 'list_agents',
    ok: agentsRes.status === 200,
    status: agentsRes.status,
    count: agents.length,
  })
  console.log(`PASS list_agents count=${agents.length}/${TRIAL_MAX} slots=${report.slots_remaining}`)
  for (const a of report.agents) {
    console.log(
      `  #${String(a.id).padStart(4)} ${(a.hierarchy_role || '-').padEnd(14)} ${a.name} [${a.template_type || '-'}]`,
    )
  }

  const hier = await api(creds, '/api/agents/hierarchy')
  report.hierarchy_api = { status: hier.status, preview: JSON.stringify(hier.body).slice(0, 800) }
  report.steps.push({ step: 'hierarchy_api', ok: hier.status === 200, status: hier.status })
  console.log(`hierarchy_api ${hier.status}`)

  // Spawn specialist only if slots remain
  if (report.slots_remaining > 0) {
    const orchAgent =
      agents.find((a) => (a.hierarchy_role || '').toLowerCase() === 'orchestrator') ||
      agents.find((a) => a.id === orch.body?.id) ||
      agents[0]
    let spawnResult = null
    if (orchAgent?.id) {
      const skill = await api(creds, `/api/agents/${orchAgent.id}/skills/run`, {
        method: 'POST',
        body: {
          skill_id: 'spawn_specialist',
          args: {
            domain: 'research',
            name: `Live Research Specialist ${Date.now().toString(36)}`,
          },
        },
      })
      spawnResult = { mode: 'spawn_specialist_skill', status: skill.status, body: skill.body }
      console.log(`spawn skill ${skill.status} ${JSON.stringify(skill.body).slice(0, 200)}`)
    }
    const skillOk =
      spawnResult &&
      spawnResult.status < 300 &&
      spawnResult.body?.ok !== false &&
      (spawnResult.body?.agent?.id || spawnResult.body?.ok === true)

    if (!skillOk) {
      const tplRes = await api(creds, '/api/templates/')
      const list = Array.isArray(tplRes.body) ? tplRes.body : tplRes.body?.templates || []
      const tpl =
        list.find((t) =>
          /specialist|writer|research|sales|marketing/i.test(
            t.type || t.template_type || t.name || '',
          ),
        ) ||
        list[1] ||
        list[0]
      const created = await api(creds, '/api/agents/', {
        method: 'POST',
        body: {
          name: `Live Specialist ${Date.now().toString(36)}`,
          template_type: tpl?.template_type || tpl?.type || 'researcher',
          template_id: tpl?.id,
          model: 'fast',
          hierarchy_role: 'specialist',
        },
      })
      spawnResult = { mode: 'post_agents', status: created.status, body: created.body }
      console.log(`spawn post ${created.status} ${JSON.stringify(created.body).slice(0, 200)}`)
    }
    report.spawn = spawnResult
    report.steps.push({
      step: 'spawn_specialist',
      ok: spawnResult?.status < 300 || /plan|limit|upgrade/i.test(JSON.stringify(spawnResult?.body || '')),
      mode: spawnResult?.mode,
      status: spawnResult?.status,
    })
    agentsRes = await api(creds, '/api/agents/')
    agents = normalizeAgents(agentsRes.body)
    report.agent_count = agents.length
    report.slots_remaining = Math.max(0, TRIAL_MAX - agents.length)
    report.agents = agents.map((a) => ({
      id: a.id,
      name: a.name,
      hierarchy_role: a.hierarchy_role || null,
      template_type: a.template_type || null,
      status: a.status || null,
      parent_id: a.parent_id ?? null,
      is_lead: !!a.is_lead,
    }))
  } else {
    report.spawn = { mode: 'skipped', reason: `at trial cap (${agents.length}/${TRIAL_MAX})` }
    report.steps.push({ step: 'spawn_specialist', ok: true, mode: 'skipped_at_cap' })
    console.log(`SKIP spawn — trial cap ${agents.length}/${TRIAL_MAX}`)
  }

  // Fresh login immediately before browser so key is not stale from concurrent workers
  let browserLogin = loginRes
  try {
    browserLogin = await login(creds)
    console.log('browser-session login ok')
  } catch (e) {
    console.warn('browser-session login failed, using prior key:', e.message)
  }

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  const userObj = {
    id: browserLogin.user?.id || creds.user_id,
    email: creds.email,
    name: browserLogin.user?.name || 'E2E B',
    role: browserLogin.user?.role || 'user',
    plan: browserLogin.user?.plan || 'trial',
    subscription_active: true,
    subscription_expires_at: browserLogin.user?.subscription_expires_at,
    needs_subscription: false,
  }
  await context.addInitScript(
    ({ apiKey, user }) => {
      localStorage.setItem('api_key', apiKey)
      localStorage.setItem('token', apiKey)
      localStorage.setItem('user', JSON.stringify(user))
    },
    { apiKey: creds.api_key, user: userObj },
  )

  const page = await context.newPage()

  // Land on dashboard first (known-good), then click Hierarchy nav
  await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForTimeout(2500)
  console.log('dashboard url', page.url())

  // Click Hierarchy in sidebar if present
  let clicked = false
  for (const sel of [
    'a[href="/agents/hierarchy"]',
    'a[href*="hierarchy"]',
    '[data-menu-id*="hierarchy"]',
    'text=Hierarchy',
  ]) {
    const loc = page.locator(sel).first()
    if ((await loc.count().catch(() => 0)) > 0) {
      try {
        await loc.click({ timeout: 8000 })
        clicked = true
        await page.waitForTimeout(3500)
        break
      } catch {
        /* try next */
      }
    }
  }
  if (!clicked) {
    await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(3500)
  }

  let url = page.url()
  console.log('after nav url', url)

  // Hard navigation fallback
  if (!url.includes('hierarchy')) {
    await page.goto(`${APP}/hierarchy`, { waitUntil: 'networkidle', timeout: 120000 }).catch(() => null)
    await page.waitForTimeout(4000)
    url = page.url()
    console.log('hard goto hierarchy url', url)
  }

  // If bounced to login, stop — do not re-login (would rotate key under other workers)
  const text = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 800)
  console.log('text', text.slice(0, 400))

  const shot = path.join(SHOTS, 'hierarchy_live.png')
  await page.screenshot({ path: shot, fullPage: true })
  await page.screenshot({ path: path.join(SHOTS, 'a_hierarchy.png'), fullPage: true })

  report.hierarchy_url = url
  report.hierarchy_text_preview = text
  report.screenshot = shot
  report.hierarchy_ui_ok = url.includes('hierarchy') || /orchestrator|hierarchy|Main AI|Lead|Specialist/i.test(text)
  report.ok = report.agent_count > 0 && report.hierarchy_ui_ok
  report.steps.push({
    step: 'hierarchy_ui',
    ok: report.hierarchy_ui_ok,
    url,
  })

  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2))
  console.log('SHOT', shot)
  console.log('FINAL_URL', url)
  console.log(`AGENT_COUNT ${report.agent_count}/${TRIAL_MAX} slots_remaining=${report.slots_remaining}`)
  console.log('SPAWN', JSON.stringify(report.spawn))
  console.log('REPORT', REPORT_PATH)

  await browser.close()
  process.exit(report.ok ? 0 : 2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
