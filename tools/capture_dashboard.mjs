// Screenshot the live dashboard at a desktop and a phone width, as WebP.
//
// Run once; the output is what gets committed.
//
//   npm i --no-save puppeteer-core@24.10.0
//   CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe" node tools/capture_dashboard.mjs
//
// Writes docs/dashboard-desktop.webp and docs/dashboard-mobile.webp. The page shows
// live data, so a rerun captures whatever the latest export says; the commit that
// adds the images records when they were taken.
import puppeteer from 'puppeteer-core';

const URL = 'https://brettadams0.github.io/border-waits/';
const SHOTS = [
  // Rendered above 1x so each stays sharp when shown at 720 or 360 CSS px.
  // Desktop height stops below the live table: until each local hour has seven
  // readings the by-hour chart beneath it renders empty by design.
  { file: 'docs/dashboard-desktop.webp', viewport: { width: 1280, height: 640, deviceScaleFactor: 1.5 } },
  { file: 'docs/dashboard-mobile.webp', viewport: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
];

const browser = await puppeteer.launch({ executablePath: process.env.CHROME, headless: true });
for (const { file, viewport } of SHOTS) {
  const page = await browser.newPage();
  await page.setViewport(viewport);
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
  await page.goto(URL, { waitUntil: 'networkidle0' });
  // The table and live badge fill from fetched JSON after load.
  await page.waitForFunction(() => /readings/.test(document.getElementById('live-badge')?.textContent ?? ''));
  await page.screenshot({ path: file, type: 'webp', quality: 80 });
  await page.close();
}
await browser.close();
