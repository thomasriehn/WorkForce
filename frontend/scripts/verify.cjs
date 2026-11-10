/* eslint-disable no-console */
/**
 * Prüfskript für die gebaute Oberfläche (nicht Teil des Builds).
 *
 * Voraussetzung: Die API läuft auf WF_BASE_URL (Standard http://127.0.0.1:8010) und liefert frontend/dist aus.
 * Das Skript meldet sich als Administrator und als Leser an, besucht jede Ansicht in zwei Fenstergrößen,
 * erstellt Bildschirmfotos unter frontend/screenshots/ und bricht mit Fehlercode ab bei
 *   – Konsolenfehlern oder unbehandelten Ausnahmen,
 *   – Verstößen gegen die Content-Security-Policy,
 *   – fehlgeschlagenen oder unerwartet mit Fehlerstatus beantworteten Anfragen,
 *   – Anfragen an fremde Hosts,
 *   – schreibenden Bedienelementen oder schreibenden Anfragen im Lesezugriff.
 *
 * Aufruf:
 *   WF_ADMIN_USER=… WF_ADMIN_PASS=… WF_READER_USER=… WF_READER_PASS=… node scripts/verify.cjs [--mutations] [--prefix=leer]
 *
 * --mutations legt zusätzlich ein Prüfkonto an und deaktiviert es wieder (zeigt die einmalige Passwortanzeige).
 *
 * Bewusst ausgelöste Fehlerantworten (falsches Passwort, zu kurzer Freigabevermerk, nicht vorhandene Einträge)
 * sind einzeln freigegeben und werden als „erwartet“ protokolliert. Gespeicherte Suchen sind persönliche Daten,
 * die die API auch Lesern erlaubt – sie zählen nicht als schreibende Verwaltungsaktion.
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const BASE = (process.env.WF_BASE_URL || 'http://127.0.0.1:8010').replace(/\/$/, '');
const OUT = path.join(__dirname, '..', 'screenshots');
const WITH_MUTATIONS = process.argv.includes('--mutations');
// Optionaler Vorsatz für die Dateinamen der Bildschirmfotos, z. B. --prefix=leer für einen Lauf ohne Daten.
const PREFIX = (process.argv.find((a) => a.startsWith('--prefix=')) || '').slice(9);
const ROLES = {
  admin: { user: process.env.WF_ADMIN_USER, pass: process.env.WF_ADMIN_PASS },
  reader: { user: process.env.WF_READER_USER, pass: process.env.WF_READER_PASS },
};
const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '820x1180', width: 820, height: 1180 },
];
const MUTATING_LABELS =
  /^(Freigeben|Deaktivieren|Reaktivieren|Status ändern|Manuellen Lauf starten|Begrenzter Testlauf|Budget speichern|Neue Version|Suchbereich anlegen|Karriereseite vormerken|Benutzer anlegen|Passwort zurücksetzen|Zusammenführen|Verwerfen|Zusammenführung lösen|Importieren|Als erledigt markieren|Pausieren|Fortsetzen|Wiederholen|Tagesaggregate berechnen|Auf neue Statistikveröffentlichungen prüfen|Wartung|Ungeklärte Arbeitsorte)/;

const problems = [];
const notes = [];
const visited = [];

function problem(ctx, text) {
  problems.push(`[${ctx}] ${text}`);
  console.log(`  ✗ ${text}`);
}

class Session {
  constructor(browser, role, viewport) {
    this.browser = browser;
    this.role = role;
    this.viewport = viewport;
    this.ctx = `${role} ${viewport.name}`;
    this.allowed = []; // { method, re, status }
    this.expectedUrls = new Set();
    this.pending = [];
  }

  async open() {
    this.context = await this.browser.newContext({ viewport: { width: this.viewport.width, height: this.viewport.height }, locale: 'de-DE', timezoneId: 'Europe/Berlin' });
    await this.context.addInitScript(() => {
      window.__csp = [];
      document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective}: ${e.blockedURI || e.sourceFile || '(inline)'}`));
    });
    this.page = await this.context.newPage();
    const page = this.page;
    page.on('console', (msg) => {
      if (msg.type() === 'error') this.pending.push({ kind: 'console', text: msg.text(), url: msg.location().url || '' });
    });
    page.on('pageerror', (err) => problem(this.ctx, `Unbehandelte Ausnahme: ${err.message}`));
    page.on('requestfailed', (req) => {
      const failure = req.failure()?.errorText || '';
      if (failure.includes('ERR_ABORTED')) return; // von der Oberfläche selbst abgebrochen (überholte Anfrage, Seitenwechsel)
      problem(this.ctx, `Anfrage fehlgeschlagen: ${req.method()} ${req.url()} (${failure})`);
    });
    page.on('request', (req) => {
      const url = req.url();
      if (url.startsWith('data:') || url.startsWith('blob:')) return;
      if (!url.startsWith(BASE)) problem(this.ctx, `Anfrage an fremden Host: ${url}`);
      if (this.role === 'reader' && req.method() !== 'GET' && !/\/api\/(auth\/(login|logout)|saved-searches)/.test(url)) {
        problem(this.ctx, `Schreibende Anfrage im Lesezugriff: ${req.method()} ${url}`);
      }
    });
    page.on('response', (res) => {
      if (res.status() < 400) return;
      const req = res.request();
      const hit = this.allowed.find((a) => a.method === req.method() && a.re.test(res.url()) && a.status === res.status());
      if (hit) {
        this.expectedUrls.add(res.url());
        notes.push(`[${this.ctx}] erwartet: ${req.method()} ${res.url().replace(BASE, '')} → ${res.status()}`);
      } else {
        problem(this.ctx, `Unerwarteter Fehlerstatus ${res.status()}: ${req.method()} ${res.url().replace(BASE, '')}`);
      }
    });
  }

  allow(method, re, status) {
    this.allowed.push({ method, re, status });
  }

  /** Konsolenfehler auswerten: „Failed to load resource“ zu erwarteten Antworten ist in Ordnung. */
  async flush(step) {
    await this.page.waitForTimeout(150);
    for (const item of this.pending.splice(0)) {
      const expected = /Failed to load resource/.test(item.text) && [...this.expectedUrls].some((u) => item.url === u || item.url.startsWith(u.split('?')[0]));
      if (!expected) problem(this.ctx, `Konsolenfehler (${step}): ${item.text} ${item.url}`);
    }
    const csp = await this.page.evaluate(() => (window.__csp || []).splice(0)).catch(() => []);
    for (const v of csp) problem(this.ctx, `CSP-Verstoß (${step}): ${v}`);
  }

  async settle() {
    const page = this.page;
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    await page.waitForFunction(() => document.querySelectorAll('.spinner:not(.spinner--inline)').length === 0, null, { timeout: 20000 }).catch(() => problem(this.ctx, 'Ladeanzeige verschwindet nicht'));
    await page.waitForTimeout(350);
  }

  async shot(name, fullPage = true) {
    const file = path.join(OUT, `${PREFIX ? `${PREFIX}-` : ''}${this.role}-${this.viewport.name}-${name}.png`);
    await this.page.screenshot({ path: file, fullPage });
  }

  async checkReaderControls(step) {
    if (this.role !== 'reader') return;
    const marked = await this.page.locator('[data-admin-action]').count();
    if (marked > 0) problem(this.ctx, `${step}: ${marked} schreibende Bedienelemente im Lesezugriff sichtbar`);
    const labels = await this.page.locator('main button:visible, main a.btn:visible').allInnerTexts();
    for (const label of labels) {
      if (MUTATING_LABELS.test(label.trim())) problem(this.ctx, `${step}: schreibende Schaltfläche im Lesezugriff: „${label.trim()}“`);
    }
  }

  /** Öffnet eine Ansicht, wartet auf die Daten, prüft Grundanforderungen und fotografiert sie. */
  async visit(name, route, opts = {}) {
    const page = this.page;
    console.log(`- ${this.ctx}: ${name} (${route})`);
    await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
    await this.settle();
    const h1 = await page.locator('main h1').first().textContent({ timeout: 8000 }).catch(() => null);
    if (!h1) problem(this.ctx, `${name}: keine Überschrift (h1) gefunden`);
    const lang = await page.evaluate(() => document.documentElement.lang);
    if (lang !== 'de') problem(this.ctx, `${name}: lang="${lang}" statt "de"`);
    const errors = await page.locator('main .state--error').count();
    if (errors > 0 && !opts.expectError) {
      const text = await page.locator('main .state--error').first().innerText();
      problem(this.ctx, `${name}: Fehlerzustand sichtbar: ${text.replace(/\s+/g, ' ')}`);
    }
    if (opts.expectError && errors === 0) problem(this.ctx, `${name}: erwarteter Fehlerzustand fehlt`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 2) problem(this.ctx, `${name}: Seite läuft horizontal über (${overflow}px)`);
    if (opts.before) await opts.before(page);
    await this.checkReaderControls(name);
    await this.shot(name, opts.fullPage !== false);
    await this.flush(name);
    visited.push({ ctx: this.ctx, name, h1: (h1 || '').trim(), empty: await page.locator('main .state--empty').count() });
    return h1;
  }

  async login() {
    const page = this.page;
    const { user, pass } = ROLES[this.role];
    this.allow('GET', /\/api\/auth\/me$/, 401);
    await page.goto(BASE + '/suche?q=Verwaltung', { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Benutzername').waitFor({ timeout: 15000 });
    await this.flush('Anmeldeseite');
    if (this.viewport.width > 1000 && this.role === 'admin') {
      this.allow('POST', /\/api\/auth\/login$/, 401);
      await page.getByLabel('Benutzername').fill(user);
      await page.getByLabel('Passwort').fill('ganz-sicher-falsch');
      await page.getByRole('button', { name: 'Anmelden' }).click();
      await page.locator('.alert--crit').waitFor({ timeout: 10000 });
      await this.shot('anmeldung-fehler');
      await this.flush('Anmeldung mit falschem Passwort');
    } else {
      await this.shot('anmeldung');
    }
    await page.getByLabel('Benutzername').fill(user);
    await page.getByLabel('Passwort').fill(pass);
    await page.getByRole('button', { name: 'Anmelden' }).click();
    await page.locator('nav[aria-label="Hauptnavigation"]').waitFor({ state: 'attached', timeout: 15000 });
    await this.settle();
    // Die ursprünglich aufgerufene Adresse bleibt nach der Anmeldung erhalten (teilbare Links).
    if (!page.url().includes('/suche?q=Verwaltung')) problem(this.ctx, `Nach der Anmeldung nicht auf der aufgerufenen Seite: ${page.url()}`);
    await this.flush('Anmeldung');
  }

  async api(pathname) {
    const res = await this.context.request.get(BASE + pathname);
    if (!res.ok()) throw new Error(`${pathname} → ${res.status()}`);
    return res.json();
  }

  async logout() {
    const page = this.page;
    if (this.viewport.width <= 1100) {
      // schmale Ansicht: Abmelden steht in der Kopfzeile und bleibt erreichbar
    }
    await page.getByRole('button', { name: 'Abmelden' }).click();
    await page.getByLabel('Benutzername').waitFor({ timeout: 10000 });
    await this.flush('Abmeldung');
  }

  async close() {
    await this.context.close();
  }
}

async function walk(s) {
  const page = s.page;
  const wide = s.viewport.width >= 1280;

  // --- Daten für Detailseiten ermitteln ------------------------------------------------------------------
  const postings = await s.api('/api/postings?kind_group=all&page_size=200');
  const merged = [...postings.items].sort((a, b) => b.member_count - a.member_count)[0];
  const districts = await s.api('/api/regions?level=district');
  const states = await s.api('/api/regions?level=state');
  const sources = (await s.api('/api/sources')).sources;
  const runs = await s.api('/api/runs?limit=100');
  const metrics = await s.api('/api/map/metrics');
  const overview = await s.api('/api/stats/overview');
  const topKreis = [...metrics.regions].sort((a, b) => b.distinct - a.distinct)[0]?.key || districts[0]?.key;
  const candidate = sources.find((x) => x.adapter_available && x.config_status === 'candidate');
  const activeSource = sources.find((x) => x.config_status === 'active') || sources[0];
  const troubled = runs.find((r) => r.status === 'blocked') || runs.find((r) => r.status === 'partial') || runs[0];
  const hasData = postings.total > 0;
  notes.push(`[${s.ctx}] Datenlage: ${postings.total} Anzeigen, ${districts.length} Kreise, ${sources.length} Quellen, ${runs.length} Läufe, ${overview.indicators.length} Statistik-Kennzahlen`);

  // --- 2 Dashboard ------------------------------------------------------------------------------------
  await s.visit('dashboard', '/');

  // --- 3 Stellensuche ----------------------------------------------------------------------------------
  await s.visit('suche', '/suche');
  await s.visit('suche-gefiltert', `/suche?q=${encodeURIComponent('Sachbearbeiter ODER Pflege*')}&working_time=vollzeit&sort=title`, {
    before: async () => {
      await page.getByRole('button', { name: 'Hilfe zur Suchsyntax' }).click();
      await page.locator('.syntax-help').waitFor();
    },
    fullPage: false,
  });
  await page.keyboard.press('Escape');
  if (districts.length > 0) {
    const town = 'Nordmusterstadt';
    await s.visit('suche-umkreis', `/suche?place=${town}&radius_km=50&kind_group=all`);
  }
  s.allow('GET', /\/api\/postings\?/, 422);
  await s.visit('suche-fehler-nur-ausschluss', `/suche?q=${encodeURIComponent('-Vertrieb')}`, { expectError: true, fullPage: false });
  s.allowed.pop();
  await s.visit('suche-ausbildung', '/suche?kind_group=ausbildung');
  await s.visit('suche-keine-treffer', '/suche?q=Quantenklempnerin&fuzzy=true');
  if (!wide) {
    await page.goto(BASE + '/suche', { waitUntil: 'domcontentloaded' });
    await s.settle();
    await page.getByRole('button', { name: /^Filter/ }).click();
    await page.locator('dialog.dialog--drawer[open]').waitFor();
    await page.waitForTimeout(300);
    await s.shot('suche-filter-bedienfeld', false);
    await page.keyboard.press('Escape');
    await s.flush('Filter-Bedienfeld');
  }

  // Filter über das gemeinsame Filterfeld: Berufsvorschläge (KldB), Merkmale, Kreisvorschläge.
  if (wide) {
    await page.goto(BASE + '/suche', { waitUntil: 'domcontentloaded' });
    await s.settle();
    const kldbHits = await s.api('/api/meta/kldb?q=Pflege');
    if (kldbHits.length > 0) {
      await page.getByRole('combobox', { name: 'Beruf suchen (KldB 2010)' }).fill('Pflege');
      await page.locator('.typeahead__option').first().waitFor({ timeout: 8000 });
      await page.keyboard.press('Enter');
      await page.waitForURL(/kldb=/, { timeout: 8000 }).catch(() => problem(s.ctx, 'Berufsvorschlag setzt den KldB-Filter nicht'));
      await s.settle();
    }
    await page.locator('summary', { hasText: 'Qualifikationen und Merkmale' }).click();
    const firstFeature = page.locator('.feature-groups input[type="checkbox"]').first();
    if ((await firstFeature.count()) > 0) {
      await firstFeature.check();
      await page.waitForURL(/features=/, { timeout: 8000 }).catch(() => problem(s.ctx, 'Merkmal setzt den Filter nicht'));
      await s.settle();
      await s.shot('suche-filter-beruf-merkmal', false);
    }
    if (districts.length > 0) {
      await page.getByRole('combobox', { name: 'Kreis oder kreisfreie Stadt' }).fill(districts[0].name.slice(0, 5));
      await page.locator('.typeahead__option').first().waitFor({ timeout: 8000 });
      await page.keyboard.press('Enter');
      await page.waitForURL(/kreise=\d{5}/, { timeout: 8000 }).catch(() => problem(s.ctx, 'Kreisvorschlag setzt den Kreisfilter nicht'));
      await s.settle();
    }
    await s.flush('Filterfeld');
  }

  // Zustand in der Adresszeile: Filter setzen, zurück, vorwärts.
  await page.goto(BASE + '/suche', { waitUntil: 'domcontentloaded' });
  await s.settle();
  await page.getByRole('button', { name: 'Ausbildung & duales Studium' }).click();
  await page.waitForURL(/kind_group=ausbildung/);
  await page.goBack();
  await page.waitForURL((u) => !u.search.includes('kind_group'));
  await s.settle();
  await s.flush('Zurück-Schaltfläche');

  // Gespeicherte Suchen: speichern, auflisten, löschen (persönliche Daten – auch im Lesezugriff erlaubt).
  if (wide) {
    const name = `Prüfsuche ${s.role} ${Date.now()}`;
    await page.goto(BASE + '/suche?q=Pflege', { waitUntil: 'domcontentloaded' });
    await s.settle();
    await page.getByRole('button', { name: /Gespeicherte Suchen/ }).click();
    await page.getByRole('button', { name: 'Aktuelle Suche speichern' }).click();
    await page.getByLabel('Name der Suche').fill(name);
    await page.getByRole('button', { name: 'Speichern', exact: true }).click();
    await page.locator('.toast--good').waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: /Gespeicherte Suchen/ }).click();
    await page.getByRole('link', { name: new RegExp(name) }).waitFor({ timeout: 10000 });
    await s.shot('suche-gespeicherte-suchen', false);
    await page.getByRole('button', { name: `Gespeicherte Suche „${name}“ löschen` }).click();
    await page.getByRole('button', { name: 'Löschen', exact: true }).click();
    await page.getByRole('link', { name: new RegExp(name) }).waitFor({ state: 'detached', timeout: 10000 });
    await s.flush('Gespeicherte Suchen');
  }

  // CSV-Export: normaler Link mit denselben Parametern.
  const exportHref = await page.goto(BASE + '/suche?q=Pflegefachkraft', { waitUntil: 'domcontentloaded' }).then(async () => {
    await s.settle();
    return page.locator('a:has-text("CSV-Export")').first().getAttribute('href').catch(() => null);
  });
  if (hasData) {
    if (!exportHref || !exportHref.startsWith('/api/postings/export.csv?') || !exportHref.includes('q=Pflegefachkraft')) problem(s.ctx, `CSV-Export-Link unerwartet: ${exportHref}`);
    else {
      const csv = await s.context.request.get(BASE + exportHref);
      if (!csv.ok() || !(csv.headers()['content-type'] || '').includes('text/csv')) problem(s.ctx, `CSV-Export antwortet nicht mit CSV (${csv.status()})`);
    }
  }
  await s.flush('CSV-Export');

  // --- 4 Karte ------------------------------------------------------------------------------------------
  await s.visit('karte', '/karte');
  if (districts.length > 0) {
    await s.visit('karte-auswahl', `/karte?kreise=${topKreis}&metric=distinct`);
    await s.visit('karte-quote', '/karte?metric=rate&klassen=equal');
    await s.visit('karte-veraenderung-7', '/karte?metric=change&days=7');
    await s.visit('karte-veraenderung-90', '/karte?metric=change&days=90');
    const indicator = overview.indicators.find((i) => i.key === 'arbeitslose') || overview.indicators[0];
    if (indicator) await s.visit('karte-kontext', `/karte?metric=context&indicator=${indicator.key}`);
    // Tooltip per Maus und Auswahl per Klick
    await page.goto(BASE + '/karte', { waitUntil: 'domcontentloaded' });
    await s.settle();
    const box = await page.locator('.map-canvas').boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.45);
      await page.mouse.move(box.x + box.width * 0.5 + 4, box.y + box.height * 0.45 + 4);
      const tip = page.locator('.map-tip:visible');
      await tip.waitFor({ timeout: 5000 }).catch(() => problem(s.ctx, 'Karte: kein Tooltip beim Überfahren eines Kreises'));
      await s.shot('karte-tooltip', false);
      await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.45);
      await page.waitForURL(/kreise=\d{5}/, { timeout: 5000 }).catch(() => problem(s.ctx, 'Karte: Klick auf einen Kreis setzt den Kreisfilter nicht'));
      await s.settle();
      const link = await page.getByRole('link', { name: 'Zur Regionsdetailseite' }).count();
      if (link === 0) problem(s.ctx, 'Karte: Verweis zur Regionsdetailseite fehlt nach der Auswahl');
    }
    await s.flush('Karte Interaktion');
  }

  // --- 5 Regionen ---------------------------------------------------------------------------------------
  await s.visit('regionen', '/regionen');
  if (districts.length > 0) {
    await s.visit('region-kreis', `/regionen/${topKreis}`);
    const noPop = districts.find((d) => d.key === '98005') || districts[districts.length - 1];
    await s.visit('region-kreis-ohne-nenner', `/regionen/${noPop.key}?kind_group=all`);
  }
  if (states.length > 0) await s.visit('region-land', `/regionen/${states[0].key}`);
  s.allow('GET', /\/api\/regions\/00000/, 404);
  await s.visit('region-nicht-gefunden', '/regionen/00000', { expectError: true, fullPage: false });
  s.allowed.pop();

  // --- 6 Anzeigen ---------------------------------------------------------------------------------------
  await s.visit('anzeigen', '/anzeigen');
  if (merged) {
    await s.visit('anzeige-detail', `/anzeigen/${merged.id}`);
    const links = await page.locator('main a[target="_blank"]').evaluateAll((els) => els.map((a) => ({ href: a.getAttribute('href'), rel: a.getAttribute('rel') })));
    for (const l of links) {
      if (!/^https?:\/\//.test(l.href || '')) problem(s.ctx, `Externer Verweis ohne http(s): ${l.href}`);
      if (!/noopener/.test(l.rel || '') || !/noreferrer/.test(l.rel || '')) problem(s.ctx, `Externer Verweis ohne rel="noopener noreferrer": ${l.href}`);
    }
    if (s.role === 'admin' && merged.member_count > 1 && wide) {
      await page.getByRole('button', { name: 'Zusammenführung lösen' }).first().click();
      await page.locator('dialog[open]').waitFor();
      await s.shot('anzeige-zusammenfuehrung-loesen', false);
      await page.getByRole('button', { name: 'Abbrechen' }).click();
    }
  }
  s.allow('GET', /\/api\/postings\/999999999$/, 404);
  await s.visit('anzeige-nicht-gefunden', '/anzeigen/999999999', { expectError: true, fullPage: false });
  s.allowed.pop();

  // --- 7 Quellenverwaltung ------------------------------------------------------------------------------
  await s.visit('quellen', '/quellen');
  if (activeSource) await s.visit('quelle-detail', `/quellen/${activeSource.id}`);
  if (candidate) {
    await s.visit('quelle-vorgemerkt', `/quellen/${candidate.id}`);
    if (s.role === 'admin' && wide) {
      const marked = await page.locator('[data-admin-action]').count();
      if (marked === 0) problem(s.ctx, 'Quellendetail: als Administrator fehlen die Aktionen');
      // Prüfmeldung der API im Freigabedialog (zu kurzer Vermerk) – es wird nichts freigegeben.
      s.allow('POST', /\/api\/sources\/\d+\/activate$/, 422);
      await page.getByRole('button', { name: 'Freigeben …' }).click();
      await page.getByLabel('Freigabevermerk').fill('zu kurz');
      await page.getByRole('button', { name: 'Freigabe dokumentieren und aktivieren' }).click();
      await page.locator('dialog[open] .form-error').waitFor({ timeout: 10000 });
      const msg = await page.locator('dialog[open] .form-error').innerText();
      if (!/Freigabevermerk/.test(msg)) problem(s.ctx, `Freigabedialog zeigt nicht die Meldung der API: ${msg}`);
      await s.shot('quelle-freigabe-pruefmeldung', false);
      await page.getByRole('button', { name: 'Abbrechen' }).click();
      await s.flush('Freigabedialog');
      s.allowed.pop();
    }
  }
  await s.visit('laeufe', '/quellen/laeufe');
  if (troubled) await s.visit('lauf-detail', `/quellen/laeufe/${troubled.id}`);
  await s.visit('system', '/quellen/system');
  if (s.role === 'admin') {
    const marked = await page.locator('[data-admin-action]').count();
    if (marked === 0) problem(s.ctx, 'System: als Administrator fehlen die schreibenden Bedienelemente (Prüfung wäre sonst wirkungslos)');
    if (WITH_MUTATIONS && wide) {
      const username = `pruefkonto_${Date.now()}`;
      await page.getByRole('button', { name: 'Benutzer anlegen' }).click();
      await page.getByLabel('Benutzername').fill(username);
      await page.getByRole('button', { name: 'Anlegen und Passwort erzeugen' }).click();
      await page.locator('.secret code').waitFor({ timeout: 10000 });
      const pw = await page.locator('.secret code').innerText();
      if (pw.length < 12) problem(s.ctx, 'Benutzer anlegen: generiertes Passwort wird nicht angezeigt');
      await page.locator('.secret code').evaluate((el) => (el.textContent = '••••••••••••••••')); // nicht ins Bildschirmfoto
      await s.shot('system-passwort-einmalig', false);
      await page.getByRole('button', { name: 'Passwort notiert – schließen' }).click();
      const row = page.locator('tr', { hasText: username });
      await row.getByRole('button', { name: 'Deaktivieren' }).click();
      await page.locator('dialog[open]').getByRole('button', { name: 'Deaktivieren' }).click();
      await row.getByText('deaktiviert').waitFor({ timeout: 10000 });
      await s.flush('Benutzer anlegen und deaktivieren');
      notes.push(`[${s.ctx}] Benutzer ${username} angelegt (Passwort einmalig angezeigt) und wieder deaktiviert`);
    }
  }

  // --- 8 Methodik ---------------------------------------------------------------------------------------
  await s.visit('methodik', '/methodik');

  // Navigation im Browser (ohne Neuladen) über die linke Navigation
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await s.settle();
  for (const label of ['Stellensuche', 'Karte', 'Regionen', 'Anzeigen', 'Quellenverwaltung', 'Methodik und Quellen', 'Dashboard']) {
    if (s.viewport.width <= 1100) {
      await page.getByRole('button', { name: 'Navigation öffnen' }).click();
      if (label === 'Stellensuche') {
        await page.waitForTimeout(250);
        await s.shot('navigation-geoeffnet', false);
      }
    }
    await page.locator('nav[aria-label="Hauptnavigation"]').getByRole('link', { name: label, exact: true }).click();
    await s.settle();
    const h1 = (await page.locator('main h1').first().textContent()) || '';
    if (!h1.trim()) problem(s.ctx, `Navigation „${label}“: keine Überschrift`);
  }
  await s.flush('Navigation');

  // Tastaturbedienung: Sprunglink und sichtbarer Fokus
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await s.settle();
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => {
    const el = document.activeElement;
    const st = el ? getComputedStyle(el) : null;
    return { text: el?.textContent?.trim(), outline: st ? `${st.outlineStyle} ${st.outlineWidth}` : '' };
  });
  if (focused.text !== 'Zum Inhalt springen') problem(s.ctx, `Erster Tabstopp ist nicht der Sprunglink, sondern „${focused.text}“`);
  await s.flush('Tastatur');
}

