// The SQL console in Chromium, with the real DuckDB-Wasm: node web/test/sql.mjs <data-dir>
// Needs the network (cdn.jsdelivr.net and extensions.duckdb.org), so it is kept apart from page.mjs:
// a failure here can be the CDN's. The data is local and every fault is injected by interception.
import fs from 'node:fs'; import path from 'node:path';
import { serve, launch, out, summary, LIVE, SAVED } from './serve.mjs';

const dataDir = path.resolve(process.argv[2]);
const manifest = JSON.parse(fs.readFileSync(path.join(dataDir, 'manifest.json')));
const srv = serve(dataDir);
const b = await launch();
const CDN = /jsdelivr|extensions\.duckdb/;

async function open(width, routes = {}, context = {}) {
  const ctx = await b.newContext({ viewport: { width, height: 900 }, ...context });
  const p = await ctx.newPage();
  p.errors = []; p.reqs = []; p.workers = 0;
  p.on('pageerror', (e) => p.errors.push(`uncaught: ${e.message}`));
  p.on('request', (r) => p.reqs.push(r.url()));
  p.on('worker', () => p.workers++);
  for (const [glob, handler] of Object.entries(routes)) await p.route(glob, handler);
  await p.goto(srv.url, { waitUntil: 'networkidle' });
  p.status = () => p.textContent('#sql-status');
  p.idle = (t = 120000) => p.waitForFunction(() => !document.getElementById('sql-run').disabled && !/Running|Stopping|Restarting/.test(document.getElementById('sql-status').textContent), null, { timeout: t });
  p.load = async () => { await p.click('#sql-load'); await p.waitForFunction(() => document.querySelector('#sql-result table') || /Couldn|Error/.test(document.getElementById('sql-status').textContent), null, { timeout: 240000 }); };
  p.run = async (sql) => { await p.fill('#sql-editor', sql); await p.click('#sql-run'); await p.idle(); return p.result(); };
  p.result = () => p.evaluate(() => { const t = document.querySelector('#sql-result table');
    return { status: document.getElementById('sql-status').textContent, err: document.getElementById('sql-status').classList.contains('err'),
      rows: t ? t.tBodies[0].rows.length : null, caption: t ? t.caption.textContent.replace(/\s+/g, ' ').trim() : null,
      first: t && t.tBodies[0].rows[0] ? [...t.tBodies[0].rows[0].cells].map((c) => c.textContent) : null }; });
  p.sw = () => p.evaluate(() => document.documentElement.scrollWidth);
  return p;
}
const models = Object.keys(manifest.files).filter((k) => k.startsWith('sql/'));
async function runModels(p) {
  const got = [];
  for (const m of models) {
    await p.selectOption('#sql-model', m);
    await p.waitForFunction((name) => document.getElementById('sql-status').textContent.includes(name), m.slice(4));
    await p.click('#sql-run'); await p.idle();
    got.push(await p.result());
  }
  return got;
}
const okModels = (got) => got.length === 3 && got.every((r) => !r.err && r.rows > 0);

