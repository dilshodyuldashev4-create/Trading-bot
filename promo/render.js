// Рендер promo.html в кадры: node render.js <outdir> [fps] [times...]
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [out, fpsArg, ...times] = process.argv.slice(2);
  const fps = Number(fpsArg || 30);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  const timings = JSON.parse(require('fs').readFileSync(path.resolve(__dirname, process.env.TIMINGS || 'timings.json'), 'utf8'));
  await page.addInitScript(t => { window.TIMINGS = t; }, timings);
  await page.goto('file://' + path.resolve(__dirname, process.env.PAGE || 'promo.html'));
  await page.evaluate(() => document.fonts.ready);
  const dur = await page.evaluate(() => window.DURATION);
  const list = times.length ? times.map(Number) : Array.from({ length: Math.round(dur * fps) }, (_, i) => i / fps);
  for (let i = 0; i < list.length; i++) {
    await page.evaluate(t => window.seek(t), list[i]);
    await page.screenshot({ path: `${out}/f${String(i).padStart(5, '0')}.jpg`, type: 'jpeg', quality: 92 });
  }
  await browser.close();
})();
