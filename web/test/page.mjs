// Page checks in Chromium. Usage: node web/test/page.mjs <data-dir> [--sql]
//   <data-dir> holds an export (manifest.json, status.json, ...), served at /border-waits-pipeline/data/v1/.
//   --sql also loads DuckDB-Wasm from jsDelivr and runs the rebuild check (needs the network).
import { createRequire } from 'node:module';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const { chromium } = createRequire(import.meta.url)('playwright');
const web = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const dataDir = path.resolve(process.argv[2]);
const withSql = process.argv.includes('--sql');
const T = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.sql': 'text/plain',
  '.parquet': 'application/octet-stream', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
let dataOff = false;
const srv = http.createServer((q, s) => {
  const p = decodeURIComponent(q.url.split(/[?#]/)[0]);
  let f = p.startsWith('/border-waits/') ? path.join(web, p.slice('/border-waits/'.length))
    : p.startsWith('/border-waits-pipeline/data/v1/') && !dataOff ? path.join(dataDir, p.slice('/border-waits-pipeline/data/v1/'.length)) : null;
  if (f && fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!f || !fs.existsSync(f)) { s.writeHead(404); return s.end(); }
  const body = fs.readFileSync(f);
  const range = /bytes=(\d+)-(\d*)/.exec(q.headers.range || '');
  if (range) {
    const a = +range[1], b = range[2] ? +range[2] : body.length - 1;
    s.writeHead(206, { 'content-type': T[path.extname(f)] || 'application/octet-stream', 'content-range': `bytes ${a}-${b}/${body.length}`, 'accept-ranges': 'bytes', 'content-length': b - a + 1 });
    return s.end(body.subarray(a, b + 1));
  }
  s.writeHead(200, { 'content-type': T[path.extname(f)] || 'application/octet-stream', 'accept-ranges': 'bytes' }); s.end(body);
}).listen(0);
const base = `http://127.0.0.1:${srv.address().port}/border-waits/`;
const out = (k, ok, v) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${k} ${JSON.stringify(v)}`); if (!ok) process.exitCode = 1; };
const b = await chromium.launch();

for (const [w, h] of [[390, 844], [1440, 900]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  const errors = [], reqs = [];
  p.on('console', (m) => m.type() === 'error' && !/404/.test(m.text()) && errors.push(m.text()));
  p.on('pageerror', (e) => errors.push(e.message));
  p.on('request', (r) => reqs.push(r.url()));
  await p.goto(base, { waitUntil: 'networkidle' });
  const g = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, now: document.querySelectorAll('#now-table tbody tr').length,
    chart: !!document.querySelector('#chart svg'), pipe: document.getElementById('pipeline').textContent.includes('Last successful run'),
    note: document.getElementById('data-note').textContent, sql: !document.getElementById('sql-load').disabled, zeros: [...document.querySelectorAll('#now-table td.num')].filter((td) => td.textContent === '0').length }));
  out(`w${w} live: no errors, no sideways scroll`, errors.length === 0 && g.sw === w, { errors, sw: g.sw });
  out(`w${w} live: 3 crossings, chart, pipeline, SQL enabled, no fallback note`, g.now === 3 && g.chart && g.pipe && g.sql && g.note === '', g);
  const extra = await p.evaluate(() => [document.getElementById('collecting').textContent, document.getElementById('live-badge').textContent]);
  out(`w${w} live: "Collecting data since" and the live badge, both from the manifest`, /^Collecting data since \w/.test(extra[0]) && /^live last run \d+ (min|h) ago · [\d,]+ readings$/.test(extra[1]), extra);
  out(`w${w} live: nothing from jsDelivr or extensions.duckdb.org before the click`, !reqs.some((u) => /jsdelivr|extensions\.duckdb/.test(u)), reqs.filter((u) => !u.includes('127.0.0.1')));
  if (withSql && w === 1440) {
    const before = reqs.length;
    const sizes = [];
    p.on('requestfinished', async (r) => { try { const s = await r.sizes(); sizes.push([new URL(r.url()).origin, s.responseBodySize + s.responseHeadersSize]); } catch {} });
    await p.click('#sql-load');
    await p.waitForFunction(() => document.querySelector('#sql-result table') || /Error|Couldn/.test(document.getElementById('sql-status').textContent), null, { timeout: 180000 });
    await p.click('#sql-check');
    await p.waitForFunction(() => /Matches|Differs|failed/.test(document.getElementById('sql-check-result').textContent), null, { timeout: 60000 });
    const after = reqs.slice(before).filter((u) => !u.startsWith('blob:'));
    const ext = sizes.filter(([o]) => !o.includes('127.0.0.1'));
    const bytes = ext.reduce((a, [, n]) => a + n, 0);
    const origins = [...new Set(after.map((u) => new URL(u).origin).filter((o) => !o.includes('127.0.0.1')))].sort();
    const st = await p.evaluate(() => [document.getElementById('sql-status').textContent, document.getElementById('sql-check-result').textContent]);
    out('sql: rebuild check matches', /^Matches/.test(st[1]), st);
    out('sql: third-party origins exactly jsDelivr + extensions.duckdb.org', JSON.stringify(origins) === JSON.stringify(['https://cdn.jsdelivr.net', 'https://extensions.duckdb.org']), origins);
    out('sql: under 8.5 MB from third parties, at most 8 requests', bytes < 8.5e6 && ext.length <= 8, { bytes, requests: ext.length, list: ext.map(([o, n]) => `${o} ${n}`) });
  }
  await p.close();
}

dataOff = true;
const p = await b.newPage({ viewport: { width: 390, height: 844 } });
await p.goto(base, { waitUntil: 'networkidle' });
const f = await p.evaluate(() => ({ note: document.getElementById('data-note').textContent, disabled: document.getElementById('sql-load').disabled,
  status: document.getElementById('sql-status').textContent, now: document.querySelectorAll('#now-table tbody tr').length }));
out('fallback: saved-snapshot line, SQL disabled, page still renders', /^Showing a saved snapshot from /.test(f.note) && f.disabled && f.status === 'SQL needs the live data files' && f.now === 3, f);
await b.close(); srv.close();