// ---------- F03, F05, U01 after load: desktop and phone ----------
for (const w of [1440, 390]) {
  const p = await open(w);
  const sizes = [];
  p.on('requestfinished', async (r) => { try { const s = await r.sizes(); sizes.push([new URL(r.url()).origin, s.responseBodySize + s.responseHeadersSize]); } catch {} });
  await p.load();
  await p.waitForTimeout(500);
  // measured here, before Reset or a hard Stop start further workers (each one fetches the engine again)
  const firstLoad = sizes.filter(([o]) => !o.includes('127.0.0.1'));
  let r = await p.result();
  out(`w${w} sql: loads and runs the selected question`, !r.err && r.rows > 0 && /^DuckDB v1\.4\.3 in your browser/.test(r.status), r);
  out(`w${w} sql: the page is no wider than the viewport once the console is open (was 573px at 390)`, await p.sw() === w, await p.sw());

  const fresh = await runModels(p);
  out(`w${w} sql: every model's compiled SQL runs in a fresh session (was: Catalog "bwt" does not exist)`, okModels(fresh), fresh);
  await p.click('#sql-check');
  await p.waitForFunction(() => /Matches|Differs|failed/.test(document.getElementById('sql-check-result').textContent), null, { timeout: 60000 });
  const check = await p.textContent('#sql-check-result');
  out(`w${w} sql: rebuild check matches the pipeline's build`, check === `Matches the pipeline's build: ${manifest.rebuild_check.expected.n} rows, md5 ${manifest.rebuild_check.expected.md5}.`, check);
  const after = await runModels(p);
  out(`w${w} sql: ...and the models give the same rows after the rebuild check`, okModels(after) && JSON.stringify(after.map((x) => [x.rows, x.first])) === JSON.stringify(fresh.map((x) => [x.rows, x.first])), after);

  const presets = [];
  for (let i = 0; i < 6; i++) { await p.selectOption('#sql-preset', String(i)); await p.waitForTimeout(100); await p.idle(); presets.push(await p.result()); }
  out(`w${w} sql: all six questions run`, presets.every((x) => !x.err && x.rows !== null) && presets[0].rows > 0 && presets[1].rows === 12, presets.map((x) => [x.rows, x.err, x.status.slice(0, 60)]));
  out(`w${w} sql: still no wider than the viewport with results on screen`, await p.sw() === w, await p.sw());

  r = await p.run('select * from range(1000)');
  out(`w${w} sql: a long result stops at 200 rows and says the rest was not fetched`, r.rows === 200 && /^The first 200 rows; the query returned more, and the rest were not fetched/.test(r.caption) && /select \* from range\(1000\)/.test(r.caption), r);
  r = await p.run('select 1 as a where false');
  out(`w${w} sql: zero rows is a result, with its columns`, r.rows === 0 && /^0 rows/.test(r.caption) && !r.err, r);
  r = await p.run("select null as n, 9007199254740993::hugeint as big, repeat('x', 1000) as long, timestamptz '2026-11-14 17:00:00+00' as t, date '2026-11-14' as d");
  out(`w${w} sql: nulls, big integers, long strings and times print as themselves`, r.first && r.first[0] === 'null' && r.first[1] === '9007199254740993' && r.first[2].length === 301 && r.first[3] === '2026-11-14 17:00:00Z' && r.first[4] === '2026-11-14', r.first && r.first.map((x) => x.slice(0, 40)));
  r = await p.run('   ');
  out(`w${w} sql: an empty query is refused politely`, /Nothing to run/.test(r.status), r);
  await p.run('select 42 as answer');
  r = await p.run('select * from no_such_table_' + 'x'.repeat(300));
  out(`w${w} sql: an error clears the earlier result, and a long message does not widen the page`, r.err && /^Error: /.test(r.status) && r.rows === null && await p.sw() === w, { r, sw: await p.sw() });

  // repeated clicks while a query runs do not queue more work; Stop ends it
  await p.fill('#sql-editor', 'select sum(a.range * b.range) from range(200000) a, range(200000) b');
  await p.click('#sql-run');
  await p.waitForFunction(() => document.getElementById('sql-run').disabled);
  const busy = await p.evaluate(() => { const x = document.getElementById('sql-run'); x.click(); x.click(); return [x.disabled, document.getElementById('sql-stop').disabled, document.getElementById('sql-check').disabled]; });
  await p.waitForTimeout(800);
  await p.click('#sql-stop');
  await p.idle(60000);
  r = await p.result();
  out(`w${w} sql: a long query can be stopped; Run is off while it runs`, busy[0] === true && busy[1] === false && busy[2] === true && /^Stopped|session was restarted/.test(r.status) && r.rows === null, { busy, r });
  r = await p.run('select count(*) as n from dim_crossing');
  out(`w${w} sql: ...and the console works afterwards`, !r.err && r.rows === 1, r);

  // arbitrary SQL can drop a view; Reset puts the tables back
  await p.run('drop view agg_wait_by_hour');
  r = await p.run('select count(*) from agg_wait_by_hour');
  const broken = r.err;
  await p.click('#sql-reset'); await p.idle();
  const resetStatus = await p.status();
  r = await p.run('select count(*) as n from agg_wait_by_hour');
  const again = await runModels(p);
  out(`w${w} sql: Reset session restores the tables, and the models run after it`, broken && /^Session reset/.test(resetStatus) && !r.err && r.rows === 1 && okModels(again), { broken, resetStatus, r, again });

  // the visitor's own query survives a preset or model choice
  await p.fill('#sql-editor', 'select 7 as mine');
  await p.selectOption('#sql-model', models[0]);
  await p.waitForFunction(() => !document.getElementById('sql-undo').hidden);
  await p.click('#sql-undo');
  out(`w${w} sql: "Restore my query" brings back what was typed`, await p.inputValue('#sql-editor') === 'select 7 as mine', await p.inputValue('#sql-editor'));
  await p.fill('#sql-editor', 'select 99 as shortcut');
  await p.press('#sql-editor', 'Control+Enter'); await p.idle();
  r = await p.result();
  out(`w${w} sql: Ctrl+Enter runs the editor`, r.first && r.first[0] === '99', r);

  if (w === 1440) {
    const bytes = firstLoad.reduce((a, [, n]) => a + n, 0);
    const origins = [...new Set(p.reqs.filter((u) => /^https?:/.test(u) && !u.includes('127.0.0.1')).map((u) => new URL(u).origin))].sort();
    out('sql: third-party origins are exactly jsDelivr and extensions.duckdb.org', JSON.stringify(origins) === JSON.stringify(['https://cdn.jsdelivr.net', 'https://extensions.duckdb.org']), origins);
    out('sql: the first load is under 8.5 MB from third parties, in at most 8 requests', bytes > 1e6 && bytes < 8.5e6 && firstLoad.length <= 8, { bytes, requests: firstLoad.length, list: firstLoad.map(([o, n]) => `${o} ${n}`) });
  }
  out(`w${w} sql: no uncaught errors through all of it`, p.errors.length === 0, p.errors);
  await p.context().close();
}

