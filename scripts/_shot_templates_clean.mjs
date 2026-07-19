/**
 * Login + screenshot templates with top-up modal dismissed if present.
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`

fs.mkdirSync(SHOTS, { recursive: true })
const creds = JSON.parse(fs.readFileSync(CREDS, 'utf8'))

async function pageLogin(page) {
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
      // snooze meter top-up modal (AppLayout SNOOZE_KEY)
      try {
        localStorage.setItem('topup_modal_snooze_until', String(Date.now() + 7 * 24 * 3600 * 1000))
      } catch {}
      return { ok: true, status: r.status, user_id: j.user?.id }
    },
    { email: creds.email, password: creds.password },
  )
}

async function dismissModals(page) {
  // close buttons / escape
  for (const sel of [
    '.ant-modal-close',
    'button.ant-modal-close',
    '[aria-label="Close"]',
    '.ant-modal-wrap button:has-text("×")',
  ]) {
    const btn = page.locator(sel).first()
    if (await btn.isVisible().catch(() => false)) {
      await btn.click({ timeout: 2000 }).catch(() => {})
      await page.waitForTimeout(400)
    }
  }
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(300)
  // click mask
  const mask = page.locator('.ant-modal-wrap, .ant-modal-mask').first()
  if (await mask.isVisible().catch(() => false)) {
    await page.mouse.click(20, 20).catch(() => {})
    await page.keyboard.press('Escape').catch(() => {})
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  try {
    await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(1200)
    let login = await pageLogin(page)
    if (!login.ok && login.status === 429) {
      console.warn('429 wait 50s')
      await page.waitForTimeout(50000)
      login = await pageLogin(page)
    }
    console.log('login', login)
    if (!login.ok) {
      process.exitCode = 1
      return
    }
    const url = `${APP}/templates`
    for (let i = 0; i < 3; i++) {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
      await page.waitForTimeout(2800)
      if (!page.url().includes('/login')) break
      console.warn('bounce to login, re-auth', i)
      login = await pageLogin(page)
      console.log('re-login', login)
      if (!login.ok) {
        if (login.status === 429) await page.waitForTimeout(45000)
        else break
      }
    }
    await dismissModals(page)
    await page.waitForTimeout(800)
    await dismissModals(page)
    await page
      .waitForSelector('text=Main AI Orchestrator, .ant-card', { timeout: 15000 })
      .catch(() => {})
    // scroll a bit to show more cards
    await page.evaluate(() => window.scrollTo(0, 200))
    await page.waitForTimeout(400)
    const out = path.join(SHOTS, 'templates_page_live.png')
    const out2 = path.join(SHOTS, 'a_templates.png')
    await page.screenshot({ path: out, fullPage: true })
    await page.screenshot({ path: out2, fullPage: false })
    const cards = await page.locator('.ant-card').count()
    console.log('url', page.url())
    console.log('cards', cards)
    console.log('screenshot', out)
    console.log('viewport_shot', out2)
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
