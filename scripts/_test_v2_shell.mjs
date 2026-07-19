/**
 * Visual smoke test for Frontend v2 mobile-first shell.
 * Run: node scripts/_test_v2_shell.mjs
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BASE = process.env.ABA_FE || 'http://127.0.0.1:5173'
const EMAIL = process.env.ABA_EMAIL || 'admin@local'
const PASS = process.env.ABA_PASSWORD || 'admin123'
const OUT = join(__dirname, 'live-screenshots', 'v2-shell')

mkdirSync(OUT, { recursive: true })

const report = {
  base: BASE,
  steps: [],
  ok: true,
  errors: [],
}

function step(name, data = {}) {
  report.steps.push({ name, ...data, at: new Date().toISOString() })
  console.log('·', name, data.detail || data.pass === false ? data : '')
}

async function login(page) {
  // Form rejects admin@local as email — use API session injection for local smoke
  const apiBase = process.env.ABA_API || 'http://127.0.0.1:8000'
  let session
  try {
    const res = await fetch(`${apiBase}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email: EMAIL, password: PASS }),
    })
    session = await res.json()
    if (!res.ok || !(session.api_key || session.token)) {
      step('login_api', { pass: false, status: res.status, session })
      report.ok = false
      return false
    }
  } catch (e) {
    step('login_api', { pass: false, detail: String(e) })
    report.ok = false
    return false
  }

  const key = session.api_key || session.token
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.evaluate(
    ({ key, user }) => {
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      if (user) localStorage.setItem('user', JSON.stringify(user))
    },
    { key, user: session.user },
  )
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 60000 })
  await page.waitForTimeout(1500)
  const url = page.url()
  const onLogin = url.includes('/login')
  await page.screenshot({ path: join(OUT, '01-authed-home.png'), fullPage: true })
  if (onLogin) {
    step('login', { pass: false, url, detail: 'redirected back to login' })
    report.ok = false
    return false
  }
  step('login', { pass: true, url, via: 'api_key_inject' })
  return true
}

async function assertMobileShell(page) {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400)
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(1500)

  const bottomNav = page.locator('.aba-v2-bottom-nav')
  const bottomVisible = await bottomNav.isVisible().catch(() => false)
  const items = await page.locator('.aba-v2-bottom-nav__item').count()
  const sider = page.locator('.aba-v2-sider, .aba-sider')
  const siderVisible = await sider.isVisible().catch(() => false)
  const shell = page.locator('.aba-v2-shell')
  const hasShell = await shell.count()

  const labels = await page.locator('.aba-v2-bottom-nav__label').allTextContents()
  await page.screenshot({ path: join(OUT, '02-mobile-home.png'), fullPage: true })

  const pass = bottomVisible && items >= 5 && !siderVisible && hasShell > 0
  step('mobile_shell', {
    pass,
    bottomVisible,
    items,
    labels,
    siderVisible,
    hasShell,
  })
  if (!pass) report.ok = false
  return pass
}

async function tapBottomAndShot(page, label, file) {
  const btn = page.locator('.aba-v2-bottom-nav__item', { hasText: label }).first()
  if (!(await btn.count())) {
    step(`tap_${label}`, { pass: false, detail: 'button missing' })
    report.ok = false
    return
  }
  await btn.click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: join(OUT, file), fullPage: true })
  const title = await page.locator('.aba-v2-header__title').textContent().catch(() => '')
  step(`tap_${label}`, { pass: true, title: (title || '').trim(), url: page.url() })
}

async function openMoreMenu(page) {
  const more = page.locator('.aba-v2-bottom-nav__item', { hasText: 'More' }).first()
  await more.click()
  await page.waitForTimeout(800)
  const drawer = page.locator('.aba-v2-nav-drawer')
  const open = await drawer.locator('.ant-drawer-content-wrapper').isVisible().catch(() => false)
  // group titles
  const groups = await page.locator('.aba-v2-nav-drawer__menu .ant-menu-item-group-title').allTextContents()
  await page.screenshot({ path: join(OUT, '07-mobile-more.png'), fullPage: true })
  step('more_sheet', { pass: open || groups.length > 0, groups, open })
  if (!(open || groups.length > 0)) report.ok = false
  // close
  await page.locator('.aba-v2-nav-drawer button[aria-label="Close menu"]').click().catch(async () => {
    await page.keyboard.press('Escape')
  })
  await page.waitForTimeout(400)
}

async function assertDesktopShell(page) {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.waitForTimeout(500)
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(1200)

  const bottomNav = page.locator('.aba-v2-bottom-nav')
  const bottomVisible = await bottomNav.isVisible().catch(() => false)
  const sider = page.locator('.aba-v2-sider, aside.aba-sider, .aba-sider')
  const siderVisible = await sider.isVisible().catch(() => false)
  await page.screenshot({ path: join(OUT, '08-desktop-home.png'), fullPage: true })

  // On desktop bottom nav should be hidden (CSS display:none or not mounted)
  const pass = !bottomVisible && siderVisible
  step('desktop_shell', { pass, bottomVisible, siderVisible })
  if (!pass) report.ok = false
}

async function checkConsole(page) {
  const hard = report.errors.filter((e) =>
    /TypeError|ReferenceError|is not defined|Failed to fetch/i.test(e),
  )
  step('console_errors', { pass: hard.length === 0, hard, all: report.errors.slice(0, 12) })
  if (hard.length) report.ok = false
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()
  page.on('pageerror', (err) => report.errors.push(String(err.message || err)))
  page.on('console', (msg) => {
    if (msg.type() === 'error') report.errors.push(msg.text())
  })

  try {
    const loggedIn = await login(page)
    if (loggedIn) {
      await assertMobileShell(page)
      await tapBottomAndShot(page, 'Agents', '03-mobile-agents.png')
      await tapBottomAndShot(page, 'Tasks', '04-mobile-tasks.png')
      await tapBottomAndShot(page, 'Biz', '05-mobile-biz.png')
      await page.locator('.aba-v2-bottom-nav__item', { hasText: 'Home' }).first().click()
      await page.waitForTimeout(800)
      await page.screenshot({ path: join(OUT, '06-mobile-home-quick.png'), fullPage: true })
      // quick actions on dashboard
      const qa = await page.locator('.aba-v2-quick-actions').isVisible().catch(() => false)
      step('dashboard_quick_actions', { pass: qa })
      if (!qa) report.ok = false
      await openMoreMenu(page)
      await assertDesktopShell(page)
    }
    await checkConsole(page)
  } catch (e) {
    report.ok = false
    report.errors.push(String(e))
    step('fatal', { pass: false, detail: String(e) })
    await page.screenshot({ path: join(OUT, '99-fatal.png'), fullPage: true }).catch(() => {})
  }

  await browser.close()
  const outJson = join(OUT, 'report.json')
  writeFileSync(outJson, JSON.stringify(report, null, 2))
  console.log('\n=== V2 SHELL REPORT ===')
  console.log(JSON.stringify(report, null, 2))
  console.log('screenshots:', OUT)
  process.exit(report.ok ? 0 : 1)
}

main()