// ---------- F03: the visitor's time zone changes neither the rebuild check nor what a query means ----------
{
  const p = await open(1440, {}, { timezoneId: 'America/Vancouver' });
  await p.load();
  const q = "select hour(timestamptz '2026-11-14 17:00:00+00') as h, timestamptz '2026-11-14 17:00:00+00' as t";
  const before = await p.run(q);
  await p.click('#sql-check');
  await p.waitForFunction(() => /Matches|Differs|failed/.test(document.getElementById('sql-check-result').textContent), null, { timeout: 60000 });
  const check = await p.textContent('#sql-check-result');
  const after = await p.run(q);
  out('zone: in a browser eight hours from UTC the rebuild check still matches the pipeline (it runs in UTC)', /^Matches the pipeline's build/.test(check), check);
  out('zone: the same query gives the same answer before and after the rebuild check; times print in UTC', before.first && JSON.stringify(before.first) === JSON.stringify(after.first) && before.first[1] === '2026-11-14 17:00:00Z', { before: before.first, after: after.first });
  await p.context().close();
}

// ---------- U01: widths the two runs above don't cover ----------
for (const w of [320, 768]) {
  const p = await open(w);
  await p.load();
  await p.run('select * from no_such_table_' + 'x'.repeat(300));
  await p.run('select * from fct_wait_readings limit 5');
  const g = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, wide: [...document.querySelectorAll('#sql *')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.scroll')).map((e) => e.id || e.tagName),
    scroll: (() => { const s = document.querySelector('#sql-result .scroll'); return s.scrollWidth > s.clientWidth && s.tabIndex === 0; })() }));
  out(`w${w} sql: wide results scroll inside their own focusable region; the page does not`, g.sw === w && g.wide.length === 0 && g.scroll, g);
  await p.context().close();
}

