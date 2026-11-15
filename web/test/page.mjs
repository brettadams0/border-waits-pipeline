// Page checks in Chromium, offline and deterministic: node web/test/page.mjs <data-dir>
//   <data-dir> holds an export (manifest.json, status.json, ...), served at /border-waits-pipeline/data/v1/.
//   It must be exported within minutes of its newest poll, as the pipeline's and CI's exports are: the
//   test's "now" is ten minutes after the export, and a "live" badge is expected at that moment.
// Every fault is injected by intercepting the page's own requests; nothing real is broken and the
// clock is the test's. The SQL console needs DuckDB-Wasm from the network: see sql.mjs.
import fs from 'node:fs'; import path from 'node:path';
import { serve, launch, out, summary, LIVE, SAVED, json, stamp } from './serve.mjs';

const dataDir = path.resolve(process.argv[2]);
const manifest0 = JSON.parse(fs.readFileSync(path.join(dataDir, 'manifest.json')));
const summary0 = JSON.parse(fs.readFileSync(path.join(dataDir, manifest0.files.summary.url)));
const clone = (o) => JSON.parse(JSON.stringify(o));
const T0 = Date.parse(manifest0.generated_at) + 10 * 60000;   // "now": ten minutes after the export
const MIN = 60000;
const srv = serve(dataDir);
const b = await launch();

// Opens the page with the test's clock and any intercepted requests; collects errors and requests.
async function open(width, { routes = {}, now = T0, height = 844 } = {}) {
  const ctx = await b.newContext({ viewport: { width, height } });
  const p = await ctx.newPage();
  p.errors = []; p.reqs = [];
  p.on('console', (m) => m.type() === 'error' && !/404|Failed to load resource|net::ERR/.test(m.text()) && p.errors.push(m.text()));
  p.on('pageerror', (e) => p.errors.push(`uncaught: ${e.message}`));
  p.on('request', (r) => p.reqs.push(r.url()));
  await p.clock.install({ time: new Date(now) });
  for (const [glob, handler] of Object.entries(routes)) await p.route(glob, handler);
  await p.goto(srv.url, { waitUntil: 'domcontentloaded' });
  p.settle = () => p.waitForFunction(() => document.getElementById('now').getAttribute('aria-busy') === 'false', null, { timeout: 15000 });
  p.state = () => p.evaluate(() => ({
    note: document.getElementById('data-note').textContent, badge: document.getElementById('live-badge').textContent,
    retry: !document.getElementById('retry').hidden, saved: !document.getElementById('use-saved').hidden,
    sql: !document.getElementById('sql-load').disabled, sw: document.documentElement.scrollWidth,
    rows: document.querySelectorAll('#now-table tbody tr th[scope="row"]').length }));
  // the text of a reading: crossing index, 'To Canada' | 'To the US', lane index
  p.reading = (crossing, direction, lane) => p.evaluate(([c, d, l]) => {
    const row = [...document.querySelectorAll('#now-table tbody')][c] && [...document.querySelectorAll('#now-table tbody')][c].querySelectorAll('tr');
    const tr = row && [...row].find((r) => r.querySelector('th[scope="row"]')?.textContent.startsWith(d));
    const td = tr && tr.querySelectorAll('td')[l];
    return td ? { text: [...td.children].map((e) => e.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean).join(' '), cls: td.className, meter: td.querySelector('.meter')?.getAttribute('style') || '' } : null;
  }, [crossing, direction, lane]);
  return p;
}
// Serves a modified export: manifest and summary are passed through `change`, status through `status`.
const live = (change = () => {}, status) => {
  const m = clone(manifest0), s = clone(summary0);
  change(m, s);
  return {
    [LIVE + 'manifest.json']: (r) => r.fulfill(json(m)),
    [LIVE + manifest0.files.summary.url]: (r) => r.fulfill(json(s)),
    ...(status === undefined ? {} : { [LIVE + 'status.json']: (r) => status === null ? r.fulfill({ status: 404 }) : r.fulfill(json(status)) }),
  };
};
const series = (s) => { const r = s.latest[0]; return (x) => x.crossing_id === r.crossing_id; };

