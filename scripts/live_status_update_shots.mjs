/** Fresh-login screenshots for status_update live test */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const SHOTS = path.join(__dirname, 'live-screenshots')
const CREDS_PATH = path.join(__dirname, '.demo_login.json')
const META = path.join(__dirname, 'live_status_update_shots_meta.json')

fs.mkdirSync(SHOTS, { recursive: true })
const CREDS = JSON.parse(fs.readFileSync(CREDS_PATH, 'utf8'))

async function login() {
  for (let i = 0; i < 6; i++) {
    const r = await fetch(`${BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email: CREDS.email, password: CREDS.password }),
    })
    const j = await r.json().catch(() => null)
    const key = j?.api_key || j?.token
    if (r.ok && key) {
      CREDS.api_key = key
      if (j.user?.id != null) CREDS.user_id = j.user.id
      fs.writeFileSync(CREDS_PATH, JSON.stringify(CREDS, null, 2))
      console.log('login ok')
      return key
    }
    if (r.status === 429) {
      console.log('429 wait')
      await new Promise((res) => setTimeout(res, 20000))
      continue
    }
    console.log('login fail', r.status, j)
    await new Promise((res) => setTimeout(res, 3000))
  }
  throw new Error('login failed')
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

try {
  await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })

  // Login entirely inside the page origin so SPA has a warm key
  const inPage = await page.evaluate(
    async ({ email, password, base }) => {
      for (let i = 0; i < 5; i++) {
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
          return { ok: true, key, user_id: j.user?.id, status: r.status }
        }
        if (r.status === 429) {
          await new Promise((res) => setTimeout(res, 15000 + i * 5000))
          continue
        }
        return { ok: false, status: r.status, j }
      }
      return { ok: false, status: 0 }
    },
    { email: CREDS.email, password: CREDS.password, base: BASE },
  )
  console.log('inPage login', inPage)
  if (!inPage.ok) throw new Error(`in-page login failed: ${JSON.stringify(inPage)}`)
  CREDS.api_key = inPage.key
  if (inPage.user_id != null) CREDS.user_id = inPage.user_id
  fs.writeFileSync(CREDS_PATH, JSON.stringify(CREDS, null, 2))

  // Resolve orchestrator in-page
  const agentInfo = await page.evaluate(async (base) => {
    const key = localStorage.getItem('api_key')
    const r = await fetch(`${base}/api/agents/`, {
      headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
    })
    const j = await r.json().catch(() => null)
    const list = Array.isArray(j) ? j : j?.agents || j?.items || []
    const orch =
      list.find((a) => a.is_orchestrator || a.hierarchy_role === 'orchestrator') || list[0]
    return { status: r.status, agentId: orch?.id, name: orch?.name, count: list.length }
  }, BASE)
  console.log('agentInfo', agentInfo)
  const agentId = agentInfo.agentId || CREDS.agent_id || 27

  await page.goto(`${APP}/agents/${agentId}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  })
  await page.waitForTimeout(5000)
  // recover if bounced to login
  if (/\/login\b/i.test(page.url())) {
    console.warn('bounced to login — re-auth in page')
    await page.evaluate(
      async ({ email, password, base }) => {
        const r = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        const j = await r.json().catch(() => null)
        const key = j?.api_key || j?.token
        if (r.ok && key) {
          localStorage.setItem('api_key', key)
          localStorage.setItem('token', key)
          if (j.user) localStorage.setItem('user', JSON.stringify(j.user))
        }
      },
      { email: CREDS.email, password: CREDS.password, base: BASE },
    )
    await page.goto(`${APP}/agents/${agentId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForTimeout(4000)
  }
  console.log('chat url', page.url())

  try {
    await page
      .locator('textarea.agent-chat-textarea, textarea[placeholder*="Message" i], textarea')
      .first()
      .waitFor({ state: 'visible', timeout: 20000 })
  } catch {
    /* ignore */
  }

  await page.evaluate(() => {
    const sc =
      document.querySelector('.agent-chat-messages, .chat-scroll, main, [class*="messages"]') ||
      document.scrollingElement
    if (sc) sc.scrollTop = sc.scrollHeight
  })
  await page.waitForTimeout(800)

  const chatShot = path.join(SHOTS, 'status_update_chat.png')
  await page.screenshot({ path: chatShot, fullPage: true })
  console.log('SHOT', chatShot)

  const bodySnippet = (await page.locator('body').innerText()).slice(0, 3000)
  console.log('BODY_START', bodySnippet.slice(0, 900))

  const banners = await page.evaluate(() =>
    [...document.querySelectorAll('[class*="ops"], [class*="Ops"], [class*="ticker"], [class*="banner"]')]
      .filter((e) => (e.innerText || '').trim().length > 5)
      .slice(0, 8)
      .map((e) => ({ cls: e.className?.toString?.().slice(0, 80), text: e.innerText.slice(0, 400) })),
  )
  console.log('BANNERS', JSON.stringify(banners).slice(0, 800))

  // Dashboard
  await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForTimeout(3000)
  if (/\/login\b/i.test(page.url())) {
    await page.evaluate(
      async ({ email, password, base }) => {
        const r = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        const j = await r.json().catch(() => null)
        const key = j?.api_key || j?.token
        if (r.ok && key) {
          localStorage.setItem('api_key', key)
          localStorage.setItem('token', key)
          if (j.user) localStorage.setItem('user', JSON.stringify(j.user))
        }
      },
      { email: CREDS.email, password: CREDS.password, base: BASE },
    )
    await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.waitForTimeout(2500)
  }
  console.log('dash url', page.url())
  const dashShot = path.join(SHOTS, 'status_update_dashboard_ops.png')
  await page.screenshot({ path: dashShot, fullPage: true })
  console.log('SHOT', dashShot)

  const banners2 = await page.evaluate(() =>
    [...document.querySelectorAll('[class*="ops"], [class*="Ops"], [class*="ticker"], [class*="banner"]')]
      .filter((e) => (e.innerText || '').trim().length > 5)
      .slice(0, 8)
      .map((e) => ({ cls: e.className?.toString?.().slice(0, 80), text: e.innerText.slice(0, 400) })),
  )
  const dashSnippet = (await page.locator('body').innerText()).slice(0, 1500)
  console.log('DASH_BODY', dashSnippet.slice(0, 700))

  // ops + activity from page origin
  const ops = await page.evaluate(async (base) => {
    const key = localStorage.getItem('api_key') || localStorage.getItem('token')
    const r = await fetch(`${base}/api/ops/live?limit=12`, {
      headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
    })
    const j = await r.json().catch(() => null)
    return {
      status: r.status,
      open_tasks: j?.snapshot?.open_tasks,
      events: (j?.events || []).slice(0, 10).map((e) => ({
        id: e.id,
        kind: e.kind,
        status: e.status,
        title: e.title,
        detail: (e.detail || '').slice(0, 180),
      })),
    }
  }, BASE)
  console.log('OPS', JSON.stringify(ops, null, 2))

  const act = await page.evaluate(
    async ({ base, agentId }) => {
      const key = localStorage.getItem('api_key') || localStorage.getItem('token')
      const r = await fetch(`${base}/api/agents/${agentId}/activity`, {
        headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
      })
      const j = await r.json().catch(() => null)
      const list = Array.isArray(j) ? j : j?.activity || j?.items || []
      return {
        status: r.status,
        recent: (list || []).slice(0, 10).map((a) => ({
          type: a.type || a.kind,
          message: (a.message || a.detail || a.title || '').slice(0, 160),
          created_at: a.created_at,
        })),
      }
    },
    { base: BASE, agentId },
  )
  console.log('ACTIVITY', JSON.stringify(act, null, 2).slice(0, 2000))

  fs.writeFileSync(
    META,
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        agentId,
        chat_url: page.url(),
        banners,
        banners2,
        ops,
        act,
        bodySnippet: bodySnippet.slice(0, 2000),
        dashSnippet: dashSnippet.slice(0, 1000),
        screenshots: [chatShot, dashShot],
      },
      null,
      2,
    ),
  )
  console.log('meta written', META)
} finally {
  await browser.close()
}
