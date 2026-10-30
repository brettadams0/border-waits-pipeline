// Lab CLS for the dashboard before and after b6e9cfd ("reserve space for
// data-driven content"), and for the live deployment.
//
// Run once; the output is what gets committed.
//
//   npm i --no-save puppeteer-core@24.10.0
//   CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe" node tools/measure_cls.mjs > results/cls.txt
//
// The two historical states are rebuilt from git, not kept as copies: web/ at
// b6e9cfd^ and at b6e9cfd is read out of git into a temp dir and served from
// 127.0.0.1. Their root-relative data requests are proxied to the live export,
// so every state renders the same data over the same network.
//
// CLS is the largest session window (1 s gap, 5 s cap) of layout-shift entries
// without recent input, the web-vitals definition, from a PerformanceObserver
// installed before any page script runs, read 6 s after the load event. Each
// run gets a fresh browser context. No CPU or network throttling: this is lab
// CLS on a fast connection, not field data.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const FIX = 'b6e9cfd';
const LIVE = 'https://brettadams0.github.io';
const RUNS = Number(process.env.RUNS ?? 10);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'bw-cls-'));
const states = { a: `${FIX}^`, b: FIX };
for (const [dir, rev] of Object.entries(states)) {
  const files = execFileSync('git', ['ls-tree', '-r', '--name-only', rev, 'web'], { encoding: 'utf8' })
    .split('\n').filter(Boolean);
  for (const f of files) {
    const dest = path.join(work, dir, f);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, execFileSync('git', ['show', `${rev}:${f}`], { maxBuffer: 64 << 20 }));
  }
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const dir = url.pathname.split('/')[1];
  if (!(dir in states)) {
    https.get(LIVE + req.url, (up) => { res.writeHead(up.statusCode, up.headers); up.pipe(res); })
      .on('error', () => { res.writeHead(502); res.end(); });
    return;
  }
  let file = path.join(work, dir, 'web', url.pathname.slice(dir.length + 2));
  if (url.pathname.endsWith('/')) file = path.join(file, 'index.html');
  fs.readFile(file, (err, body) => {
    if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
    res.end(body);
  });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const local = `http://127.0.0.1:${server.address().port}`;

const OBSERVER = `
  window.__shifts = [];
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shifts.push([e.startTime, e.value]); })
    .observe({ type: 'layout-shift', buffered: true });`;

const largestSessionWindow = () => {
  let best = 0, cur = 0, start = -1, prev = -1;
  for (const [t, v] of window.__shifts) {
    if (start < 0 || t - prev > 1000 || t - start > 5000) { cur = 0; start = t; }
    cur += v; prev = t; best = Math.max(best, cur);
  }
  return best;
};

const VIEWPORTS = {
  'desktop 1280x800 dpr1': { width: 1280, height: 800, deviceScaleFactor: 1 },
  'mobile 390x844 dpr3': { width: 390, height: 844, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
};
const TARGETS = {
  [`before ${FIX} (local)`]: `${local}/a/`,
  [`at ${FIX} (local)`]: `${local}/b/`,
  live: `${LIVE}/border-waits/`,
};

const browser = await puppeteer.launch({ executablePath: process.env.CHROME, headless: true });
console.log(`# ${new Date().toISOString()}  ${await browser.version()}  ${RUNS} runs each, no CPU or network throttling`);
for (const [vpName, viewport] of Object.entries(VIEWPORTS)) {
  for (const [name, url] of Object.entries(TARGETS)) {
    const values = [];
    for (let i = 0; i < RUNS; i++) {
      const ctx = await browser.createBrowserContext();
      const page = await ctx.newPage();
      await page.setViewport(viewport);
      await page.evaluateOnNewDocument(OBSERVER);
      await page.goto(url, { waitUntil: 'load' });
      await new Promise((r) => setTimeout(r, 6000));
      values.push(await page.evaluate(largestSessionWindow));
      await ctx.close();
    }
    values.sort((x, y) => x - y);
    const mean = values.reduce((s, v) => s + v, 0) / values.length;
    const median = (values[(RUNS - 1) >> 1] + values[RUNS >> 1]) / 2;
    console.log(`${vpName.padEnd(22)} ${name.padEnd(22)} mean ${mean.toFixed(4)}  median ${median.toFixed(4)}  min ${values[0].toFixed(4)}  max ${values.at(-1).toFixed(4)}`);
  }
}
await browser.close();
server.close();
fs.rmSync(work, { recursive: true, force: true });