// ---------- the page as it normally loads, at four widths (U01 before SQL, U02, D02) ----------
for (const w of [320, 390, 768, 1440]) {
  const p = await open(w);
  await p.settle();
  const g = await p.evaluate(() => {
    const svg = document.querySelector('#chart svg'), box = svg.getBoundingClientRect();
    const overflow = [...document.querySelectorAll('main *')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.scroll')).map((e) => e.tagName + '.' + e.className).slice(0, 5);
    return { sw: document.documentElement.scrollWidth, overflow,
      scale: box.width / svg.viewBox.baseVal.width, font: parseFloat(getComputedStyle(svg.querySelector('text')).fontSize),
      heat: [...document.querySelectorAll('#heat button')].map((x) => x.querySelectorAll('.cells i').length), map: document.querySelectorAll('#map .x').length,
      runs: document.querySelectorAll('.runs i').length, how: document.querySelectorAll('#how > div b').length,
      pipe: document.getElementById('pipeline').textContent, collecting: document.getElementById('collecting').textContent,
      small: [...document.querySelectorAll('main button:not([hidden]), main select, main summary, main a.button')].filter((e) => e.offsetParent && e.getBoundingClientRect().height < 24).length };
  });
  const st = await p.state();
  out(`w${w}: no errors, nothing wider than the viewport`, p.errors.length === 0 && g.sw === w && g.overflow.length === 0, { errors: p.errors, sw: g.sw, overflow: g.overflow });
  out(`w${w}: live badge, no notice, 3 crossings x 2 directions, SQL button ready`, /^live last run \d+ min ago · [\d,]+ readings$/.test(st.badge) && st.note === '' && !st.retry && st.rows === 6 && st.sql, st);
  out(`w${w}: chart drawn at 1:1, so its labels are a real ${g.font}px (was 11px scaled to 3.9px at 320)`, Math.abs(g.scale - 1) < 0.01 && g.font >= 11, g);
  out(`w${w}: schematic, 12 x 24 heat grid, run strip and 4 step tiles are drawn from the data`, g.map === 3 && g.heat.length === 12 && g.heat.every((n) => n === 24) && g.runs === manifest0.cadence.recent_runs.filter((t) => Date.parse(t) >= T0 - 7 * 864e5).length && g.how === 4, g);
  out(`w${w}: pipeline summary and collecting line come from the manifest; no control under 24px`, /Last successful run: .*\(10 min ago\)/.test(g.pipe) && /^Collecting since \w/.test(g.collecting) && g.small === 0, g);
  out(`w${w}: nothing from jsDelivr or extensions.duckdb.org before the click`, !p.reqs.some((u) => /jsdelivr|extensions\.duckdb/.test(u)), p.reqs.filter((u) => !u.includes('127.0.0.1')));
  await p.context().close();
}

// ---------- D01: the latest reading is shown whole ----------
{
  const p = await open(390, { routes: live((m, s) => {
    const mine = s.latest.filter(series(s));
    const set = (d, l, v) => Object.assign(mine.find((r) => r.direction === d && r.lane === l), v);
    set('to_us', 'travellers', { delay_min: null, is_open: null, status_raw: 'Update Pending', source_updated_at: null });
    set('to_us', 'commercial', { delay_min: null, is_open: false, status_raw: 'Lanes Closed', source_updated_at: null });
    set('to_canada', 'travellers', { delay_min: null, is_open: null, status_raw: 'Not Applicable' });
    s.latest.splice(s.latest.indexOf(mine.find((r) => r.direction === 'to_canada' && r.lane === 'commercial')), 1);
  }) });
  await p.settle();
  const c = summary0.crossings.findIndex((x) => x.crossing_id === summary0.latest[0].crossing_id);
  const got = [await p.reading(c, 'To the US', 0), await p.reading(c, 'To the US', 1), await p.reading(c, 'To Canada', 0), await p.reading(c, 'To Canada', 1)];
  out('latest: pending, closed, not applicable and missing are words, never an older number', /^Update pending checked .+ ago/.test(got[0].text) && /^Closed checked .+ ago/.test(got[1].text)
    && /^Not applicable updated/.test(got[2].text) && /^No data not in the feed$/.test(got[3].text) && got.every((g) => !/^\d|No delay/.test(g.text)) && p.errors.length === 0, { got, errors: p.errors });
  out('latest: a lane without an estimate has an empty meter', got.every((g) => g.meter === ''), got);
  await p.context().close();
}

// ---------- D02: freshness per reading; ages move on their own; the badge is honest ----------
{
  const c0 = summary0.crossings[0].crossing_id, c1 = summary0.crossings[1].crossing_id;
  const p = await open(390, { routes: live((m, s) => {
    m.generated_at = new Date(T0 - 10 * MIN).toISOString();
    for (const r of s.latest) Object.assign(r, { delay_min: 15, is_open: true, status_raw: 'x', observed_at: stamp(T0 - 10 * MIN), source_updated_at: stamp(T0 - 30 * MIN) });
    const set = (c, d, v) => s.latest.filter((r) => r.crossing_id === c && r.direction === d).forEach((r) => Object.assign(r, v));
    set(c0, 'to_canada', { source_updated_at: stamp(T0 - 87 * MIN) });                      // an older agency update
    set(c0, 'to_us', { source_updated_at: stamp(T0 + 20 * MIN) });                          // stamped after the fetch (CBP's coming hour)
    set(c1, 'to_canada', { source_updated_at: stamp(T0 - 200 * MIN), delay_min: 90 });      // past the stale threshold
    set(c1, 'to_us', { source_updated_at: null, delay_min: null, is_open: false });         // no source time at all
  }) });
  await p.settle();
  const before = p.reqs.length;
  const a = [await p.reading(0, 'To Canada', 0), await p.reading(0, 'To the US', 0), await p.reading(1, 'To Canada', 0), await p.reading(1, 'To the US', 0)];
  out('freshness: each direction shows its own age; a future stamp counts from the fetch; no time says "checked"',
    a[0].text === '15 min updated 1 h 27 min ago' && a[1].text === '15 min updated 10 min ago' && a[2].text === '90 min updated 3 h 20 min ago · stale' && / old/.test(a[2].cls)
    && a[3].text === 'Closed checked 10 min ago' && a[2].meter === '--w:100%' && a[0].meter === '--w:25%', a);
  out('freshness: fresh export is "live"', /^live last run 10 min ago/.test((await p.state()).badge), await p.state());
  await p.clock.fastForward(3 * 60 * MIN);   // the tab stays open for three hours
  await p.waitForFunction(() => /^delayed/.test(document.getElementById('live-badge').textContent), null, { timeout: 5000 }).catch(() => {});
  const later = [await p.reading(0, 'To Canada', 0), await p.reading(0, 'To the US', 0)], st = await p.state();
  out('freshness: an open tab ages past the threshold: readings turn stale, the badge turns "delayed", nothing is refetched',
    later[0].text === '15 min updated 4 h 27 min ago · stale' && later[1].text === '15 min updated 3 h 10 min ago · stale' && /^delayed last run 3 h 10 min ago/.test(st.badge) && p.reqs.length === before, { later, st, requests: p.reqs.length - before });
  await p.context().close();

  const old = await open(390, { routes: live((m) => { m.generated_at = new Date(T0 - 300 * MIN).toISOString(); }) });
  await old.settle();
  out('freshness: an old export that "succeeded" is not live', /^delayed last run 5 h 0 min ago/.test((await old.state()).badge), await old.state());
  await old.context().close();

  const failing = await open(390, { routes: live(() => {}, { run_id: 'x-1', time: new Date(T0 - 5 * MIN).toISOString(), result: 'failure', failed_step: 'dbt build', failed_stage: 'build', collected: true, run_url: 'https://example.test/run', last_success: null }) });
  await failing.settle();
  const f = await failing.evaluate(() => [document.getElementById('live-badge').textContent, document.getElementById('pipeline').textContent]);
  out('freshness: a failed last attempt over older data says so, and that the readings were stored', /^failing the last run failed 5 min ago; data from \d+ min ago/.test(f[0]) && /failed at dbt build/.test(f[1]) && /readings were stored/.test(f[1]), f);
  await failing.context().close();
}

// ---------- F01: every way the load can go wrong ends in a state, never in half a page ----------
{
  const abort = (r) => r.abort();
  let p = await open(390, { routes: { [LIVE + '**']: abort } });
  await p.settle();
  let st = await p.state();
  out('startup: live unreachable -> saved snapshot, labelled, with a retry; SQL still offered', /^Live data couldn't be loaded \(.+\)\. Showing a saved snapshot from \w+ \d+, \d{4} instead\.$/.test(st.note) && /^snapshot readings of .*not current/.test(st.badge) && st.retry && st.rows === 6 && st.sql && p.errors.length === 0, { st, errors: p.errors });
  const now = await p.evaluate(() => [document.getElementById('now-note').textContent, document.getElementById('pipeline').textContent, document.querySelectorAll('#chart circle').length, document.querySelector('#now-table td small').textContent]);
  out('startup: snapshot readings carry their date, not "ago", and the chart has points', /^A saved snapshot: .* Not current\.$/.test(now[0]) && /A saved snapshot: readings up to/.test(now[1]) && now[2] > 0 && /\d{4}/.test(now[3]) && !/ago/.test(now[3]), now);
  await p.unroute(LIVE + '**');
  await p.click('#retry'); await p.settle();
  st = await p.state();
  out('startup: Retry reaches live data without a reload', /^live /.test(st.badge) && st.note === '' && !st.retry, st);
  await p.context().close();

  p = await open(390, { routes: { [LIVE + '**']: abort, [SAVED + '**']: abort } });
  await p.settle();
  st = await p.state();
  out('startup: live and snapshot both unreachable -> one message, a retry, no uncaught error, SQL not offered', /^Couldn't load the readings \(live data: .+; saved snapshot: .+\)\.$/.test(st.note) && st.retry && !st.sql && st.badge === 'No data loaded.' && p.errors.length === 0, { st, errors: p.errors });
  await p.unroute(LIVE + '**'); await p.unroute(SAVED + '**');
  await p.click('#retry'); await p.settle();
  out('startup: ...and Retry recovers from that too', /^live /.test((await p.state()).badge) && (await p.state()).sql, await p.state());
  await p.context().close();

  for (const [name, change, reason] of [
    ['a summary with latest: null', (m, s) => { s.latest = null; }, /unexpected summary/],
    ['an unsupported schema_version', (m) => { m.schema_version = 2; }, /unexpected schema_version 2/],
    ['a reading whose delay is text', (m, s) => { s.latest[0].delay_min = '12'; }, /unexpected latest readings/],
    ['an hour outside 0-23', (m, s) => { s.by_hour[0].local_hour = 24; }, /unexpected hourly rows/],
    ['a manifest that names a file on another host', (m) => { m.files.dim_crossing.url = 'https://example.test/x.parquet'; }, /unexpected file dim_crossing/],
    ['a manifest without the summary', (m) => { delete m.files.summary; }, /unexpected manifest/],
  ]) {
    p = await open(390, { routes: live(change) });
    await p.settle();
    st = await p.state();
    out(`startup: ${name} -> saved snapshot, with the reason`, reason.test(st.note) && /^snapshot/.test(st.badge) && st.retry && st.rows === 6 && p.errors.length === 0, { st, errors: p.errors });
    await p.context().close();
  }

  p = await open(390, { routes: { [LIVE + 'manifest.json']: (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Not found</title>' }) } });
  await p.settle();
  out('startup: a web page where JSON should be -> saved snapshot', /not JSON/.test((await p.state()).note) && p.errors.length === 0, await p.state());
  await p.context().close();

  p = await open(390, { routes: { [LIVE + 'manifest.json']: () => { /* never answers */ } } });
  await p.waitForTimeout(300);
  const waiting = await p.evaluate(() => [document.getElementById('live-badge').textContent, document.getElementById('now').getAttribute('aria-busy')]);
  await p.clock.fastForward(8100);
  await p.settle();
  st = await p.state();
  out('startup: a request that never answers is given 8 s, said to be loading meanwhile, then the snapshot is shown', waiting[0] === 'Loading the latest readings…' && waiting[1] === 'true' && /no answer in 8 s/.test(st.note) && /^snapshot/.test(st.badge), { waiting, st });
  await p.context().close();

  p = await open(390, { routes: live(() => {}, null) });
  await p.settle();
  const pipe = await p.evaluate(() => document.getElementById('pipeline').textContent);
  st = await p.state();
  out('startup: status.json missing -> the live readings still show', /^live /.test(st.badge) && st.note === '' && /status not available/.test(pipe), { st, pipe });
  await p.context().close();

  p = await open(390, { routes: live((m, s) => { s.latest = []; s.by_hour = []; }) });
  await p.settle();
  st = await p.state();
  const empty = await p.evaluate(() => [document.getElementById('now-note').textContent, document.querySelector('#now-table td').textContent, document.querySelector('#chart svg').textContent.trim()]);
  out('startup: an export with no readings says so and offers the snapshot', st.note === 'The pipeline has published no readings yet.' && st.saved && !st.retry && /No readings have been published/.test(empty[0]) && /No data/.test(empty[1]) && /not enough days/.test(empty[2]) && p.errors.length === 0, { st, empty, errors: p.errors });
  await p.click('#use-saved'); await p.settle();
  st = await p.state();
  out('startup: ...and "Show the saved snapshot" does', /^Showing the saved snapshot from/.test(st.note) && /^snapshot/.test(st.badge) && st.retry, st);
  await p.context().close();
}

// ---------- D09 / D13: the chart joins neighbours only, and its gates come from the summary ----------
{
  const key = { crossing_id: summary0.crossings[0].crossing_id, direction: 'to_us', lane: 'travellers' };
  const row = (h, days, median = 10 + h, n = days * 2) => ({ ...key, local_hour: h, n, days, valid_days: days, median_delay_min: median, p90_delay_min: median + 12 });
  const chart = async (rows, gates = {}) => {
    const p = await open(390, { routes: live((m, s) => { s.by_hour = rows; s.chart = { ...s.chart, min_days_point: 3, min_days_solid: 7, min_days_band: 14, ...gates }; }) });
    await p.settle();
    for (const [k, v] of Object.entries({ crossing: key.crossing_id, direction: key.direction, lane: key.lane })) await p.selectOption('#pick-' + k, v);
    const g = await p.evaluate(() => ({ lines: [...document.querySelectorAll('#chart polyline')].map((l) => l.getAttribute('points').trim().split(' ').length),
      solid: document.querySelectorAll('#chart circle.dot:not(.few)').length, few: document.querySelectorAll('#chart circle.few').length, gaps: document.querySelectorAll('#chart .gap').length,
      bands: document.querySelectorAll('#chart .band:not(.one)').length, single: document.querySelectorAll('#chart .band.one').length,
      text: document.querySelector('#chart svg').textContent, label: document.querySelector('#chart svg').getAttribute('aria-label'),
      table: [...document.querySelectorAll('#hour-table tbody tr')].map((r) => r.textContent), key: document.getElementById('chart-key').textContent,
      pressed: document.querySelector('#heat button[aria-pressed="true"]')?.getAttribute('aria-label'), errors: 0 }));
    g.errors = p.errors;
    await p.context().close();
    return g;
  };
  let g = await chart([row(6, 8), row(7, 8), row(8, 8), row(10, 8), row(12, 4), row(14, 15), row(15, 15), row(20, 15), row(22, 2)]);
  out('chart: only neighbouring solid hours are joined (6-7-8 and 14-15), never across the empty hour 9', JSON.stringify(g.lines) === '[3,2]' && g.solid === 7 && g.few === 1 && g.gaps === 16 && g.errors.length === 0, g);
  out('chart: the band needs its own gate, per run of neighbours; one eligible hour alone gets a bar, not a wedge', g.bands === 1 && g.single === 1, g);
  out('chart: the table and the label agree with the picture', g.label.includes('7 hours with 7 or more days of estimates, 1 with 3 to 6, 16 with too few to show')
    && g.table[9] === '9:00too few days yet00' && g.table[22] === '22:00too few days yet42' && g.table[12] === '12:0022—84' && g.table[14] === '14:0024363015' && /7 of 24 hours/.test(g.key),
    { label: g.label, rows: [g.table[9], g.table[12], g.table[14], g.table[22]], key: g.key });
  out('chart: the heat grid marks the charted series', /to the us, travellers/i.test(g.pressed || ''), g.pressed);
  g = await chart([row(13, 9)]);
  out('chart: a single hour is a point with no line', g.lines.length === 0 && g.solid === 1 && g.gaps === 23, g);
  g = await chart([]);
  out('chart: no eligible hour says so instead of drawing an empty frame', g.solid + g.few === 0 && /not enough days of estimates yet/.test(g.text) && g.errors.length === 0, g);
  g = await chart([row(6, 8, 0), row(7, 8, 0), row(8, 8, 0)]);
  out('chart: all-zero medians are drawn, on the baseline', JSON.stringify(g.lines) === '[3]' && g.solid === 3, g);
  g = await chart([row(6, 6), row(7, 6), row(8, 2)], { min_days_point: 3, min_days_solid: 6, min_days_band: 6 });
  out('chart: below, at and above a gate (2 / 6 / 6 days against 3 and 6)', g.solid === 2 && g.few === 0 && g.gaps === 22 && g.bands === 1, g);
  g = await chart([{ ...row(6, 9), median_delay_min: null, p90_delay_min: null, n: 0, valid_days: 0 }, row(7, 9)]);
  out('chart: an hour with only closed readings (no median) is a gap, not a zero', g.solid === 1 && g.gaps === 23 && /^6:00too few days yet00$/.test(g.table[6]), { g, row: g.table[6] });
}

// ---------- the heat grid drives the chart ----------
{
  const p = await open(1440, { height: 900 });
  await p.settle();
  await p.click('#heat button >> nth=5');
  const g = await p.evaluate(() => ({ pressed: [...document.querySelectorAll('#heat button')].map((x) => x.getAttribute('aria-pressed')).indexOf('true'),
    picks: ['crossing', 'direction', 'lane'].map((k) => document.getElementById('pick-' + k).value).join('|'), k: document.querySelectorAll('#heat button')[5].dataset.k }));
  out('heat grid: choosing a row charts that series', g.pressed === 5 && g.picks === g.k, g);
  await p.context().close();
}

await b.close(); srv.close(); summary();
