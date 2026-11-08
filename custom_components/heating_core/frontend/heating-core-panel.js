// Heating Core – eigene Seite „Heizung“ (HEATING-9) mit animiertem Anlagenschema (HEATING-10).
// Liest nur Entitäten der Integration heating_core; schaltet über normale HA-Dienste.

const MODES = {
  eco: "Eco", presence: "Präsenz", schedule: "Zeitplan", pre_heat: "Vorheizen",
  manual: "Komfort (immer)", boost: "Boost", away: "Abwesend", window: "Fenster offen",
  temperature_drop: "Temperatursturz", summer: "Sommer – Heizung aus", follower: "Folgt dem Kreis",
  unavailable: "Nicht erreichbar", floor_heating: "Fußboden heizt", floor_idle: "Fußboden in Ruhe",
  source_cold: "Kessel zu kalt", sensor_missing: "Sensor fehlt", circuit_off: "Von der Anlage abgeschaltet",
};
const DECISIONS = {
  startup: "Startschutz nach Neustart", no_setpoint: "Anlage meldet keinen Sollwert",
  pending_confirmation: "Warte auf Bestätigung der Anlage", no_delta: "Passt – nichts zu tun",
  within_hysteresis: "Abweichung zu klein", budget: "Schreib-Budget erschöpft",
  hold_drop: "Sperrzeit nach Erhöhen", hold_raise: "Sperrzeit nach Absenken",
  raise: "Würde erhöhen", drop: "Würde absenken", significant_drop: "Würde deutlich absenken",
  forced_min: "Sicherheit: Minimum", renew: "Würde erneuern", circuit_off: "Kreis aus – nicht übersteuert",
};
const PROBLEMS = {
  sensor_missing: "Sensor fehlt", temperature_unknown: "Ist-Temperatur unbekannt",
  master_unavailable: "Thermostat/Heizkreis nicht erreichbar", room_unavailable: "Thermostat nicht erreichbar",
  source_temperature_unknown: "Kesseltemperatur unbekannt",
};
const HEATING = new Set(["presence", "schedule", "pre_heat", "manual", "boost", "floor_heating"]);

const fmt = (v, d = 1) => (v === null || v === undefined || v === "" || isNaN(Number(v)) ? "–" : Number(v).toFixed(d));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

class HeatingCorePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dragging = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._dragging || this._queued) return;
    this._queued = true;
    requestAnimationFrame(() => { this._queued = false; this._render(); });
  }

  set narrow(v) { this._narrow = v; }
  set panel(v) { this._panel = v; }

  // ---- Daten -------------------------------------------------------------

  _model() {
    const h = this._hass;
    const byDevice = {};
    for (const e of Object.values(h.entities || {})) {
      if (e.platform !== "heating_core" || !h.states[e.entity_id]) continue;
      const dev = (byDevice[e.device_id] ||= { id: e.device_id, name: h.devices?.[e.device_id]?.name || "", ent: {} });
      dev.ent[e.translation_key || e.entity_id] = e.entity_id;
    }
    const devices = Object.values(byDevice);
    const systems = devices.filter((d) => d.ent.write_enabled).map((d) => ({ ...d, circuits: [] }));
    const circuits = devices.filter((d) => d.ent.target && h.states[d.ent.target].attributes.anlage !== undefined);
    const rooms = devices.filter((d) => d.ent.target && h.states[d.ent.target].attributes.heizkreis !== undefined);
    for (const c of circuits) {
      const sys = systems.find((s) => s.name === h.states[c.ent.target].attributes.anlage) || systems[0];
      c.rooms = rooms.filter((r) => h.states[r.ent.target].attributes.heizkreis === c.name);
      sys?.circuits.push(c);
    }
    return systems;
  }

  _st(id) { return id ? this._hass.states[id] : undefined; }
  _a(id) { return this._st(id)?.attributes || {}; }
  _on(id) { return this._st(id)?.state === "on"; }

  // ---- Aktionen ----------------------------------------------------------

  _toggle(id) {
    this._hass.callService("switch", this._on(id) ? "turn_off" : "turn_on", { entity_id: id });
  }

  _setNumber(id, value) {
    this._hass.callService("number", "set_value", { entity_id: id, value: Number(value) });
  }

  // ---- Darstellung -------------------------------------------------------

  _slider(id, label) {
    const st = this._st(id);
    if (!st) return "";
    const a = st.attributes;
    return `<label class="slider"><span>${esc(label)}</span>
      <input type="range" data-number="${id}" min="${a.min}" max="${a.max}" step="${a.step}" value="${st.state}">
      <b data-out="${id}">${fmt(st.state)} °C</b></label>`;
  }

  _chip(id, label, onClass = "on") {
    if (!id) return "";
    return `<button class="chip ${this._on(id) ? onClass : ""}" data-toggle="${id}">${esc(label)}</button>`;
  }

  _room(r) {
    const t = this._a(r.ent.target);
    const mode = this._st(r.ent.mode)?.state;
    const valves = t.ventile_offen === undefined || t.ventile_offen === null ? "" :
      `<span class="tag ${t.ventile_offen ? "hot" : ""}">Ventile ${t.ventile_offen ? "offen" : "zu"}</span>`;
    return `<div class="room">
      <div class="row"><b>${esc(r.name)}</b><span class="mode ${HEATING.has(mode) ? "hot" : ""}">${esc(MODES[mode] || mode || "–")}</span></div>
      <div class="row small">Ist <b>${fmt(t.ist_temperatur)} °C</b> · Soll <b>${fmt(this._st(r.ent.target)?.state)} °C</b>
        ${this._on(r.ent.presence) ? '<span class="tag">Präsenz</span>' : ""} ${valves}
        ${t.problem ? `<span class="tag warn">${esc(PROBLEMS[t.problem] || t.problem)}</span>` : ""}</div>
      ${this._slider(r.ent.comfort, "Komfort")}
      ${r.ent.pre_heat ? `<div class="row">${this._chip(r.ent.pre_heat, "Vorheizen")}</div>` : ""}
    </div>`;
  }

  _circuit(c) {
    const st = this._st(c.ent.target);
    const t = st.attributes;
    const mode = this._st(c.ent.mode)?.state;
    const floor = t.kessel_temperatur !== undefined && t.kessel_temperatur !== null;
    const would = (t.wuerde_schalten || []).length ? `<ul class="would">${t.wuerde_schalten.map((w) => `<li>${esc(w.replace("switch.", ""))}</li>`).join("")}</ul>` : "";
    const details = floor
      ? `<div class="row small">Kessel <b>${fmt(t.kessel_temperatur)} °C</b> · Freigabe <b>${t.kessel_freigabe ? "ja" : "nein"}</b> ·
           Pumpe <b>${t.pumpe_ist ? "läuft" : "aus"}</b>${t.pumpe_soll !== t.pumpe_ist ? ` → soll ${t.pumpe_soll ? "laufen" : "aus"}` : ""}</div>
         ${would ? `<div class="small">Würde schalten:</div>${would}` : '<div class="small muted">Würde nichts schalten.</div>'}`
      : `<div class="big"><span>${fmt(t.ist_temperatur)} °C</span><small>Ist</small><span>→</span><span>${fmt(st.state)} °C</span><small>Soll</small></div>
         <div class="row small">Anlage meldet <b>${fmt(t.anlage_sollwert)} °C</b> · ${esc(DECISIONS[t.entscheidung] || t.entscheidung || "")}
         ${t.schreib_budget_rest !== undefined && t.schreib_budget_rest !== null ? ` · Budget ${t.schreib_budget_rest}` : ""}</div>`;
    return `<section class="card">
      <div class="row"><h2>${esc(c.name)}</h2><span class="mode ${HEATING.has(mode) ? "hot" : ""}">${esc(MODES[mode] || mode || "–")}</span></div>
      ${t.problem ? `<div class="warnbox">${esc(PROBLEMS[t.problem] || t.problem)}</div>` : ""}
      ${details}
      ${this._slider(c.ent.comfort, "Komfort")}
      ${c.ent.pre_heat ? `<div class="row">${this._chip(c.ent.pre_heat, "Vorheizen")}</div>` : ""}
      ${c.rooms.length ? `<div class="rooms">${c.rooms.map((r) => this._room(r)).join("")}</div>` : ""}
    </section>`;
  }

  _schema(sys) {
    // HEATING-10: Wärmeerzeuger → Kreise → Zonen; Leitung läuft (animiert), wenn Wärme fließt.
    const rows = [];
    for (const c of sys.circuits) {
      const t = this._a(c.ent.target);
      const mode = this._st(c.ent.mode)?.state;
      const floor = t.kessel_temperatur !== undefined && t.kessel_temperatur !== null;
      const flow = floor ? !!t.pumpe_ist : mode !== "circuit_off" && mode !== "summer" && Number(t.ist_temperatur) < Number(this._st(c.ent.target)?.state);
      rows.push({ c, t, floor, flow, zones: c.rooms });
    }
    const kessel = rows.find((r) => r.floor)?.t.kessel_temperatur;
    const rowH = 70;
    const H = Math.max(140, rows.reduce((n, r) => n + Math.max(1, r.zones.length) * rowH, 0) + 20);
    let y = 20;
    let svg = "";
    const boilerY = H / 2;
    for (const r of rows) {
      const n = Math.max(1, r.zones.length);
      const cy = y + (n * rowH) / 2 - rowH / 2 + 25;
      const cls = r.flow ? "pipe flow" : "pipe";
      svg += `<path class="${cls}" d="M150 ${boilerY} C 200 ${boilerY}, 200 ${cy}, 260 ${cy}"/>`;
      svg += `<rect class="box ${r.flow ? "hotbox" : ""}" x="260" y="${cy - 22}" width="190" height="44" rx="10"/>
        <text x="355" y="${cy - 3}" class="t">${esc(r.c.name)}</text>
        <text x="355" y="${cy + 14}" class="s">${r.floor ? (r.t.pumpe_ist ? "Pumpe läuft" : "Pumpe aus") : `${fmt(r.t.ist_temperatur)} → ${fmt(this._st(r.c.ent.target)?.state)} °C`}</text>`;
      r.zones.forEach((z, i) => {
        const zt = this._a(z.ent.target);
        const zy = y + i * rowH + 25;
        const zflow = r.floor ? r.t.pumpe_ist && zt.ventile_offen : r.flow;
        svg += `<path class="${zflow ? "pipe flow" : "pipe"}" d="M450 ${cy} C 500 ${cy}, 500 ${zy}, 550 ${zy}"/>
          <rect class="box ${zflow ? "hotbox" : ""}" x="550" y="${zy - 22}" width="230" height="44" rx="10"/>
          <text x="665" y="${zy - 3}" class="t">${esc(z.name)}</text>
          <text x="665" y="${zy + 14}" class="s">${fmt(zt.ist_temperatur)} → ${fmt(this._st(z.ent.target)?.state)} °C${zt.ventile_offen === undefined || zt.ventile_offen === null ? "" : zt.ventile_offen ? " · offen" : " · zu"}</text>`;
      });
      y += n * rowH;
    }
    svg = `<rect class="box boiler" x="20" y="${boilerY - 40}" width="130" height="80" rx="14"/>
      <text x="85" y="${boilerY - 8}" class="t">Wärmeerzeuger</text>
      <text x="85" y="${boilerY + 14}" class="s">${kessel !== undefined ? `${fmt(kessel)} °C` : ""}</text>` + svg;
    return `<svg class="schema" viewBox="0 0 800 ${H}" preserveAspectRatio="xMinYMin meet">${svg}</svg>`;
  }

  _system(sys) {
    const s = sys.ent;
    const problems = this._a(s.problem).probleme || [];
    const writing = this._on(s.write_enabled);
    return `<div class="system">
      <div class="head">
        <h1>${esc(sys.name)}</h1>
        <button class="chip ${writing ? "on" : "shadow"}" data-toggle="${s.write_enabled}">${writing ? "Steuert aktiv" : "Schattenbetrieb – schaltet nichts"}</button>
        ${this._chip(s.away, "Abwesend")} ${this._chip(s.guest, "Gast")}
      </div>
      ${problems.length ? `<div class="warnbox">${problems.map((p) => esc(p.replace(/: (\w+)$/, (m, k) => ": " + (PROBLEMS[k] || k)))).join("<br>")}</div>` : ""}
      <div class="globals">${this._slider(s.eco, "Eco")}${this._slider(s.away_temp, "Abwesend")}</div>
      <section class="card schemawrap">${this._schema(sys)}</section>
      <div class="grid">${sys.circuits.map((c) => this._circuit(c)).join("")}</div>
    </div>`;
  }

  _render() {
    if (!this._hass) return;
    const systems = this._model();
    this.shadowRoot.innerHTML = `<style>${CSS}</style>
      <div class="page">
        <div class="top">${this._narrow ? '<ha-menu-button></ha-menu-button>' : ""}<span>Heizung</span></div>
        ${systems.length ? systems.map((s) => this._system(s)).join("") : '<p class="muted">Noch keine Anlage eingerichtet.</p>'}
      </div>`;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) { menu.hass = this._hass; menu.narrow = this._narrow; }
    this.shadowRoot.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => this._toggle(b.dataset.toggle)));
    this.shadowRoot.querySelectorAll("[data-number]").forEach((inp) => {
      const out = this.shadowRoot.querySelector(`[data-out="${inp.dataset.number}"]`);
      inp.addEventListener("pointerdown", () => { this._dragging = true; });
      inp.addEventListener("input", () => { out.textContent = `${fmt(inp.value)} °C`; });
      inp.addEventListener("change", () => { this._dragging = false; this._setNumber(inp.dataset.number, inp.value); });
    });
  }
}

