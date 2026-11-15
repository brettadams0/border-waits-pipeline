// Shared by page.mjs and sql.mjs: a static server for the page and one export, and a browser.
import { createRequire } from 'node:module';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const { chromium } = createRequire(import.meta.url)('playwright');
export const web = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const T = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.sql': 'text/plain',
  '.parquet': 'application/octet-stream', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };

// web/ is served at /border-waits/ and dataDir at /border-waits-pipeline/data/v1/, as on the site.
export function serve(dataDir) {
  const srv = http.createServer((q, s) => {
    const p = decodeURIComponent(q.url.split(/[?#]/)[0]);
    let f = p.startsWith('/border-waits/') ? path.join(web, p.slice('/border-waits/'.length))
      : p.startsWith('/border-waits-pipeline/data/v1/') ? path.join(dataDir, p.slice('/border-waits-pipeline/data/v1/'.length)) : null;
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
  return { url: `http://127.0.0.1:${srv.address().port}/border-waits/`, close: () => srv.close() };
}

// A proxy is only needed where the network suite runs behind one.
export const launch = () => chromium.launch(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } } : {});

let failed = 0;
export const out = (name, ok, detail) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + JSON.stringify(detail)}`); if (!ok) { failed++; process.exitCode = 1; } };
export const summary = () => console.log(failed ? `${failed} FAILED` : 'all passed');
export const LIVE = '**/border-waits-pipeline/data/v1/', SAVED = '**/border-waits/fallback/';
export const json = (body) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
// DuckDB's timestamptz text, as the summary carries it
export const stamp = (ms) => new Date(ms).toISOString().replace('T', ' ').replace(/\.\d+Z$/, '+00');