(async () => {
  for (const [role, cred] of Object.entries(ROLES)) {
    if (!cred.user || !cred.pass) {
      console.error(`Zugangsdaten fehlen: WF_${role.toUpperCase()}_USER / WF_${role.toUpperCase()}_PASS`);
      process.exit(2);
    }
  }
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  try {
    for (const viewport of VIEWPORTS) {
      for (const role of Object.keys(ROLES)) {
        const s = new Session(browser, role, viewport);
        await s.open();
        try {
          await s.login();
          await walk(s);
          await s.logout();
        } catch (err) {
          problem(s.ctx, `Abbruch des Durchlaufs: ${err.message.split('\n')[0]}`);
          await s.shot('abbruch', false).catch(() => {});
        } finally {
          await s.close();
        }
      }
    }
  } finally {
    await browser.close();
  }

  console.log('\nHinweise:');
  for (const n of [...new Set(notes)]) console.log(`  · ${n}`);
  const emptyOnly = visited.filter((v) => v.empty > 0).map((v) => `${v.ctx}: ${v.name}`);
  console.log(`\nBesuchte Ansichten: ${visited.length} · Bildschirmfotos unter ${path.relative(process.cwd(), OUT)}/`);
  if (emptyOnly.length) console.log(`Ansichten mit sichtbarem Leerzustand (${emptyOnly.length}):\n  ${emptyOnly.join('\n  ')}`);
  if (problems.length) {
    console.log(`\n${problems.length} Problem(e):`);
    for (const p of problems) console.log(`  ✗ ${p}`);
    process.exit(1);
  }
  console.log('\nKeine Probleme: keine Konsolenfehler, keine CSP-Verstöße, keine fehlgeschlagenen Anfragen, keine schreibenden Bedienelemente im Lesezugriff.');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
