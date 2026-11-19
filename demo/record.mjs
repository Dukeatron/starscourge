#!/usr/bin/env node
// Demo recorder for the AI Compliance Engine.
//
// Drives the web UI through the shot list in docs/DEMO.md at a watchable pace and
// records a 1920x1080 video, plus a timeline, draft captions and an ffmpeg cut list
// that removes most of the LLM wait. Re-run it after any UI change.
//
//   cd demo && npm install                      # once (Playwright)
//   npx playwright install chromium             # only if the browser is missing
//   uvicorn main:app                            # repo root, another terminal
//   npm run record                              # live take: real LLM calls
//   npm run rehearse                            # same flow, API answered from demo/fixtures
//   npm run smoke                               # fast, headless, mock: does the flow still work?
//
// Flags: --mock  --fast  --headless  --no-video  --no-cursor  --no-coldopen
//        --base-url=http://127.0.0.1:8000
//        --ui=path/to/index.html   serve this file at "/" instead of the server's page
//                                  (test a frontend branch before it is merged)
// Env:   DEMO_BASE_URL, DEMO_PROVIDER, DEMO_MODEL (set in the UI's Model panel. Keep the
//        API key in the server's .env so it never appears on screen), DEMO_THEME=light|dark
//
// --mock answers /api/analyze-regulation and /api/generate-audit with demo/fixtures,
// captured from a real run (see demo/fixtures/README.md). Use it to rehearse pacing or to
// re-shoot UI-only changes. The published demo should be a live take.
//
// SELECTORS: everything the script touches is in SEL below, aimed at the redesigned
// static/index.html (refine/frontend @ 872f922, merged). If the UI changes again, update SEL.

