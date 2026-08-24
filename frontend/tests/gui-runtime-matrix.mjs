import fs from 'node:fs'
import path from 'node:path'
import { chromium, firefox, webkit } from 'playwright'

const BASE_URL = process.env.GUI_BASE_URL || 'http://127.0.0.1:5173'
const outDir = path.resolve(process.env.GUI_ARTIFACT_DIR || 'artifacts/gui-runtime-matrix')
fs.mkdirSync(outDir, { recursive: true })

const routes = [
  ['dashboard', '/'],
  ['observations', '/observations'],
  ['aircraft', '/aircraft'],
  ['fr24', '/fr24'],
  ['routes', '/routes'],
  ['infrastructure', '/infrastructure'],
  ['airports', '/airports'],
  ['review', '/review'],
  ['export', '/export'],
  ['readiness', '/readiness'],
  ['calibration', '/calibration'],
  ['analysis', '/analysis'],
  ['spatial-truth', '/spatial-truth'],
]
const viewports = [320, 375, 768, 1280, 1440, 1920].map((width) => ({ width, height: width < 768 ? 844 : 900 }))
const engines = { chromium, firefox, webkit }
const results = []
let failed = false

function record(entry) {
  results.push(entry)
  if (entry.status === 'FAIL') failed = true
}

for (const [engineName, engine] of Object.entries(engines)) {
  const browser = await engine.launch({ headless: true })
  try {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport, reducedMotion: 'no-preference' })
      const page = await context.newPage()
      const pageErrors = []
      page.on('pageerror', (error) => pageErrors.push(String(error)))
      try {
        for (const [name, route] of routes) {
          await page.goto(`${BASE_URL}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 })
          await page.waitForTimeout(300)
          const bodyText = await page.locator('body').innerText()
          const diagnostic = bodyText.includes('NON_PRODUCTION_DIAGNOSTIC') || bodyText.toLowerCase().includes('diagnostic')
          const file = `${engineName}-${viewport.width}-${name}.png`
          await page.screenshot({ path: path.join(outDir, file), fullPage: true })
          record({
            engine: engineName,
            viewport: viewport.width,
            surface: name,
            route,
            status: bodyText.trim().length > 0 && pageErrors.length === 0 ? 'PASS' : 'FAIL',
            diagnostic_marker_observed: diagnostic,
            page_errors: [...pageErrors],
            screenshot: file,
          })
          pageErrors.length = 0
        }

        await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
        await page.keyboard.press('Tab')
        const focused = await page.evaluate(() => {
          const el = document.activeElement
          return el && el !== document.body ? { tag: el.tagName, text: (el.textContent || '').trim().slice(0, 80) } : null
        })
        record({ engine: engineName, viewport: viewport.width, mode: 'keyboard-only', status: focused ? 'PASS' : 'FAIL', focused })

        await page.evaluate(() => { document.documentElement.style.zoom = '2' })
        const zoomLayout = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          bodyWidth: document.body.getBoundingClientRect().width,
        }))
        record({
          engine: engineName,
          viewport: viewport.width,
          mode: 'css-200%-zoom-surrogate',
          status: Number.isFinite(zoomLayout.scrollWidth) && zoomLayout.scrollWidth > 0 ? 'PASS' : 'FAIL',
          note: 'CSS zoom stress only; not credited as native browser 200% zoom certification.',
          layout: zoomLayout,
        })
      } catch (error) {
        record({ engine: engineName, viewport: viewport.width, status: 'FAIL', error: String(error), page_errors: pageErrors })
      } finally {
        await context.close()
      }
    }

    const reduced = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
    const reducedPage = await reduced.newPage()
    try {
      await reducedPage.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
      const matches = await reducedPage.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
      record({ engine: engineName, viewport: 1280, mode: 'reduced-motion', status: matches ? 'PASS' : 'FAIL' })
    } catch (error) {
      record({ engine: engineName, viewport: 1280, mode: 'reduced-motion', status: 'FAIL', error: String(error) })
    } finally {
      await reduced.close()
    }
  } finally {
    await browser.close()
  }
}

const summary = {
  schema_version: '1.0',
  app: 'skywatcher-pr',
  architecture: 'diagnostic-router',
  engines: Object.keys(engines),
  viewports: viewports.map((v) => v.width),
  routes: routes.map(([name, route]) => ({ name, route })),
  expected_surface_cells: Object.keys(engines).length * viewports.length * routes.length,
  observed_surface_cells: results.filter((r) => r.surface).length,
  failures: results.filter((r) => r.status === 'FAIL').length,
  native_200_percent_zoom_certified: false,
  results,
}
fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n')
console.log(JSON.stringify({ expected_surface_cells: summary.expected_surface_cells, observed_surface_cells: summary.observed_surface_cells, failures: summary.failures }, null, 2))
process.exit(failed ? 1 : 0)