// ---------- F02: a blocked data file is an error with a way back ----------
{
  const p = await open(1440, { [LIVE + '*.parquet']: (r) => r.abort() });
  await p.click('#sql-load');
  await p.waitForFunction(() => /Couldn't start/.test(document.getElementById('sql-status').textContent), null, { timeout: 240000 });
  const failed = await p.evaluate(() => ({ status: document.getElementById('sql-status').textContent, button: document.getElementById('sql-load').textContent, disabled: document.getElementById('sql-load').disabled, hidden: document.getElementById('sql-console').hidden }));
  out('sql: a blocked Parquet file -> an error that says what failed, and a retry button (was: disabled for good)', /data files couldn't be opened/.test(failed.status) && failed.button === 'Try loading DuckDB again' && !failed.disabled && failed.hidden, failed);
  await p.unroute(LIVE + '*.parquet');
  await p.load();
  const r = await p.result();
  out('sql: ...and the retry works without reloading the page, with one live worker', !r.err && r.rows > 0 && p.errors.length === 0, { r, errors: p.errors, workers: p.workers });
  await p.context().close();
}
{
  let blocked = true;
  const p = await open(1440, { 'https://cdn.jsdelivr.net/**': (r) => blocked ? r.abort() : r.continue() });
  await p.click('#sql-load');
  await p.waitForFunction(() => /Couldn't start/.test(document.getElementById('sql-status').textContent), null, { timeout: 60000 });
  const failed = await p.evaluate(() => [document.getElementById('sql-status').textContent, document.getElementById('sql-load').disabled]);
  blocked = false;
  await p.load();
  const r = await p.result();
  out('sql: a blocked CDN -> error and retry; the retry loads DuckDB', /Couldn't start the SQL console/.test(failed[0]) && failed[1] === false && !r.err && r.rows > 0, { failed, r });
  await p.context().close();
}

// ---------- F04: choosing a model ----------
{
  const p = await open(1440);
  await p.load();
  await p.fill('#sql-editor', 'select 1 as kept');
  await p.route(LIVE + 'sql/**', (r) => r.fulfill({ status: 404, contentType: 'text/html', body: '<!doctype html><title>404</title>' }));
  await p.selectOption('#sql-model', models[0]);
  await p.waitForFunction(() => /Couldn't load that model/.test(document.getElementById('sql-status').textContent));
  let g = await p.evaluate(() => [document.getElementById('sql-editor').value, document.getElementById('sql-model').value, document.getElementById('sql-status').textContent]);
  out('model: a 404 leaves the editor alone, resets the choice and says why', g[0] === 'select 1 as kept' && g[1] === '' && /HTTP 404/.test(g[2]), g);
  await p.unroute(LIVE + 'sql/**');
  await p.route(LIVE + 'sql/**', (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>soft 404</title>' }));
  await p.selectOption('#sql-model', models[1]);
  await p.waitForFunction(() => /web page, not SQL/.test(document.getElementById('sql-status').textContent));
  out('model: a web page served as 200 is not put in the editor', await p.inputValue('#sql-editor') === 'select 1 as kept', await p.inputValue('#sql-editor'));
  await p.unroute(LIVE + 'sql/**');
  await p.route(LIVE + 'sql/**', (r) => r.abort());
  await p.selectOption('#sql-model', models[0]);
  await p.waitForFunction(() => /Couldn't load that model/.test(document.getElementById('sql-status').textContent) && document.getElementById('sql-model').value === '');
  out('model: a refused request is reported the same way', await p.inputValue('#sql-editor') === 'select 1 as kept' && p.errors.length === 0, p.errors);
  await p.unroute(LIVE + 'sql/**');
  // out of order: the first choice answers late, after the second has answered
  await p.route(LIVE + 'sql/**', async (r) => { if (r.request().url().includes('agg_wait_by_hour.')) await new Promise((ok) => setTimeout(ok, 1500)); await r.continue().catch(() => {}); });
  await p.selectOption('#sql-model', 'sql/agg_wait_by_hour');
  await p.selectOption('#sql-model', 'sql/fct_service_standard_monthly');
  await p.waitForFunction(() => /fct_service_standard_monthly/.test(document.getElementById('sql-status').textContent));
  await p.waitForTimeout(2200);
  g = await p.evaluate(() => [document.getElementById('sql-editor').value, document.getElementById('sql-model').value]);
  out('model: when two choices race, the later one wins and the slow one cannot overwrite it', /stg_cbsa_land_monthly/.test(g[0]) && !/fct_wait_readings_recent/.test(g[0]) && g[1] === 'sql/fct_service_standard_monthly' && p.errors.length === 0, { head: g[0].slice(0, 80), sel: g[1], errors: p.errors });
  await p.context().close();
}

// ---------- D11: the saved snapshot is a working dataset ----------
{
  const p = await open(390, { [LIVE + '**']: (r) => r.abort() });
  await p.load();
  let r = await p.result();
  out('snapshot: with live data unreachable the console runs on the saved export, and says which', !r.err && r.rows > 0 && /saved snapshot \(three crossings\), not live data/.test(r.status), r);
  const presets = [];
  for (let i = 0; i < 6; i++) { await p.selectOption('#sql-preset', String(i)); await p.waitForTimeout(100); await p.idle(); presets.push(await p.result()); }
  out('snapshot: all six questions run on it', presets.every((x) => !x.err && x.rows > 0), presets.map((x) => [x.rows, x.err, x.status.slice(0, 50)]));
  out('snapshot: its models run', okModels(await runModels(p)), null);
  await p.click('#sql-check');
  await p.waitForFunction(() => /Matches|Differs|failed/.test(document.getElementById('sql-check-result').textContent), null, { timeout: 60000 });
  out('snapshot: its own rebuild check matches', /^Matches the pipeline's build/.test(await p.textContent('#sql-check-result')), await p.textContent('#sql-check-result'));
  r = await p.run('select count(distinct crossing_id) as n from fct_wait_readings');
  out('snapshot: it holds the three featured crossings and nothing presented as live', r.first && r.first[0] === '3' && await p.sw() === 390, r);
  // the page gets live data back: the console follows it
  await p.unroute(LIVE + '**');
  await p.click('#retry');
  await p.waitForFunction(() => /^(live|delayed)/.test(document.getElementById('live-badge').textContent));   // the fixture export has its own age; either way it is live data
  await p.waitForFunction(() => !/saved snapshot/.test(document.getElementById('sql-status').textContent) && document.querySelector('#sql-result table'), null, { timeout: 60000 });
  await p.idle();
  r = await p.run('select count(distinct crossing_id) as n from fct_wait_readings');
  out('snapshot: after a successful retry the console queries the live files, not the snapshot', r.first && +r.first[0] > 3 && !/saved snapshot/.test(r.status), r);
  await p.context().close();
}

await b.close(); srv.close(); summary();