import { chromium } from 'playwright';
import { mkdirSync, readFileSync, writeFileSync, renameSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flags = new Set(argv.filter(a => !a.includes('=')));
const kv = Object.fromEntries(argv.filter(a => a.includes('=')).map(a => { const [k, ...v] = a.replace(/^--/, '').split('='); return [k, v.join('=')]; }));
const MOCK = flags.has('--mock');
const FAST = flags.has('--fast');
const HEADLESS = flags.has('--headless');
const VIDEO = !flags.has('--no-video');
const CURSOR = !flags.has('--no-cursor');
const COLDOPEN = !flags.has('--no-coldopen');
const UI_FILE = kv.ui ? resolve(process.cwd(), kv.ui) : null;
const BASE_URL = (kv['base-url'] || process.env.DEMO_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const PROVIDER = process.env.DEMO_PROVIDER || '';
const MODEL = process.env.DEMO_MODEL || '';
const THEME = process.env.DEMO_THEME === 'light' ? 'light' : 'dark';
const LLM_TIMEOUT_MS = 10 * 60 * 1000;
const SIZE = { width: 1920, height: 1080 };

// ---------------------------------------------------------------- selectors
const SEL = {
  healthOnline: '#healthTxt:has-text("API online")',   // header health chip
  stateTiles: '#stateView',                            // company-state tiles (left column)
  stateEditorToggle: '#stateDetails > summary',        // "Edit as JSON"
  stateJson: '#stateJson',                             // JSON textarea (input event re-renders tiles)
  regulation: '#reg',
  regMeta: '#chars',                                   // "1,234 chars · 8 clauses detected"
  analyze: '#analyze',
  progress: '#findings .progress',                     // staged progress (cosmetic timing)
  summary: '#findings .summary',                       // donut + counters + grounding meter
  groundMeter: '#findings .ground-meter',              // "N of M quotes verified verbatim by the server"
  covStrip: '#findings .cov-strip',                    // "N of M clauses assessed · K not flagged"
  findingCard: '#cards article.card',
  excerptInCard: '.quote q',                           // the quote inside a card
  badgeInCard: '.grounded',                            // server-driven: Verified / Partial / Unverified / No matching source
  verifiedBadge: '.grounded:has-text("Verified · verbatim")',
  showInSource: '[data-src]',                          // "Show in source" button inside a card
  errorVisible: '#error .alert',
  coverageTab: '.tab[data-tab="coverage"]',
  coverageMap: '#coverage .clause-map',                // numbered clause cells
  coverageClause: '#coverage .clause',                 // one row per clause
  notFlaggedClause: '#coverage .clause.nf',            // hatched amber "Review by hand"
  sourceTab: '.tab[data-tab="source"]',
  sourceMarks: '#srcText mark',                        // highlighted excerpts in the regulation
  sourceText: '#srcText',
  findingsTab: '.tab[data-tab="findings"]',
  auditButton: '#audit',
  reportHeading: '#report .md h1',
  reportSections: '#report .md h2',
  reportActions: '#report .doc-bar',                   // Download / Copy / Print
  reportProvenance: '#report .doc-head',               // "Drafted by … (LLM)" / "Rendered deterministically" + "Draft · pending human review"
  modelDetails: '#modelDetails',
  provider: '#provider',
  model: '#model',
};

// ---------------------------------------------------------------- pacing
const T = FAST
  ? { beat: 120, read: 250, longRead: 400, scrollMs: 250, steps: 2 }
  : { beat: 800, read: 2400, longRead: 4200, scrollMs: 1300, steps: 28 };
const wait = ms => new Promise(r => setTimeout(r, ms));

// ---------------------------------------------------------------- data
const REGULATION = readFileSync(join(HERE, 'regulation.txt'), 'utf8').trim();
const STATE = JSON.parse(readFileSync(join(HERE, 'company_state.json'), 'utf8'));
const NF_PREFER = /These should be provided to CERT-In/; // not-flagged clause to feature in the coverage shot
const INJECTION_LINE =REGULATION.split('\n').find(l => /ignore all previous instructions/i.test(l)) || '';

// ---------------------------------------------------------------- timeline
const timeline = [];
let t0 = 0;
function mark(id, caption = '') {
  const t = (Date.now() - t0) / 1000;
  timeline.push({ id, t: +t.toFixed(2), caption });
  console.log(`  [${t.toFixed(1).padStart(6)}s] ${id}${caption ? '  ' + caption : ''}`);
}

// ---------------------------------------------------------------- helpers
// A visible cursor: headless/recorded Chromium does not draw the real one.
const CURSOR_JS = `(() => {
  if (window.__demoCursor) return; window.__demoCursor = true;
  const add = () => {
    const c = document.createElement('div');
    c.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;border-radius:50%;' +
      'background:rgba(56,189,248,.30);border:2px solid rgba(56,189,248,.95);transform:translate(-50%,-50%);' +
      'transition:transform .12s ease,background .12s ease;left:-60px;top:-60px';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => { c.style.transform = 'translate(-50%,-50%) scale(.7)'; c.style.background = 'rgba(56,189,248,.7)'; }, true);
    addEventListener('mouseup', () => { c.style.transform = 'translate(-50%,-50%)'; c.style.background = 'rgba(56,189,248,.30)'; }, true);
  };
  document.readyState === 'loading' ? addEventListener('DOMContentLoaded', add) : add();
})();`;

async function glideTo(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) return;
  await page.mouse.move(box.x + Math.min(box.width / 2, 160), box.y + box.height / 2, { steps: T.steps });
}
async function click(page, selector) {
  const el = page.locator(selector).first();
  await glideTo(page, el);
  await wait(T.beat / 2);
  await el.click();
}
async function smoothScroll(locator, block = 'start') {
  await locator.evaluate((el, block) => el.scrollIntoView({ behavior: 'smooth', block }), block);
  await wait(T.scrollMs);
}

async function installRoutes(context) {
  if (UI_FILE) {
    const html = readFileSync(UI_FILE, 'utf8');
    await context.route(BASE_URL + '/', route => route.fulfill({ status: 200, contentType: 'text/html', body: html }));
  }
  if (!MOCK) return;
  const fx = join(HERE, 'fixtures');
  const analysis = readFileSync(join(fx, 'analysis.json'), 'utf8');
  const markdown = readFileSync(join(fx, 'audit.md'), 'utf8');
  const meta = existsSync(join(fx, 'meta.json')) ? JSON.parse(readFileSync(join(fx, 'meta.json'), 'utf8')) : {};
  const delay = FAST ? 300 : 5000; // long enough to show the progress animation
  // /api/coverage is deterministic (no LLM), so it is NOT mocked: the real server computes it
  // from the fixture's excerpt_span values, exactly as in a live take.
  await context.route('**/api/analyze-regulation', async route => {
    await wait(delay);
    // Same header the real server sends, naming the model the fixture was captured with.
    const headers = meta.model && meta.model !== 'server default' ? { 'X-LLM-Model-Used': meta.model } : {};
    await route.fulfill({ status: 200, contentType: 'application/json', headers, body: analysis });
  });
  await context.route('**/api/generate-audit', async route => {
    await wait(delay);
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ anomalies: JSON.parse(analysis), markdown, renderer: meta.audit_renderer ?? 'deterministic', model: meta.audit_model ?? null }),
    });
  });
}

