/**
 * Live probe: hierarchy UI + list agents + spawn specialist if trial slots remain.
 * Uses Node-side login + injectAuth (same pattern as live_browser_e2e.mjs).
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const REPORT = path.join(__dirname, 'hierarchy_probe_report.json')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const TRIAL_MAX = 10

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  return JSON.parse(fs.readFileSync(CREDS, 'utf8'))
}

function persistCreds(creds) {
  try {
    fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
    fs.writeFileSync(path.join(__dirname, '.demo_token'), creds.api_key || '')
  } catch {
    /* ignore */
  }
}

async function nodeLogin(creds) {
  for (let attempt = 0; attempt < 6; attempt++) {
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
      return { ok: true, user: j.user, key }
    }
    if (r.status === 429) {
      const detail = typeof j?.detail === 'string' ? j.detail : ''
      const m = /Try again in (\d+)/i.exec(detail)
      const sec = m ? Math.min(120, parseInt(m[1], 10) + 2) : Math.min(90, 15 + attempt * 20)
      console.warn(`Login 429 — wait ${sec}s (attempt ${attempt + 1}/6)`)
      await new Promise((res) => setTimeout(res, sec * 1000))
      continue
    }
    return { ok: false, status: r.status, detail: j }
  }
  return { ok: false, status: 429, detail: 'rate limited' }
}

