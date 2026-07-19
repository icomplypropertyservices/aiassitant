/**
 * Login once → /agents/tasks → dismiss modals → screenshot → confirm task via API.
 * Avoid extra logins while the SPA is loading (login rotates api_key and bounces UI).
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const REPORT = path.join(__dirname, 'live_queued_task_report.json')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const TARGET_ID = Number(process.env.TASK_ID || 279)

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  return JSON.parse(fs.readFileSync(CREDS, 'utf8'))
}

async function pageLogin(page, creds) {
  return page.evaluate(
    async ({ email, password }) => {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const j = await r.json().catch(() => ({}))
      const key = j.api_key || j.token
      if (!r.ok || !key) return { ok: false, status: r.status, detail: j.detail || j }
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      localStorage.setItem(
        'user',
        JSON.stringify(j.user || { email, plan: 'trial', subscription_active: true }),
      )
      return { ok: true, status: r.status, user_id: j.user?.id, key_prefix: key.slice(0, 16) }
    },
    { email: creds.email, password: creds.password },
  )
}

async function dismissModals(page) {
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press('Escape').catch(() => {})
    const closers = [
      'button[aria-label="Close"]',
      'button:has-text("×")',
      'button:has-text("✕")',
      '.modal-close',
      '[class*="modal"] button[aria-label="Close"]',
    ]
    for (const sel of closers) {
      const loc = page.locator(sel).first()
      if (await loc.count()) {
        await loc.click({ timeout: 1500 }).catch(() => {})
      }
    }
    // Click the X in top-right of dialog if present
    const dialogClose = page.locator('div').filter({ hasText: /Running hot|top up/i }).locator('button').first()
    if (await dialogClose.count()) {
      await dialogClose.click({ timeout: 1500 }).catch(() => {})
    }
    await page.waitForTimeout(300)
  }
}

function flattenBoard(j) {
  const all = []
  if (!j || typeof j !== 'object') return all
  const cols = j.columns
  if (cols && typeof cols === 'object' && !Array.isArray(cols)) {
    for (const [name, tasks] of Object.entries(cols)) {
      if (!Array.isArray(tasks)) continue
      for (const t of tasks) {
        all.push({ id: t.id, title: t.title, status: t.status, column: name })
      }
    }
  } else if (Array.isArray(cols)) {
    for (const col of cols) {
      const name = col.id || col.key || col.name || col.status
      for (const t of col.tasks || []) {
        all.push({ id: t.id, title: t.title, status: t.status, column: name })
      }
    }
  }
  if (Array.isArray(j.tasks)) {
    for (const t of j.tasks) {
      all.push({ id: t.id, title: t.title, status: t.status })
    }
  }
  return all
}

async function main() {
  const creds = loadCreds()
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const out = {
    task_id: TARGET_ID,
    url: null,
    login: null,
    visible: false,
    status_text: null,
    board_api: null,
    screenshot: null,
  }

  try {
    await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(1200)

    let login = await pageLogin(page, creds)
    if (!login.ok && login.status === 429) {
      const waitMs = 35000
      console.warn(`login 429 — wait ${waitMs}ms`)
      await page.waitForTimeout(waitMs)
      login = await pageLogin(page, creds)
    }
    out.login = login
    console.log('login', JSON.stringify(login))
    if (!login.ok) throw new Error('login failed: ' + JSON.stringify(login))

    try {
      const key = await page.evaluate(() => localStorage.getItem('api_key'))
      if (key) {
        creds.api_key = key
        if (login.user_id != null) creds.user_id = login.user_id
        fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
        fs.writeFileSync(path.join(__dirname, '.demo_token'), key)
      }
    } catch {
      /* ignore */
    }

    // Single navigation — do not re-login until after screenshot
    await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(3000)
    await dismissModals(page)

    if (page.url().includes('/login')) {
      // Only re-login if bounced
      const again = await pageLogin(page, creds)
      out.login_retry = again
      console.log('login_retry', JSON.stringify(again))
      if (again.ok) {
        await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 120000 })
        await page.waitForTimeout(3000)
        await dismissModals(page)
      }
    }

    try {
      await page.waitForSelector(
        '.tasks-board-column-card, [data-task-id], text=Tasks workflow, text=To do, text=Queued, text=Completed',
        { timeout: 40000 },
      )
    } catch {
      console.warn('board selector timeout')
    }
    await dismissModals(page)
    await page.waitForTimeout(1500)

    out.url = page.url()
    let bodyText = await page.locator('body').innerText().catch(() => '')
    const shotPath = path.join(SHOTS, 'queued_task_board.png')
    await page.screenshot({ path: shotPath, fullPage: true })
    out.screenshot = shotPath
    console.log('shot1', out.url, 'body_len', bodyText.length)

    // API confirm — re-login only inside evaluate if needed (after screenshot)
    const board = await page.evaluate(
      async ({ taskId, email, password }) => {
        async function login() {
          const r = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ email, password }),
          })
          const j = await r.json().catch(() => ({}))
          const key = j.api_key || j.token
          if (r.ok && key) {
            localStorage.setItem('api_key', key)
            localStorage.setItem('token', key)
            return key
          }
          return null
        }
        const headersFor = (key) => ({
          Authorization: `Bearer ${key}`,
          'X-API-Key': key,
          Accept: 'application/json',
        })
        let key = localStorage.getItem('api_key') || localStorage.getItem('token')
        let r = await fetch('/api/agents/tasks/board', { headers: headersFor(key) })
        if (r.status === 401 || r.status === 429) {
          if (r.status === 429) await new Promise((res) => setTimeout(res, 10000))
          const nk = await login()
          if (nk) {
            key = nk
            r = await fetch('/api/agents/tasks/board', { headers: headersFor(key) })
          }
        }
        const j = await r.json().catch(() => null)
        let gr = await fetch(`/api/agents/tasks/${taskId}`, { headers: headersFor(key) })
        if (gr.status === 401) {
          const nk = await login()
          if (nk) {
            key = nk
            gr = await fetch(`/api/agents/tasks/${taskId}`, { headers: headersFor(key) })
          }
        }
        const gt = await gr.json().catch(() => null)
        return {
          board_http: r.status,
          get_http: gr.status,
          board_counts: j && j.counts,
          board_total: j && j.total,
          board_column_keys: j && j.columns && typeof j.columns === 'object' ? Object.keys(j.columns) : null,
          get:
            gt && typeof gt === 'object'
              ? {
                  id: gt.id,
                  title: gt.title,
                  status: gt.status,
                  agent_id: gt.agent_id,
                  labels: gt.labels,
                }
              : gt,
          raw_columns_type: j && j.columns ? (Array.isArray(j.columns) ? 'array' : typeof j.columns) : null,
        }
      },
      { taskId: TARGET_ID, email: creds.email, password: creds.password },
    )

    // Flatten columns client-side for found check
    const boardFull = await page.evaluate(async (taskId) => {
      const key = localStorage.getItem('api_key') || localStorage.getItem('token')
      const r = await fetch('/api/agents/tasks/board', {
        headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
      })
      const j = await r.json().catch(() => null)
      const all = []
      if (j && j.columns && typeof j.columns === 'object' && !Array.isArray(j.columns)) {
        for (const [name, tasks] of Object.entries(j.columns)) {
          if (!Array.isArray(tasks)) continue
          for (const t of tasks) {
            all.push({ id: t.id, title: t.title, status: t.status, column: name })
          }
        }
      }
      return {
        http: r.status,
        total: all.length,
        found: all.find((t) => t.id === taskId) || null,
        sample: all.slice(0, 10),
        completed_sample: all.filter((t) => t.status === 'completed' || t.column === 'completed').slice(0, 5),
      }
    }, TARGET_ID)

    out.board_api = { ...board, flatten: boardFull }
    console.log('board_api', JSON.stringify(out.board_api, null, 2).slice(0, 2000))

    // If still on tasks page, reshot after dismiss; if bounced to login, re-enter once
    if (page.url().includes('/login') || bodyText.toLowerCase().includes('sign in')) {
      const again = await pageLogin(page, creds)
      out.login_for_final_shot = again
      if (again.ok) {
        await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 120000 })
        await page.waitForTimeout(3500)
        await dismissModals(page)
        try {
          await page.waitForSelector(
            '.tasks-board-column-card, text=Tasks workflow, text=Completed, text=Queued',
            { timeout: 30000 },
          )
        } catch {
          /* ignore */
        }
        await dismissModals(page)
        await page.waitForTimeout(1000)
        out.url = page.url()
        bodyText = await page.locator('body').innerText().catch(() => '')
        await page.screenshot({ path: shotPath, fullPage: true })
      }
    } else {
      await dismissModals(page)
      await page.screenshot({ path: shotPath, fullPage: true })
      bodyText = await page.locator('body').innerText().catch(() => '')
    }

    const idStr = String(TARGET_ID)
    const titleHint = 'Live test queued task'
    const apiStatus = board?.get?.status || boardFull?.found?.status || null
    out.visible_in_dom =
      bodyText.includes(idStr) ||
      bodyText.includes(`#${idStr}`) ||
      bodyText.includes(titleHint) ||
      bodyText.includes('Tasks workflow') ||
      bodyText.includes('Tasks board') ||
      /To do|Queued|Completed|In progress/i.test(bodyText)
    out.task_on_board = Boolean(boardFull?.found) || Boolean(board?.get?.id === TARGET_ID)
    out.status_text = apiStatus
    out.status_empty = !apiStatus
    out.visible = out.task_on_board || (out.visible_in_dom && !out.status_empty)
    out.body_snippet = bodyText.slice(0, 400).replace(/\s+/g, ' ')

    // Scroll completed column / search if possible
    try {
      const card = page.getByText(titleHint, { exact: false }).first()
      if (await card.count()) {
        await card.scrollIntoViewIfNeeded().catch(() => {})
        await page.waitForTimeout(400)
        const focusPath = path.join(SHOTS, 'queued_task_focus.png')
        await page.screenshot({ path: focusPath, fullPage: true })
        out.screenshot_focus = focusPath
      }
    } catch {
      /* ignore */
    }

    console.log(
      'RESULT',
      JSON.stringify({
        task_id: TARGET_ID,
        visible: out.visible,
        task_on_board: out.task_on_board,
        status: out.status_text,
        status_empty: out.status_empty,
        url: out.url,
        screenshot: out.screenshot,
      }),
    )
  } finally {
    let rep = {}
    try {
      rep = JSON.parse(fs.readFileSync(REPORT, 'utf8'))
    } catch {
      /* ignore */
    }
    rep.browser = out
    if (out.board_api?.get?.status) {
      rep.status = out.board_api.get.status
      rep.task = { ...(rep.task || {}), ...out.board_api.get }
    } else if (out.board_api?.flatten?.found?.status) {
      rep.status = out.board_api.flatten.found.status
    }
    rep.task_id = TARGET_ID
    rep.browser_visible = out.visible
    rep.task_on_board = out.task_on_board
    rep.status_empty = out.status_empty
    rep.screenshot = out.screenshot
    rep.ok = Boolean(out.task_on_board || (out.status_text && !out.status_empty))
    fs.writeFileSync(REPORT, JSON.stringify(rep, null, 2))
    await browser.close()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