function srtTime(s) {
  const ms = Math.max(0, Math.round(s * 1000));
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
}

function writeArtifacts(outDir, report) {
  writeFileSync(join(outDir, 'timeline.json'), JSON.stringify({ mock: MOCK, baseUrl: BASE_URL, ui: UI_FILE, timeline, ...report }, null, 2));
  const caps = timeline.filter(m => m.caption);
  writeFileSync(join(outDir, 'captions.draft.srt'), caps.map((m, i) => {
    const next = i + 1 < caps.length ? caps[i + 1].t - 0.1 : m.t + 4;
    return `${i + 1}\n${srtTime(m.t)} --> ${srtTime(Math.min(next, m.t + 6))}\n${m.caption}\n`;
  }).join('\n'));

  // Cut list: keep ~3 s of each loading animation, drop the rest of the wait.
  const gaps = [['analyze-click', 'findings-visible'], ['audit-click', 'audit-visible']]
    .map(([a, b]) => [timeline.find(m => m.id === a), timeline.find(m => m.id === b)])
    .filter(([a, b]) => a && b && b.t - a.t > 4)
    .map(([a, b]) => [a.t + 3, b.t - 0.3]);
  if (gaps.length) {
    let segs = [], from = 0;
    gaps.forEach(([cutFrom, cutTo]) => { segs.push([from, cutFrom]); from = cutTo; });
    segs.push([from, null]);
    const trims = segs.map(([s, e], i) => `[0:v]trim=start=${s.toFixed(2)}${e != null ? `:end=${e.toFixed(2)}` : ''},setpts=PTS-STARTPTS[s${i}]`).join(';');
    const sh = `#!/bin/sh
# Removes the LLM waits (keeps ~3 s of each progress animation). Run inside this folder.
# Output: demo-cut.mp4 (H.264, 30 fps). Captions in captions.draft.srt are for the UNCUT video;
# shift them in your editor, or re-time them after cutting.
set -e
ffmpeg -y -i video.webm -filter_complex \\
 "${trims};${segs.map((_, i) => `[s${i}]`).join('')}concat=n=${segs.length}:v=1:a=0,fps=30[v]" \\
 -map "[v]" -c:v libx264 -crf 18 -pix_fmt yuv420p demo-cut.mp4
`;
    writeFileSync(join(outDir, 'cut-llm-wait.sh'), sh, { mode: 0o755 });
  }
}