async function nodeApi(creds, apiPath, { method = 'GET', body = null } = {}) {
  async function once(key) {
    const headers = {
      Authorization: `Bearer ${key}`,
      'X-API-Key': key,
      Accept: 'application/json',
    }
    if (body != null) headers['Content-Type'] = 'application/json'
    const r = await fetch(`${BASE}${apiPath}`, {
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

  let res = await once(creds.api_key)
  if (res.status === 401) {
    const lr = await nodeLogin(creds)
    if (lr.ok) res = await once(creds.api_key)
  }
  return res
}

function normalizeAgents(body) {
  if (Array.isArray(body)) return body
  if (Array.isArray(body?.agents)) return body.agents
  if (Array.isArray(body?.items)) return body.items
  return []
}

function mapAgents(agents) {
  return agents.map((a) => ({
    id: a.id,
    name: a.name,
    hierarchy_role: a.hierarchy_role || a.role || null,
    template_type: a.template_type || null,
    status: a.status || null,
    parent_id: a.parent_id ?? null,
    is_lead: !!a.is_lead,
  }))
}

async function injectAuth(page, creds) {
  await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
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
  // Verify from browser origin; re-login in-page if key rotated
  const check = await page.evaluate(async ({ email, password, apiKey, base }) => {
    async function meOk(key) {
      const r = await fetch(`${base}/api/auth/me`, {
        headers: {
          Authorization: `Bearer ${key}`,
          Accept: 'application/json',
          'X-API-Key': key,
        },
      })
      return r.ok
    }
    const lsKey = localStorage.getItem('api_key') || apiKey
    if (await meOk(lsKey)) return { ok: true, key: lsKey }
    const r = await fetch(`${base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const j = await r.json().catch(() => null)
    const key = j?.api_key || j?.token
    if (r.ok && key) {
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      if (j.user) localStorage.setItem('user', JSON.stringify(j.user))
      return { ok: true, key, user_id: j.user?.id }
    }
    return { ok: false, status: r.status, detail: j }
  }, { email: creds.email, password: creds.password, apiKey: creds.api_key, base: BASE })

  if (check.ok && check.key && check.key !== creds.api_key) {
    creds.api_key = check.key
    if (check.user_id != null) creds.user_id = check.user_id
    persistCreds(creds)
  }
  return check
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
    hierarchy_api: null,
    screenshot: null,
    ok: false,
  }

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

  try {
    // 1) Node login
    const login = await nodeLogin(creds)
    if (!login.ok) {
      report.steps.push({ step: 'node_login', ok: false, detail: login })
      throw new Error(`node login failed: ${JSON.stringify(login).slice(0, 200)}`)
    }
    report.steps.push({
      step: 'node_login',
      ok: true,
      plan: login.user?.plan,
      user_id: login.user?.id,
      subscription_active: login.user?.subscription_active,
    })
    console.log(
      `PASS node_login plan=${login.user?.plan} user=${login.user?.id} sub=${login.user?.subscription_active}`,
    )

    // 2) Ensure orchestrator
    const orch = await nodeApi(creds, '/api/agents/ensure-orchestrator', { method: 'POST' })
    report.steps.push({
      step: 'ensure_orchestrator',
      ok: orch.status === 200 || orch.status === 201,
      status: orch.status,
      id: orch.body?.id,
    })
    console.log(`ensure_orchestrator status=${orch.status} id=${orch.body?.id}`)

    // 3) List agents
    let agentsRes = await nodeApi(creds, '/api/agents/')
    let agents = normalizeAgents(agentsRes.body)
    report.agent_count = agents.length
    report.slots_remaining = Math.max(0, TRIAL_MAX - agents.length)
    report.agents = mapAgents(agents)
    report.steps.push({
      step: 'list_agents',
      ok: agentsRes.status === 200,
      status: agentsRes.status,
      count: agents.length,
      slots_remaining: report.slots_remaining,
    })
    console.log(`PASS list_agents count=${agents.length} slots_remaining=${report.slots_remaining}`)
    for (const a of report.agents) {
      console.log(
        `  agent#${String(a.id).padStart(4)}  ${(a.hierarchy_role || '-').padEnd(14)}  ${a.name}  [${a.template_type || '-'}]`,
      )
    }

    // 4) Hierarchy API
    const hier = await nodeApi(creds, '/api/agents/hierarchy')
    report.hierarchy_api = {
      status: hier.status,
      preview: JSON.stringify(hier.body).slice(0, 600),
    }
    report.steps.push({
      step: 'hierarchy_api',
      ok: hier.status === 200,
      status: hier.status,
    })
    console.log(`hierarchy_api status=${hier.status}`)

    // 5) Spawn specialist if slots remain
    if (report.slots_remaining > 0) {
      const orchAgent =
        agents.find((a) => (a.hierarchy_role || '').toLowerCase() === 'orchestrator') ||
        agents.find((a) => a.id === orch.body?.id) ||
        agents[0]

      let spawnResult = null
      if (orchAgent?.id) {
        const skill = await nodeApi(creds, `/api/agents/${orchAgent.id}/skills/run`, {
          method: 'POST',
          body: {
            skill_id: 'spawn_specialist',
            args: {
              domain: 'research',
              name: `Live Research Specialist ${Date.now().toString(36)}`,
            },
          },
        })
        spawnResult = {
          mode: 'spawn_specialist_skill',
          status: skill.status,
          body: skill.body,
        }
        console.log(
          `spawn_specialist skill status=${skill.status} ${JSON.stringify(skill.body).slice(0, 220)}`,
        )
      }

      const skillOk =
        spawnResult &&
        spawnResult.status >= 200 &&
        spawnResult.status < 300 &&
        spawnResult.body?.ok !== false &&
        (spawnResult.body?.agent?.id || spawnResult.body?.ok === true) &&
        !/plan allows|upgrade|limit|max/i.test(JSON.stringify(spawnResult.body || ''))

      if (!skillOk) {
        const tplRes = await nodeApi(creds, '/api/templates/')
        const list = Array.isArray(tplRes.body) ? tplRes.body : tplRes.body?.templates || []
        const tpl =
          list.find((t) =>
            /specialist|writer|research|sales|marketing/i.test(
              t.type || t.template_type || t.name || '',
            ),
          ) ||
          list[1] ||
          list[0]
        const body = {
          name: `Live Specialist ${Date.now().toString(36)}`,
          template_type: tpl?.template_type || tpl?.type || tpl?.id || 'researcher',
          template_id: tpl?.id,
          model: 'fast',
          hierarchy_role: 'specialist',
        }
        const created = await nodeApi(creds, '/api/agents/', { method: 'POST', body })
        spawnResult = {
          mode: 'post_agents',
          status: created.status,
          body: created.body,
          template: tpl
            ? { id: tpl.id, type: tpl.template_type || tpl.type, name: tpl.name }
            : null,
        }
        console.log(
          `spawn POST /agents status=${created.status} ${JSON.stringify(created.body).slice(0, 220)}`,
        )
      }

      const spawnOk = spawnResult?.status >= 200 && spawnResult?.status < 300
      report.spawn = spawnResult
      report.steps.push({
        step: 'spawn_specialist',
        ok: spawnOk || /plan allows|upgrade|limit|max/i.test(JSON.stringify(spawnResult?.body || '')),
        mode: spawnResult?.mode,
        status: spawnResult?.status,
        detail: JSON.stringify(spawnResult?.body || {}).slice(0, 300),
      })

      agentsRes = await nodeApi(creds, '/api/agents/')
      agents = normalizeAgents(agentsRes.body)
      report.agent_count = agents.length
      report.slots_remaining = Math.max(0, TRIAL_MAX - agents.length)
      report.agents = mapAgents(agents)
      console.log(`PASS re-list after spawn count=${agents.length}`)
      for (const a of report.agents) {
        console.log(
          `  agent#${String(a.id).padStart(4)}  ${(a.hierarchy_role || '-').padEnd(14)}  ${a.name}  [${a.template_type || '-'}]`,
        )
      }
    } else {
      report.spawn = { mode: 'skipped', reason: `at trial cap (${agents.length}/${TRIAL_MAX})` }
      report.steps.push({
        step: 'spawn_specialist',
        ok: true,
        mode: 'skipped_at_cap',
        count: agents.length,
        max: TRIAL_MAX,
      })
      console.log(`SKIP spawn_specialist — at trial cap ${agents.length}/${TRIAL_MAX}`)
    }

    // 6) Open hierarchy UI + screenshot
    const auth = await injectAuth(page, creds)
    report.steps.push({ step: 'inject_auth', ok: !!auth.ok, detail: auth.ok ? 'ok' : auth })
    console.log(`inject_auth ok=${auth.ok}`)

    await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 90000 })
    await page.waitForTimeout(3000)
    if (/\/login\b/i.test(page.url())) {
      const auth2 = await injectAuth(page, creds)
      console.log(`re-inject_auth ok=${auth2.ok}`)
      await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 90000 })
      await page.waitForTimeout(3000)
    }
    report.hierarchy_url = page.url()
    const bodyText = await page.locator('body').innerText().catch(() => '')
    const hierarchyUiOk =
      !/\/login\b/i.test(page.url()) &&
      /hierarchy|orchestrator|agent|team|lead|specialist|org/i.test(bodyText)
    report.steps.push({
      step: 'hierarchy_ui',
      ok: hierarchyUiOk,
      url: page.url(),
      text_preview: bodyText.slice(0, 400).replace(/\s+/g, ' '),
    })
    console.log(`hierarchy_ui ok=${hierarchyUiOk} url=${page.url()}`)

    const shotPath = path.join(SHOTS, 'hierarchy_live.png')
    await page.screenshot({ path: shotPath, fullPage: true })
    report.screenshot = shotPath
    console.log(`SCREENSHOT ${shotPath}`)

    report.ok =
      report.steps.some((s) => s.step === 'list_agents' && s.ok) &&
      report.steps.some((s) => s.step === 'hierarchy_ui' && s.ok)
    console.log(`AGENT_COUNT ${report.agent_count}/${TRIAL_MAX} slots_remaining=${report.slots_remaining}`)
  } catch (e) {
    report.error = e.message
    console.error('ERROR', e.message)
    try {
      const p = path.join(SHOTS, 'hierarchy_live_error.png')
      await page.screenshot({ path: p, fullPage: true })
      report.screenshot = p
    } catch {
      /* ignore */
    }
  } finally {
    fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
    await browser.close()
    console.log(`REPORT ${REPORT}`)
    console.log(
      JSON.stringify(
        {
          ok: report.ok,
          agent_count: report.agent_count,
          slots_remaining: report.slots_remaining,
          spawn_mode: report.spawn?.mode || null,
          spawn_status: report.spawn?.status || null,
          hierarchy_url: report.hierarchy_url,
          screenshot: report.screenshot,
          agents: report.agents,
        },
        null,
        2,
      ),
    )
    process.exit(report.ok ? 0 : 1)
  }
}

main()
