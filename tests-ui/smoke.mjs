// Browser smoke test za Ingenium UI (Playwright).
// Pokretanje:
//   1) backend mora raditi na :8000
//   2) TOKEN=$(cd backend && .venv/bin/python -c "from app.core.security import create_access_token; import uuid; print(create_access_token(str(uuid.UUID('00000000-0000-0000-0000-000000000010')), str(uuid.UUID('00000000-0000-0000-0000-000000000001'))))")
//   3) npm i playwright && npx playwright install chromium
//   4) TOKEN=$TOKEN node tests-ui/smoke.mjs
import { chromium } from 'playwright';

const token = process.env.TOKEN;
if (!token) { console.error('Postavi TOKEN env var (vidi upute u headeru).'); process.exit(2); }
const BASE = process.env.BASE || 'http://localhost:8000';
const results = [];
const log = (ok, msg) => { results.push({ok, msg}); console.log((ok ? '✅' : '❌') + ' ' + msg); };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// capture console errors
const consoleErrors = [];
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', e => consoleErrors.push('PAGEERROR: ' + e.message));

// inject tokens before app scripts run
await page.addInitScript((t) => {
  localStorage.setItem('aqp_token', t);
  localStorage.setItem('aqp_refresh', t);
}, token);

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

// 0) app loaded, not on login
log(!page.url().includes('/login'), 'App učitan (nije redirect na login): ' + page.url());

// 1) Navigate to Skladište — view se učita (radi i na praznoj bazi)
await page.click(".nav-item:has-text('Skladište')");
await page.waitForTimeout(800);
log(await page.locator('#view-skladiste').isVisible(), 'Skladište view otvoren');
const stockRows = await page.locator('#stock-tbody .stock-row').count();
log(true, `Skladište prikazuje ${stockRows} artikala (prazna baza je OK)`);

// 2) KPI element postoji i sadrži valutu
const kpiVal = await page.locator('#kpi-stock-value').textContent();
log(/€/.test(kpiVal || ''), `KPI vrijednost zaliha: ${kpiVal}`);

// 3) Open "Novi artikl" modal — THE bug we fixed
await page.click("#view-skladiste button:has-text('Novi artikl')");
await page.waitForTimeout(500);
const modal = page.locator('#modal-novi-artikl');
const modalVisible = await modal.isVisible();
log(modalVisible, 'Modal "Novi artikl" se otvorio');

// 4) Invisible-text fix: type into SKU, assert text color contrasts with bg
const uniqueSku = 'UITEST-' + Date.now();   // jedinstven da je test ponovljiv
await page.fill('#na-sku', uniqueSku);
await page.fill('#na-name', 'UI Test Artikl');
const colors = await page.locator('#na-sku').evaluate(el => {
  const s = getComputedStyle(el);
  return { color: s.color, bg: s.backgroundColor };
});
const parseRGB = c => (c.match(/\d+/g) || []).slice(0,3).map(Number);
const [cr,cg,cb] = parseRGB(colors.color);
const [br,bg2,bb] = parseRGB(colors.bg);
const contrast = Math.abs(cr-br) + Math.abs(cg-bg2) + Math.abs(cb-bb);
log(contrast > 150, `Tekst u polju je vidljiv (color=${colors.color} bg=${colors.bg}, kontrast=${contrast})`);

// 5) Fill rest + save → expect new row
await page.fill('#na-qty', '7');
await page.fill('#na-min', '3');
await page.fill('#na-price', '9.99');
await page.click("button:has-text('Spremi artikl')");
await page.waitForTimeout(3500);
const afterSave = await page.locator('#stock-tbody .stock-row').count();
log(afterSave === stockRows + 1, `Artikl spremljen — redova ${stockRows} → ${afterSave}`);

// 6) Open stock panel (movements) on first row
await page.locator('#stock-tbody .stock-row button.icon-btn').first().click();
await page.waitForTimeout(800);
const panelVisible = await page.locator('#stock-panel-overlay').isVisible().catch(() => false);
log(panelVisible, 'Panel kretanja zalihe se otvorio');
await page.screenshot({ path: '/tmp/ingenium-stock-panel.png' });
// close panel
await page.keyboard.press('Escape').catch(()=>{});
await page.locator('#stock-panel-overlay').evaluate(e => e.remove()).catch(()=>{});

// 7) Navigate to Nabava
await page.click(".nav-item:has-text('Nabava')");
await page.waitForTimeout(800);
const nabavaVisible = await page.locator('#view-nabava').isVisible();
const poRows = await page.locator('#po-tbody tr').count();
log(nabavaVisible, `Nabava view otvoren (${poRows} redova u tablici)`);

// 8) Supplier modal (was unreachable before today's fix)
await page.click(".nav-item:has-text('Dobavljači')");
await page.waitForTimeout(500);
await page.click("#view-suppliers button:has-text('Novi dobavljač')").catch(()=>{});
await page.waitForTimeout(400);
const supModalVisible = await page.locator('#modal-novi-dobavljac').isVisible().catch(()=>false);
const supSaveBtn = await page.locator("#modal-novi-dobavljac button:has-text('Spremi dobavljača')").count();
log(supModalVisible && supSaveBtn === 1, `Modal "Novi dobavljač" otvoren + ima Spremi gumb (${supSaveBtn})`);

await page.screenshot({ path: '/tmp/ingenium-final.png', fullPage: false });

console.log('\n--- console errors (' + consoleErrors.length + ') ---');
consoleErrors.slice(0,10).forEach(e => console.log('  ⚠️ ' + e));

const passed = results.filter(r => r.ok).length;
console.log(`\n=== ${passed}/${results.length} UI provjera prošlo ===`);
await browser.close();
process.exit(passed === results.length ? 0 : 1);