// ---------------------------------------------------------------- the run
async function main() {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const outDir = resolve(HERE, 'out', `${stamp}${MOCK ? '-mock' : ''}`);
  mkdirSync(outDir, { recursive: true });
  console.log(`Recording ${MOCK ? '(MOCK fixtures)' : '(live LLM)'} against ${BASE_URL}${UI_FILE ? ` with UI ${UI_FILE}` : ''}\n  -> ${outDir}`);

  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    viewport: SIZE,
    deviceScaleFactor: 1,
    colorScheme: THEME,
    recordVideo: VIDEO ? { dir: outDir, size: SIZE } : undefined,
  });
  await context.addInitScript(theme => { try { localStorage.setItem('cc-theme', theme); } catch {} }, THEME);
  if (CURSOR) await context.addInitScript(CURSOR_JS);
  await installRoutes(context);
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  t0 = Date.now();
  const report = { grounding: { checked: 0, verbatim: 0, badges: {}, failures: [] }, findings: [] };

  try {
    // SHOT 1 · cold open: a wall of regulation text (b-roll for the hook line).
    if (COLDOPEN) {
      const esc = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
      await page.setContent(`<body style="margin:0;background:#0b0f16;color:#b8c2d1;font:24px/1.75 Georgia,serif;overflow:hidden">
        <div style="padding:90px 240px;white-space:pre-wrap">${esc((REGULATION + '\n\n').repeat(3))}</div></body>`);
      mark('coldopen', 'In 2022, CERT-In gave every company in India six hours to report a cyber incident.');
      await page.evaluate(ms => new Promise(r => {
        const el = document.scrollingElement, end = el.scrollHeight - innerHeight, start = performance.now();
        const step = now => { const p = Math.min(1, (now - start) / ms); el.scrollTop = end * p; p < 1 ? requestAnimationFrame(step) : r(); };
        requestAnimationFrame(step);
      }), FAST ? 300 : 6000);
    }

    // SHOT 2 · the app.
    await page.goto(BASE_URL + '/');
    await page.locator(SEL.healthOnline).waitFor();
    if (THEME === 'dark') await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
    mark('app-loaded', 'Someone has to check every clause against settings spread across five teams.');
    await wait(T.read);

    // SHOT 3 · company state.
    mark('state-load', 'PaySetu, a payment aggregator, described by forty-four real settings.');
    if (SEL.stateEditorToggle) await click(page, SEL.stateEditorToggle);
    await wait(T.beat);
    await page.locator(SEL.stateJson).fill(JSON.stringify(STATE, null, 2));
    await page.locator(SEL.stateJson).dispatchEvent('input');
    await wait(T.beat);
    if (SEL.stateEditorToggle) await click(page, SEL.stateEditorToggle);
    await glideTo(page, page.locator(SEL.stateTiles));
    await wait(T.longRead);

    if (PROVIDER || MODEL) {
      await page.locator(SEL.modelDetails).evaluate(d => { d.open = true; });
      if (PROVIDER) await page.locator(SEL.provider).selectOption(PROVIDER);
      if (MODEL) { await page.locator(SEL.model).fill(MODEL); await page.locator(SEL.model).dispatchEvent('input'); }
      await page.locator(SEL.modelDetails).evaluate(d => { d.open = false; });
    }

    // SHOT 4 · paste the regulation (and show the buried instruction).
    mark('regulation-paste', 'The actual CERT-In direction, plus one planted line: ignore all previous instructions.');
    await click(page, SEL.regulation);
    await page.locator(SEL.regulation).fill(REGULATION);
    await page.locator(SEL.regulation).dispatchEvent('input');
    await glideTo(page, page.locator(SEL.regMeta));
    await wait(T.beat);
    await page.locator(SEL.regulation).evaluate(el => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }));
    await wait(T.read);
    await page.locator(SEL.regulation).evaluate(el => el.scrollTo({ top: 0, behavior: 'smooth' }));
    await wait(T.beat);

    // SHOT 5 · analyze. The wait is cut in the edit (cut-llm-wait.sh).
    await click(page, SEL.analyze);
    mark('analyze-click', 'Analyze.');
    await page.locator(SEL.progress).waitFor({ timeout: 5000 }).catch(() => {});
    await Promise.race([
      page.locator(SEL.summary).waitFor({ timeout: LLM_TIMEOUT_MS }),
      page.locator(SEL.errorVisible).waitFor({ timeout: LLM_TIMEOUT_MS }).then(async () => {
        throw new Error('UI showed an error: ' + (await page.locator(SEL.errorVisible).innerText()).replace(/\s+/g, ' '));
      }),
    ]);
    mark('findings-visible', 'Gaps ranked by severity.');
    await page.mouse.move(SIZE.width * 0.62, 330, { steps: T.steps });
    await wait(T.longRead); // let the donut and counters animate
    await glideTo(page, page.locator(SEL.groundMeter));
    mark('ground-meter', 'The server checks every quote against the regulation, and says which ones it could verify.');
    await wait(T.read);
    if (await page.locator(SEL.covStrip).count()) {
      await glideTo(page, page.locator(SEL.covStrip));
      mark('coverage-strip', 'And how many clauses it assessed.');
      await wait(T.read);
    }

    // SHOT 6 · walk the cards. Record each card's server-driven badge; check quotes are real text.
    const cards = page.locator(SEL.findingCard);
    const n = await cards.count();
    for (let i = 0; i < n; i++) {
      const card = cards.nth(i);
      const q = card.locator(SEL.excerptInCard);
      const badge = card.locator(SEL.badgeInCard);
      const title = (await card.locator('h3').innerText()).trim();
      const sev = await card.getAttribute('data-sev');
      const badgeText = (await badge.count()) ? (await badge.first().innerText()).trim().replace(/\s+/g, ' ') : 'none';
      report.findings.push({ title, severity: sev, badge: badgeText });
      const kind = badgeText.split(/[·(]/)[0].replace(/[^\w ]/g, '').trim() || badgeText;
      report.grounding.badges[kind] = (report.grounding.badges[kind] || 0) + 1;
      if (await q.count()) {
        const text = (await q.first().innerText()).trim();
        report.grounding.checked++;
        if (REGULATION.includes(text)) report.grounding.verbatim++;
        else report.grounding.failures.push({ card: i, text });
      }
    }
    console.log(`  grounding: ${report.grounding.verbatim}/${report.grounding.checked} quotes are real regulation text; badges ${JSON.stringify(report.grounding.badges)}`);
    for (const f of report.grounding.failures) console.warn(`  WARN card ${f.card} quote not in regulation.txt: ${f.text.slice(0, 80)}`);

    // Linger on the top card, then on the first card whose quote the server VERIFIED (the wow shot).
    const verified = cards.filter({ has: page.locator(SEL.verifiedBadge) });
    const hero = (await verified.count()) ? verified.first() : cards.first();
    await smoothScroll(cards.first(), 'center');
    await glideTo(page, cards.first().locator('h3'));
    mark('finding-1', 'Top finding: the requirement, our current value, the gap and a concrete fix.');
    await wait(T.longRead);
    await smoothScroll(hero, 'center');
    const heroBadge = hero.locator(SEL.badgeInCard).first();
    if (await heroBadge.count()) await glideTo(page, heroBadge);
    mark('verified-badge', (await verified.count())
      ? 'Green means the model\'s quote was found word for word in the direction.'
      : 'No verified quote in this run: say so, do not use this shot.');
    await wait(T.longRead);

    // SHOT 7 · source grounding: the verified quote highlighted in place; the planted line is not.
    const srcBtn = hero.locator(SEL.showInSource);
    if (await srcBtn.count()) { await glideTo(page, srcBtn); await wait(T.beat / 2); await srcBtn.click(); }
    else await click(page, SEL.sourceTab);
    await page.locator(SEL.sourceText).waitFor();
    mark('source-grounding', 'Every verified quote is pinned to the exact characters it came from.');
    await wait(T.longRead);
    if (INJECTION_LINE) {
      // #srcText is its own scroll container: scroll it to the planted line and point at it.
      await smoothScroll(page.locator(SEL.sourceText), 'center');
      const rect = await page.locator(SEL.sourceText).evaluate(async (box, phrase) => {
        const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          const i = node.data.indexOf(phrase);
          if (i < 0) continue;
          const range = document.createRange();
          range.setStart(node, i); range.setEnd(node, i + phrase.length);
          const r0 = range.getBoundingClientRect(), b = box.getBoundingClientRect();
          box.scrollBy({ top: r0.top - b.top - b.height / 2, behavior: 'smooth' });
          await new Promise(r => setTimeout(r, 900));
          const r = range.getBoundingClientRect();
          return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
        return null;
      }, 'ignore all previous instructions');
      if (rect) await page.mouse.move(rect.x, rect.y, { steps: T.steps });
      mark('injection', 'The planted instruction is never cited, and the gaps are still reported.');
      await wait(T.longRead);
    }

    // SHOT 8 · clause coverage: what the model did NOT flag.
    await click(page, SEL.coverageTab);
    await page.locator(SEL.coverageMap).waitFor();
    mark('coverage', 'Clause coverage: every clause, and which ones the model raised nothing on.');
    await glideTo(page, page.locator(SEL.coverageMap));
    await wait(T.read);
    const nf = page.locator(SEL.notFlaggedClause);
    report.coverage = { clauses: await page.locator(SEL.coverageClause).count(), notFlagged: await nf.count() };
    if (report.coverage.notFlagged) {
      // Prefer a real obligation the model skipped (dataset-specific: CERT-In (iv), hand logs to
      // CERT-In with any incident report), then any "shall/should/must" clause, then the first.
      const pick = [nf.filter({ hasText: NF_PREFER }), nf.filter({ hasText: /\b(shall|should|must)\b/ }), nf];
      let target = nf.first();
      for (const cand of pick) if (await cand.count()) { target = cand.first(); break; }
      await smoothScroll(target, 'center');
      await glideTo(page, target.locator('.nfnote, .ctext').first());
      mark('not-flagged', 'Amber: the model raised nothing here. It tells you what it skipped, so a human checks it.');
      await wait(T.longRead);
    }
    console.log(`  coverage: ${report.coverage.clauses} clauses, ${report.coverage.notFlagged} not flagged`);

    // SHOT 9 · audit log: provenance + draft marker, then a quick scroll.
    await click(page, SEL.auditButton);
    mark('audit-click', 'One click drafts the working paper.');
    await page.locator(SEL.reportHeading).waitFor({ timeout: LLM_TIMEOUT_MS });
    await glideTo(page, page.locator(SEL.reportProvenance));
    report.audit = { provenance: (await page.locator(SEL.reportProvenance).innerText()).replace(/\s+/g, ' ').trim() };
    mark('audit-visible', 'It says who wrote it, and it is a draft pending human review.');
    await wait(T.longRead);
    const sections = page.locator(SEL.reportSections);
    const s = Math.min(await sections.count(), 3);
    for (let i = 0; i < s; i++) {
      await smoothScroll(sections.nth(i), 'start');
      await wait(T.read);
    }
    await smoothScroll(page.locator(SEL.reportActions), 'start');
    await glideTo(page, page.locator(SEL.reportActions));
    mark('end', 'New rule in. Verified quotes out. Six hours, not twenty-four.');
    await wait(T.longRead);
  } catch (err) {
    mark('error');
    console.error('\nRun failed:', err.message);
    report.error = err.message;
    await page.screenshot({ path: join(outDir, 'failure.png') }).catch(() => {});
    process.exitCode = 1;
  } finally {
    const video = page.video();
    await context.close();
    await browser.close();
    if (video) {
      const src = await video.path().catch(() => null);
      if (src && existsSync(src)) renameSync(src, join(outDir, 'video.webm'));
    }
    writeArtifacts(outDir, report);
    console.log(`\nDone (${((Date.now() - t0) / 1000).toFixed(1)} s). Output: ${outDir}`);
  }
}

main();
