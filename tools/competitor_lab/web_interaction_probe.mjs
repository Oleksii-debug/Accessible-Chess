import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const outDir = process.env.COMPETITOR_RESULTS || 'competitor-results/web';
fs.mkdirSync(outDir, { recursive: true });

const targets = [
  { id: 'lichess-analysis', url: 'https://lichess.org/analysis' },
  { id: 'lichess-study', url: 'https://lichess.org/study' },
  { id: 'chesscom-analysis', url: 'https://www.chess.com/analysis' },
  { id: 'chesscom-lessons', url: 'https://www.chess.com/lessons' },
  { id: 'skchess-guide', url: 'https://accessiblechess.in/skchess' },
  { id: 'chessbase-support', url: 'https://support.chessbase.com/en/downloads' }
];

function safeName(value) {
  return value.replace(/[^a-z0-9._-]+/gi, '-');
}

async function describeActive(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return null;
    const text = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300);
    return {
      tag: el.tagName,
      type: el.getAttribute?.('type'),
      role: el.getAttribute?.('role'),
      id: el.id || null,
      name: el.getAttribute?.('name'),
      ariaLabel: el.getAttribute?.('aria-label'),
      ariaDescribedBy: el.getAttribute?.('aria-describedby'),
      title: el.getAttribute?.('title'),
      href: el.getAttribute?.('href'),
      text
    };
  });
}

async function inspectTarget(browser, target) {
  const context = await browser.newContext({
    locale: 'en-US',
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce'
  });
  const page = await context.newPage();
  const result = {
    target,
    startedAt: new Date().toISOString(),
    playwrightVersion: process.env.npm_package_dependencies_playwright || null,
    navigation: null,
    title: null,
    finalUrl: null,
    headings: [],
    landmarks: [],
    interactives: [],
    tabSequence: [],
    errors: []
  };

  page.on('console', msg => {
    if (msg.type() === 'error') result.errors.push({ kind: 'console', text: msg.text().slice(0, 1000) });
  });
  page.on('pageerror', err => result.errors.push({ kind: 'pageerror', text: String(err).slice(0, 1000) }));

  try {
    const response = await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    result.navigation = response ? { status: response.status(), ok: response.ok() } : null;
    await page.waitForTimeout(2500);
    result.title = await page.title();
    result.finalUrl = page.url();

    result.headings = await page.locator('h1,h2,h3,h4,h5,h6').evaluateAll(nodes => nodes.slice(0, 100).map(n => ({
      tag: n.tagName,
      text: (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 500)
    })));

    result.landmarks = await page.locator('main,nav,header,footer,aside,[role="main"],[role="navigation"],[role="region"],[role="search"],[role="dialog"],[role="application"]').evaluateAll(nodes => nodes.slice(0, 150).map(n => ({
      tag: n.tagName,
      role: n.getAttribute('role'),
      ariaLabel: n.getAttribute('aria-label'),
      ariaLabelledBy: n.getAttribute('aria-labelledby'),
      text: (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300)
    })));

    result.interactives = await page.locator('button,a[href],input,textarea,select,[tabindex],[role="button"],[role="link"],[role="textbox"],[role="menuitem"],[role="tab"],[role="treeitem"],[role="option"],[role="gridcell"]').evaluateAll(nodes => nodes.slice(0, 500).map(n => ({
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

    await page.locator('body').click({ position: { x: 2, y: 2 }, force: true }).catch(() => {});
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(30);
      const active = await describeActive(page);
      result.tabSequence.push({ step: i + 1, active });
      if (!active) break;
    }

    await page.screenshot({ path: path.join(outDir, `${safeName(target.id)}.png`), fullPage: true }).catch(err => {
      result.errors.push({ kind: 'screenshot', text: String(err) });
    });

    if (typeof page.locator('body').ariaSnapshot === 'function') {
      try {
        result.ariaSnapshot = await page.locator('body').ariaSnapshot({ timeout: 10000 });
      } catch (err) {
        result.errors.push({ kind: 'ariaSnapshot', text: String(err).slice(0, 1000) });
      }
    }
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
  for (const target of targets) {
    await inspectTarget(browser, target);
  }
} finally {
  await browser.close();
}
