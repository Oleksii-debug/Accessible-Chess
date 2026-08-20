import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const outDir = process.env.COMPETITOR_RESULTS || 'competitor-results/web';
fs.mkdirSync(outDir, { recursive: true });

const targets = [
  { id: 'lichess-analysis', url: 'https://lichess.org/analysis', enableLichessBlindMode: true },
  { id: 'lichess-editor', url: 'https://lichess.org/editor', enableLichessBlindMode: true },
  { id: 'lichess-import', url: 'https://lichess.org/paste', enableLichessBlindMode: true },
  { id: 'lichess-study', url: 'https://lichess.org/study', enableLichessBlindMode: true },
  { id: 'chesscom-analysis', url: 'https://www.chess.com/analysis' },
  { id: 'chesscom-lessons', url: 'https://www.chess.com/lessons' },
  { id: 'skchess-guide', url: 'https://accessiblechess.in/skchess' },
  { id: 'chessbase-support', url: 'https://support.chessbase.com/en/downloads' }
];

function safeName(value) { return value.replace(/[^a-z0-9._-]+/gi, '-'); }

async function describeActive(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return null;
    return {
      tag: el.tagName,
      type: el.getAttribute?.('type'),
      role: el.getAttribute?.('role'),
      id: el.id || null,
      name: el.getAttribute?.('name'),
      ariaLabel: el.getAttribute?.('aria-label'),
      ariaDescribedBy: el.getAttribute?.('aria-describedby'),
      ariaExpanded: el.getAttribute?.('aria-expanded'),
      ariaSelected: el.getAttribute?.('aria-selected'),
      title: el.getAttribute?.('title'),
      href: el.getAttribute?.('href'),
      text: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300)
    };
  });
}

async function collectSurface(page) {
  const headings = await page.locator('h1,h2,h3,h4,h5,h6').evaluateAll(nodes => nodes.slice(0, 120).map(n => ({
    tag: n.tagName,
    text: (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 500)
  })));
  const landmarks = await page.locator('main,nav,header,footer,aside,[role="main"],[role="navigation"],[role="region"],[role="search"],[role="dialog"],[role="application"]').evaluateAll(nodes => nodes.slice(0, 180).map(n => ({
    tag: n.tagName,
    role: n.getAttribute('role'),
    ariaLabel: n.getAttribute('aria-label'),
    ariaLabelledBy: n.getAttribute('aria-labelledby'),
    text: (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300)
  })));
  const interactives = await page.locator('button,a[href],input,textarea,select,[tabindex],[role="button"],[role="link"],[role="textbox"],[role="menuitem"],[role="tab"],[role="treeitem"],[role="option"],[role="gridcell"],[role="slider"],[role="checkbox"]').evaluateAll(nodes => nodes.slice(0, 700).map(n => ({
    tag: n.tagName,
    type: n.getAttribute('type'),
    role: n.getAttribute('role'),
    id: n.id || null,
    tabindex: n.getAttribute('tabindex'),
    ariaLabel: n.getAttribute('aria-label'),
    ariaExpanded: n.getAttribute('aria-expanded'),
    ariaSelected: n.getAttribute('aria-selected'),
    ariaControls: n.getAttribute('aria-controls'),
    title: n.getAttribute('title'),
    href: n.getAttribute('href'),
    text: (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300)
  })));
  let ariaSnapshot = null;
  if (typeof page.locator('body').ariaSnapshot === 'function') {
    try { ariaSnapshot = await page.locator('body').ariaSnapshot({ timeout: 10000 }); } catch {}
  }
  return { headings, landmarks, interactives, ariaSnapshot };
}

async function tabProbe(page, count = 60) {
  const rows = [];
  await page.locator('body').click({ position: { x: 2, y: 2 }, force: true }).catch(() => {});
  for (let i = 0; i < count; i++) {
    await page.keyboard.press('Tab');
    await page.waitForTimeout(35);
    rows.push({ step: i + 1, active: await describeActive(page) });
  }
  return rows;
}

async function enableLichessBlindMode(page, result) {
  const button = page.getByRole('button', { name: /Accessibility.*Enable blind mode/i }).first();
  if (!(await button.count())) {
    result.scenarios.lichessBlindMode = { attempted: true, found: false };
    return;
  }
  const before = (await button.innerText().catch(() => '')) || await button.getAttribute('aria-label');
  try {
    await button.click({ timeout: 10000 });
    await page.waitForTimeout(1500);
    const disable = page.getByRole('button', { name: /Accessibility.*Disable blind mode/i }).first();
    result.scenarios.lichessBlindMode = {
      attempted: true,
      found: true,
      before,
      after: (await disable.count()) ? ((await disable.innerText().catch(() => '')) || await disable.getAttribute('aria-label')) : null,
      urlAfter: page.url(),
      surfaceAfter: await collectSurface(page),
      tabSequenceAfter: await tabProbe(page, 80)
    };
    await page.screenshot({ path: path.join(outDir, `${safeName(result.target.id)}-blind-mode.png`), fullPage: true }).catch(() => {});
  } catch (err) {
    result.scenarios.lichessBlindMode = { attempted: true, found: true, before, error: String(err).slice(0, 1500) };
  }
}

async function inspectTarget(browser, target) {
  const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const result = {
    target,
    startedAt: new Date().toISOString(),
    navigation: null,
    title: null,
    finalUrl: null,
    surfaceBefore: null,
    tabSequenceBefore: [],
    scenarios: {},
    errors: []
  };
  page.on('console', msg => { if (msg.type() === 'error') result.errors.push({ kind: 'console', text: msg.text().slice(0, 1000) }); });
  page.on('pageerror', err => result.errors.push({ kind: 'pageerror', text: String(err).slice(0, 1000) }));
  try {
    const response = await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    result.navigation = response ? { status: response.status(), ok: response.ok() } : null;
    await page.waitForTimeout(3000);
    result.title = await page.title();
    result.finalUrl = page.url();
    result.surfaceBefore = await collectSurface(page);
    result.tabSequenceBefore = await tabProbe(page, 60);
    await page.screenshot({ path: path.join(outDir, `${safeName(target.id)}.png`), fullPage: true }).catch(err => result.errors.push({ kind: 'screenshot', text: String(err) }));
    if (target.enableLichessBlindMode) await enableLichessBlindMode(page, result);
  } catch (err) {
    result.errors.push({ kind: 'fatal', text: String(err).slice(0, 2000) });
  } finally {
    result.finishedAt = new Date().toISOString();
    fs.writeFileSync(path.join(outDir, `${safeName(target.id)}.json`), JSON.stringify(result, null, 2));
    await context.close();
  }
}

const browser = await chromium.launch({ headless: true });
try {
  for (const target of targets) await inspectTarget(browser, target);
} finally {
  await browser.close();
}
