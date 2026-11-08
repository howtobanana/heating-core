// Baut ein Playwright-Skript, das die Seite „Heizung“ mit einem nachgebauten hass rendert (für ui-test-unraid.sh).
// Aufruf: node tests/ui/build.mjs [daten.json] [zusatz.js] > test.mjs   (VARIANTS="A B C" für Entwürfe)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const panel = readFileSync(`${here}/../../custom_components/heating_core/frontend/heating-core-panel.js`, "utf8");
const data = readFileSync(process.argv[2] || `${here}/perg.json`, "utf8");
const extra = process.argv[3] ? readFileSync(process.argv[3], "utf8") : "";
const variants = (process.env.VARIANTS || "").split(" ").filter(Boolean);

const THEMES = {
  light: "--primary-background-color:#f5f6f8;--secondary-background-color:#eceff3;--card-background-color:#fff;--primary-text-color:#1f2328;--secondary-text-color:#69707a;--divider-color:#e1e4e8;--primary-color:#03a9f4;--text-primary-color:#fff;",
  dark: "--primary-background-color:#111318;--secondary-background-color:#1e2127;--card-background-color:#1a1c21;--primary-text-color:#e6e8eb;--secondary-text-color:#9aa1ab;--divider-color:#2d3138;--primary-color:#03a9f4;--text-primary-color:#fff;",
};

const html = (theme, variant) => `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;font-family:Roboto,system-ui,sans-serif;${THEMES[theme]}}</style></head><body>
<script>window.__variant=${JSON.stringify(variant || "")};</script>
<script>${panel}</script><script>${extra}</script>
<script>
  const raw = ${data};
  const hass = { states: {}, entities: {}, devices: {}, callService: () => {} };
  for (const [id, e] of Object.entries(raw)) {
    hass.states[id] = { entity_id: id, state: e.state, attributes: e.attributes };
    hass.entities[id] = { entity_id: id, platform: e.key === "x" ? "schedule" : "heating_core", device_id: e.device, translation_key: e.key };
    hass.devices[e.device] = { name: e.device, model: e.model || hass.devices[e.device]?.model };
  }
  const el = document.createElement(window.__variant ? "heating-core-prototype" : "heating-core-panel");
  el.narrow = innerWidth < 870;
  document.body.appendChild(el);
  el.hass = hass;
</script></body></html>`;

const shots = [];
for (const v of variants.length ? variants : [""]) {
  for (const [w, h, dev] of [[1280, 900, "desktop"], [390, 844, "handy"]]) {
    for (const theme of ["light", "dark"]) shots.push({ name: `${v ? v + "-" : ""}${dev}-${theme}`, w, h, html: html(theme, v) });
  }
}

process.stdout.write(`import { chromium } from 'playwright';
const shots = ${JSON.stringify(shots)};
const browser = await chromium.launch();
for (const s of shots) {
  const page = await browser.newPage({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 2 });
  page.on('pageerror', (e) => console.log(s.name, 'Fehler:', e.message));
  await page.setContent(s.html);
  await page.waitForTimeout(400);
  await page.screenshot({ path: '/out/' + s.name + '.png', fullPage: true });
  console.log('ok', s.name);
  await page.close();
}
await browser.close();
`);