const CSS = `
  :host { display:block; background: var(--primary-background-color); color: var(--primary-text-color); min-height:100vh; }
  .page { max-width: 1200px; margin: 0 auto; padding: 0 16px 32px; font-family: var(--paper-font-body1_-_font-family, system-ui); }
  .top { display:flex; align-items:center; gap:8px; height:56px; font-size:20px; }
  h1 { font-size: 22px; margin: 0; } h2 { font-size: 17px; margin: 0; }
  .system { margin-bottom: 32px; }
  .head { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin: 8px 0 12px; }
  .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
  .card { background: var(--card-background-color); border-radius: 14px; padding: 14px; box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); margin-bottom: 12px; }
  .grid .card { margin: 0; }
  .row { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; margin: 4px 0; }
  .small { font-size: 13px; color: var(--secondary-text-color); } .muted { color: var(--secondary-text-color); }
  .row.small { justify-content: flex-start; gap: 4px 6px; }
  .big { display:grid; grid-template-columns: auto auto auto auto auto; align-items:baseline; gap: 4px 8px; margin: 8px 0; font-size: 26px; }
  .big small { font-size: 12px; color: var(--secondary-text-color); }
  .mode { font-size: 13px; padding: 2px 10px; border-radius: 999px; background: var(--secondary-background-color); }
  .mode.hot, .tag.hot { background: #ff7043; color: #fff; }
  .tag { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--secondary-background-color); margin-left: 4px; }
  .tag.warn, .warnbox { background: #ffb74d33; color: var(--primary-text-color); }
  .warnbox { border-radius: 10px; padding: 8px 12px; margin: 8px 0; font-size: 14px; border: 1px solid #ffb74d; }
  .chip { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); border-radius: 999px; padding: 6px 14px; font-size: 14px; cursor: pointer; }
  .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .chip.shadow { background: #90a4ae33; }
  .slider { display:grid; grid-template-columns: 90px 1fr 70px; align-items:center; gap:8px; font-size: 14px; margin: 6px 0; }
  .slider input { width: 100%; accent-color: var(--primary-color); cursor: pointer; }
  .slider b { text-align: right; }
  .globals { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0 16px; }
  .rooms { margin-top: 10px; display:grid; gap: 8px; }
  .room { border-top: 1px solid var(--divider-color); padding-top: 8px; }
  .would { margin: 4px 0 8px; padding-left: 18px; font-size: 13px; }
  .schemawrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .schema { width: 100%; min-width: 620px; height: auto; display: block; }
  .schema .box { fill: var(--secondary-background-color); stroke: var(--divider-color); }
  .schema .hotbox { stroke: #ff7043; stroke-width: 2; }
  .schema .boiler { fill: #ff704322; stroke: #ff7043; }
  .schema .t { font-size: 14px; font-weight: 600; text-anchor: middle; fill: var(--primary-text-color); }
  .schema .s { font-size: 12px; text-anchor: middle; fill: var(--secondary-text-color); }
  .schema .pipe { fill: none; stroke: #90a4ae; stroke-width: 6; stroke-linecap: round; opacity: .5; }
  .schema .pipe.flow { stroke: #ff7043; opacity: 1; stroke-dasharray: 14 10; animation: flow 1s linear infinite; }
  @keyframes flow { to { stroke-dashoffset: -24; } }
  @media (prefers-reduced-motion: reduce) { .schema .pipe.flow { animation: none; } }
  button:not(:disabled) { cursor: pointer; }
`;

customElements.define("heating-core-panel", HeatingCorePanel);
