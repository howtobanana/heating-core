// Heating Core – eigene Seite „Heizung“ (HEATING-9) mit animiertem Anlagenschema (HEATING-10).
// Liest nur Entitäten der Integration heating_core; schaltet über normale HA-Dienste.
// Aufbau (Entwurf „A mit Kacheln aus B“, Fabian 08.11.2026): Status, Schema mit Legende, je Heizkreis Kacheln.

const MODES = {
  eco: "Eco", presence: "Präsenz", schedule: "Zeitplan", pre_heat: "Vorheizen",
  manual: "Komfort (immer)", boost: "Boost", away: "Abwesend", window: "Fenster offen",
  temperature_drop: "Temperatursturz", summer: "Sommer – Heizung aus", follower: "Folgt dem Kreis",
  unavailable: "Nicht erreichbar", floor_heating: "Fußboden heizt", floor_idle: "Fußboden in Ruhe",
  source_cold: "Kessel zu kalt", sensor_missing: "Sensor fehlt", circuit_off: "Von der Anlage abgeschaltet",
  disabled: "Ausgeschaltet",
};
const DECISIONS = {
  startup: "Wartet kurz nach dem Neustart", no_setpoint: "Anlage meldet keinen Sollwert",
  pending_confirmation: "Warte auf Bestätigung der Anlage", no_delta: "Passt – nichts zu tun",
  within_hysteresis: "Passt – Abweichung zu klein", budget: "Schreib-Budget erschöpft",
  hold_drop: "Sperrzeit nach Erhöhen", hold_raise: "Sperrzeit nach Absenken", hold_min: "Kessel schonen: Haltezeit 2 h",
  raise: "Würde erhöhen", drop: "Würde absenken", significant_drop: "Würde deutlich absenken",
  forced_min: "Sicherheit: Minimum", renew: "Würde erneuern", circuit_off: "Kreis aus – nicht übersteuert", disabled: "Kreis ausgeschaltet – nur Frostschutz",
};
const PROBLEMS = {
  sensor_missing: "Sensor fehlt", temperature_unknown: "Ist-Temperatur unbekannt",
  master_unavailable: "Thermostat/Heizkreis nicht erreichbar", room_unavailable: "Thermostat nicht erreichbar",
  source_temperature_unknown: "Kesseltemperatur unbekannt",
  room_write_failed: "Thermostat hat den Sollwert nicht angenommen",
  room_sensor_blocks: "Raumfühler der Pellematic schaltet den Kreis ab, obwohl Räume Wärme brauchen. Am Display der Pellematic (oder Ökofen-App) beim Heizkreis: Raumfühler aus bzw. Raumeinfluss 0, Ökomodus aus. Anleitung: Einstellungen → Reparaturen",
};
const HEATING = new Set(["presence", "schedule", "pre_heat", "manual", "boost", "floor_heating"]);
const OFF_MODES = new Set(["circuit_off", "summer", "away", "window", "unavailable", "disabled"]);
const HOT = "#f4511e", COLD = "#1e88e5", IDLE = "#9aa5b1", WARN = "#f5a623";

const val = (v, unit) => { // Anzeige der Grundwerte
  const n = Number(v);
  if (unit === "s") return n >= 60 && n % 60 === 0 ? `${n / 60} min` : `${Math.round(n)} s`;
  if (unit === "min") return n >= 120 && n % 60 === 0 ? `${n / 60} h` : `${Math.round(n)} min`;
  return `${fmt(v)} °C`;
};
const has = (v) => v !== null && v !== undefined && v !== "" && !isNaN(Number(v));
const fmt = (v, d = 1) => (has(v) ? Number(v).toLocaleString("de-AT", { minimumFractionDigits: d, maximumFractionDigits: d }) : "–");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---- Symbole fürs Schema (DIN-ähnlich) --------------------------------------
const I = {
  pump: (x, y, on) => `<g class="pump ${on ? "on" : ""}" transform="translate(${x} ${y})"><circle r="9"/><path d="M-3.5-4.5 5.5 0-3.5 4.5Z"/></g>`,
  valve: (x, y, open) => `<g class="valve ${open ? "open" : ""}" transform="translate(${x} ${y})"><path d="M-7-6 7 6V-6L-7 6Z"/></g>`,
  trv: (x, y, open) => `<g class="valve ${open ? "open" : ""}" transform="translate(${x} ${y})"><path d="M0 0V-9"/><rect x="-5" y="-15" width="10" height="6" rx="2"/><path d="M-7-6 7 6V-6L-7 6Z"/></g>`,
  radiator: (x, y, on) => `<g class="rad ${on ? "on" : ""}" transform="translate(${x} ${y})"><rect x="-10" y="-8" width="20" height="16" rx="2"/><path d="M-5-8v16M0-8v16M5-8v16"/></g>`,
  floor: (x, y, on) => `<g class="rad ${on ? "on" : ""}" transform="translate(${x} ${y})"><path d="M-10-7H7a2.5 2.5 0 0 1 0 5H-7a2.5 2.5 0 0 0 0 5H7a2.5 2.5 0 0 1 0 5H-10"/></g>`,
  warn: (x, y) => `<g transform="translate(${x} ${y})"><path fill="${WARN}" d="M0-8 8 7H-8Z"/><path stroke="#000" stroke-width="1.6" d="M0-3v5M0 4.5v.5"/></g>`,
};
// schlichter Stift (Strich wie die übrigen Symbole) statt des Emoji ✎ (Fabian 11.11.2026)
const EDIT = `<svg class="edit" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>`;
const icon = (fn, on, w = 26, h = 22) => `<svg width="${w}" height="${h}" viewBox="${-w / 2} ${-h / 2} ${w} ${h}">${fn(0, 0, on)}</svg>`;
const elbow = (x1, y1, xm, x2, y2) => {
  if (Math.abs(y2 - y1) < 1) return `M${x1} ${y1}H${x2}`;
  const r = Math.min(8, Math.abs(y2 - y1) / 2), s = y2 > y1 ? 1 : -1;
  return `M${x1} ${y1}H${xm - r}Q${xm} ${y1} ${xm} ${y1 + s * r}V${y2 - s * r}Q${xm} ${y2} ${xm + r} ${y2}H${x2}`;
};

class HeatingCorePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dragging = false;
  }

  set hass(hass) {
    this._hass = hass;
    // HA reicht hass bei jeder Änderung irgendwo im Haus weiter; neu zeichnen nur, wenn sich bei
    // Heating Core etwas ändert – sonst startet die Animation ständig neu und ruckelt.
    if (hass.entities !== this._entObj) {
      this._entObj = hass.entities;
      this._ids = Object.values(hass.entities || {}).filter((e) => e.platform === "heating_core").map((e) => e.entity_id);
    }
    const sig = this._ids.map((id) => hass.states[id]?.last_updated).join("|") + this._narrow;
    if (sig === this._sig) return;
    if (this._dragging || this._queued || this._editing) return;
    this._sig = sig;
    this._queued = true;
    requestAnimationFrame(() => { this._queued = false; this._render(); });
  }

  set narrow(v) { this._narrow = v; if (this._hass) this.hass = this._hass; }
  set panel(v) { this._panel = v; }

  // ---- Daten -------------------------------------------------------------

  _model() {
    const h = this._hass;
    const byDevice = {};
    for (const e of Object.values(h.entities || {})) {
      if (e.platform !== "heating_core" || !h.states[e.entity_id]) continue;
      const dev = (byDevice[e.device_id] ||= { id: e.device_id, name: h.devices?.[e.device_id]?.name || "", model: h.devices?.[e.device_id]?.model || "", ent: {} });
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

  // Was die Anlage meldet, aufbereitet für Schema und Kacheln. Wärme „fließt“ nur, wenn Pumpe/Ventil es melden
  // bzw. ein Heizkreis an ist und Ist < Soll – einen echten Durchfluss misst keine Anlage.
  _info(sys) {
    return sys.circuits.map((c) => {
      const t = this._a(c.ent.target);
      const mode = this._st(c.ent.mode)?.state;
      const soll = this._st(c.ent.target)?.state;
      const floor = has(t.kessel_temperatur);
      // Meldet die Anlage ihre Kreispumpe (Ökofen), zählt nur die: sonst sähe es nach Heizen aus, obwohl nichts fließt (HEATING-24)
      const flow = floor || typeof t.pumpe_ist === "boolean" ? !!t.pumpe_ist : !OFF_MODES.has(mode) && Number(t.ist_temperatur) < Number(soll);
      const rooms = c.rooms.map((r) => {
        const rt = this._a(r.ent.target);
        const zone = rt.ventile_offen !== undefined && rt.ventile_offen !== null;
        const rmode = this._st(r.ent.mode)?.state, passive = rmode === "passive"; // Heizkörper ohne TRV: warm, wenn der Kreis fließt (HEATING-38)
        return { ent: r.ent, name: r.name, t: rt, zone, passive, mode: rmode, soll: this._st(r.ent.target)?.state,
          ist: rt.ist_temperatur, problem: rt.problem, flow: passive ? flow : zone ? !!t.pumpe_ist && rt.ventile_offen : flow && rt.waermebedarf !== false };
      });
      return { ent: c.ent, name: c.name, t, mode, soll, ist: t.ist_temperatur, floor, flow, rooms, problem: t.problem };
    });
  }

  // ---- Aktionen ----------------------------------------------------------

  _toggle(id) {
    this._hass.callService("switch", this._on(id) ? "turn_off" : "turn_on", { entity_id: id });
  }

  _setNumber(id, value) {
    this._hass.callService("number", "set_value", { entity_id: id, value: Number(value) });
  }

  _step(id, dir, by) {
    const st = this._st(id);
    if (!st) return;
    const a = st.attributes, step = Number(by) || Number(a.step) || 0.5;
    const v = Math.min(Number(a.max), Math.max(Number(a.min), Math.round((Number(st.state) + dir * step) / step) * step));
    if (v !== Number(st.state)) this._setNumber(id, v);
  }

  // ---- Bausteine ---------------------------------------------------------

  _tone(mode, problem) {
    if (problem) return "warn";
    if (HEATING.has(mode)) return "hot";
    if (mode === "eco" || mode === "floor_idle") return "eco";
    return "off";
  }

  _badge(mode, problem) {
    return `<span class="badge ${this._tone(mode, problem)}">${esc(problem ? PROBLEMS[problem] || problem : MODES[mode] || mode || "–")}</span>`;
  }

  // Grundwert: Name + Erklärung links, −/Wert/+ rechts; by = Schrittweite, wenn die des Reglers zu fein ist
  _setting(id, label, hint, by) {
    const st = this._st(id);
    if (!st) return "";
    const u = st.attributes.unit_of_measurement;
    return `<div class="set"><div><span>${esc(label)}</span><small>${esc(hint)}</small></div>
      <div class="mini"><button data-step="${id}" data-d="-1" ${by ? `data-by="${by}"` : ""} aria-label="${esc(label)} weniger">−</button>
      <b>${val(st.state, u)}</b><button data-step="${id}" data-d="1" ${by ? `data-by="${by}"` : ""} aria-label="${esc(label)} mehr">+</button></div></div>`;
  }

  // Drehregler wie die HA-Thermostat-Karte: Bogen = Ist, Knopf = Komfort (ziehbar), Mitte = Komfort groß.
  // Drehregler: Mitte = was gerade gilt (Soll jetzt), darunter Ist; Knopf = Komfort (ziehbar, zeigt beim Ziehen den Komfort)
  _dial(ist, comfortId, tone, soll) {
    const st = this._st(comfortId);
    const a = st?.attributes || {}, lo = Number(a.min ?? 16), hi = Number(a.max ?? 26);
    const f = (v) => Math.max(0, Math.min(1, (Number(v) - lo) / (hi - lo)));
    const C = 2 * Math.PI * 40, arc = C * 0.75;
    const knob = (v) => { const r = (135 + 270 * f(v)) * (Math.PI / 180); return [50 + 40 * Math.cos(r), 50 + 40 * Math.sin(r)]; };
    const [kx, ky] = st ? knob(st.state) : [0, 0];
    const center = has(soll) ? soll : st?.state;
    return `<svg class="ring ${tone} ${st ? "dial" : ""}" viewBox="0 0 100 100" ${st ? `data-dial="${comfortId}" data-lo="${lo}" data-hi="${hi}" data-step="${a.step || 0.5}"` : ""}
        role="${st ? "slider" : "img"}" ${st ? `tabindex="0"` : ""} aria-label="Komfort" aria-valuemin="${lo}" aria-valuemax="${hi}" aria-valuenow="${st?.state ?? ""}">
      <circle class="track" cx="50" cy="50" r="40" stroke-dasharray="${arc} ${C}" transform="rotate(135 50 50)"/>
      <circle class="val" cx="50" cy="50" r="40" stroke-dasharray="${has(ist) ? arc * f(ist) : 0} ${C}" transform="rotate(135 50 50)"/>
      ${st ? `<circle class="mark" cx="${kx}" cy="${ky}" r="6.5"/>` : ""}
      <text x="50" y="52" class="rv">${has(center) ? fmt(center) + "°" : "–"}</text>
      <text x="50" y="67" class="rs">Ist ${fmt(ist)}°</text></svg>`;
  }

  _tile({ name, ist, soll, mode, problem, ent, note, iconSvg, plan, seed }) {
    const tone = this._tone(mode, problem);
    const comfort = this._st(ent.comfort);
    const presence = this._on(ent.presence);
    return `<div class="tile ${tone}">
      <div class="tname">${iconSvg || ""}<span>${esc(name)}</span>${presence ? '<span class="dot" title="Präsenz">●</span>' : ""}</div>
      ${this._dial(ist, ent.comfort, tone, soll)}
      <div class="tmode">${esc(problem ? PROBLEMS[problem] || problem : MODES[mode] || mode || "–")}</div>
      ${note ? `<div class="note">${esc(note)}</div>` : ""}
      ${comfort ? `<div class="stepper"><button data-step="${ent.comfort}" data-d="-1" aria-label="Komfort niedriger">−</button>
        <span>Komfort<b>${fmt(comfort.state)}°</b></span>
        <button data-step="${ent.comfort}" data-d="1" aria-label="Komfort höher">+</button></div>` : ""}
      ${plan !== undefined ? this._planLine(plan, ent.target, name, plan ? null : seed) : ""}
      ${ent.pre_heat ? `<button class="chip ${this._on(ent.pre_heat) ? "on" : ""}" data-toggle="${ent.pre_heat}">Vorheizen</button>` : ""}
    </div>`;
  }

  // Absenkung je Kreis/Raum als kleine Zeile mit −/+
  _setback(id) {
    const st = this._st(id);
    if (!st) return "";
    return `<div class="mini"><button data-step="${id}" data-d="-1" aria-label="Absenkung niedriger">−</button>
      <span>Absenkung <b>${fmt(st.state)}°</b></span><button data-step="${id}" data-d="1" aria-label="Absenkung höher">+</button></div>`;
  }

  // Zeitplan (HA-Zeitplan-Helfer): an/aus bis …, Klick öffnet die Helfer
  // Zeitplan-Knopf öffnet den eigenen Editor (HEATING-20); ohne Plan: „Zeitplan anlegen“ (Raum: Vorlage = Plan des Kreises)
  _planLine(id, target, name, seed) {
    const attrs = `data-plan="${esc(id || "")}" data-target="${esc(target || "")}" data-name="${esc(name || "")}" data-seed="${esc(seed || "")}"`;
    if (!id) return `<button class="plan add" ${attrs}>${seed ? "Eigener Zeitplan" : "Kein Zeitplan – Absenkung · anlegen"}</button>`;
    const st = this._st(id);
    const next = st?.attributes?.next_event ? new Date(st.attributes.next_event).toLocaleTimeString("de-AT", { hour: "2-digit", minute: "2-digit" }) : "";
    // Träger Kessel (HEATING-30): Komfort vor dem Zeitplan bzw. kurze Absenkung übersprungen – sagen, warum warm
    const hint = this._st(target)?.attributes?.zeitplan_hinweis;
    const text = hint === "lead" ? `Vorheizen für ${next} · Kessel schonen`
      : hint === "skip" ? `Kurze Absenkung bis ${next} übersprungen · Kessel schonen`
      : `Zeitplan ${st?.state === "on" ? "Komfort" : "Absenkung"}${next ? ` bis ${next}` : ""}`;
    return `<button class="plan ${st?.state === "on" || hint ? "on" : ""}" ${attrs} title="Zeitplan bearbeiten">${text}${EDIT}</button>`;
  }

  _openPlan(b) {
    const ed = document.createElement("hc-schedule-editor");
    this._editing = true;
    ed.addEventListener("closed", () => { this._editing = false; this._sig = null; this.hass = this._hass; });
    this.shadowRoot.appendChild(ed);
    ed.open({ hass: this._hass, schedule: b.dataset.plan || null, target: b.dataset.target, name: b.dataset.name, seed: b.dataset.seed || null });
  }

  // ---- Schema: Kessel → Verteiler (Vorlauf/Rücklauf) → Pumpe → Heizkreis → Räume ----

  _schema(info, narrow, fuel, brand) {
    if (!info.length) return "";
    const kessel = info.find((i) => i.floor)?.t.kessel_temperatur;
    const W = narrow ? 360 : 820;
    const L = narrow
      ? { kessel: [12, 84], pump: 102, box: [122, 344], room: [158, 344], branch: 138, valve: 148, step: 52 }
      : { kessel: [16, 136], pump: 199, box: [262, 470], room: [560, 804], branch: 500, valve: 530, step: 56 };
    let y = narrow ? 18 : 8;
    const rows = info.map((i) => {
      const n = i.rooms.length;
      let cy, rooms;
      if (narrow) {
        cy = y + 24;
        rooms = i.rooms.map((r, k) => ({ ...r, y: cy + 58 + k * L.step }));
        y = cy + 30 + (n ? n * L.step + 18 : 18);
      } else {
        const h = Math.max(1, n) * L.step + 20;
        cy = y + h / 2;
        rooms = i.rooms.map((r, k) => ({ ...r, y: cy - ((n - 1) * L.step) / 2 + k * L.step }));
        y += h;
      }
      return { ...i, cy, rooms };
    });
    const top = rows[0].cy, bottom = rows[rows.length - 1].cy;
    const any = rows.some((r) => r.flow);
    // Kessel so hoch wie alle Heizkreise: jeder Kreis bekommt eine gerade Doppelleitung, nichts kreuzt sich
    // mindestens 120 hoch (bei nur einem Kreis sonst zu flach), mittig zu den Kreisen, nicht über den Rand
    const bh = Math.max(bottom - top + 68, 120);
    const shift = Math.max(0, 8 - ((top + bottom) / 2 - bh / 2));  // Kreise nach unten, damit die Box mittig bleibt
    for (const r of rows) { r.cy += shift; for (const z of r.rooms) z.y += shift; }
    y += shift;
    const boiler = { x: L.kessel[0], y: (top + bottom) / 2 + shift - bh / 2, w: L.kessel[1] - L.kessel[0], h: bh };
    const H = Math.max(y, boiler.y + boiler.h) + 8;
    // Rohr: durchgehende Leitung, bei Fluss mit laufender Strichlinie darüber – Enden sitzen immer sauber an der Kante
    const pipe = (on, back, color, d, thin) => {
      const t = thin ? "thin" : "";
      return on
        ? `<path class="pipe base ${t}" style="stroke:${color}" d="${d}"/><path class="pipe flow ${t} ${back ? "back" : ""}" style="stroke:${color}" d="${d}"/>`
        : `<path class="pipe idle ${t}" d="${d}"/>`;
    };
    const kx = boiler.x + boiler.w;
    let s = "";
    for (const r of rows) s += pipe(r.flow, true, COLD, `M${kx} ${r.cy + 6}H${L.box[0]}`);
    for (const r of rows) {
      const [bx, bx2] = L.box;
      const sub = r.floor ? `Pumpe ${r.t.pumpe_ist ? "läuft" : "aus"}${r.t.pumpe_soll !== r.t.pumpe_ist && r.t.pumpe_soll != null ? ` · würde ${r.t.pumpe_soll ? "ein" : "aus"}schalten` : ""}` : `${fmt(r.ist)} → ${fmt(r.soll)} °C`;
      s += pipe(r.flow, false, HOT, `M${kx} ${r.cy - 6}H${bx}`) + I.pump(L.pump, r.cy - 6, r.flow);
      s += `<rect class="box ${r.flow ? "hot" : ""} ${r.problem ? "warnbox" : ""}" x="${bx}" y="${r.cy - 24}" width="${bx2 - bx}" height="48" rx="12"/>
        <text class="t" x="${bx + 14}" y="${r.cy - 4}">${esc(r.name)}</text>
        <text class="s" x="${bx + 14}" y="${r.cy + 14}">${esc(sub)}</text>`;
      for (const z of r.rooms) {
        const d = narrow ? `M${L.branch} ${r.cy + 24}V${z.y - 8}Q${L.branch} ${z.y} ${L.branch + 8} ${z.y}H${L.room[0]}` : elbow(bx2, r.cy, L.branch, L.room[0], z.y);
        const [rx, rx2] = L.room;
        const info2 = z.problem ? PROBLEMS[z.problem] || z.problem : z.passive ? (has(z.ist) ? `${fmt(z.ist)} °C` : "–") : `${fmt(z.ist)} → ${fmt(z.soll)} °C`;
        const extra = z.passive ? " · ohne Thermostat" : z.zone ? (z.t.ventile_offen ? " · Ventil offen" : " · Ventil zu") : has(z.t.trv_sollwert) ? ` · TRV ${fmt(z.t.trv_sollwert)}` : "";
        s += pipe(z.flow, false, HOT, d, true) + (z.passive ? "" : (z.zone ? I.valve : I.trv)(L.valve, z.y, z.flow));
        s += `<rect class="box ${z.flow ? "hot" : ""} ${z.problem ? "warnbox" : ""}" x="${rx}" y="${z.y - 21}" width="${rx2 - rx}" height="42" rx="10"/>
          ${z.zone ? I.floor(rx + 20, z.y, z.flow) : I.radiator(rx + 20, z.y, z.flow)}
          <text class="t sm" x="${rx + 40}" y="${z.y - 3}">${esc(z.name)}</text>
          <text class="s" x="${rx + 40}" y="${z.y + 13}">${esc(info2 + extra)}</text>
          ${z.problem ? I.warn(rx2 - 16, z.y) : ""}`;
      }
    }
    // Pelletlager: Füllung von unten in der Farbe der Umrandung, Restmenge in kg nach Füllstand eingefärbt
    const kg = fuel?.state, max = fuel?.attributes?.max_kg;
    const p = has(kg) && has(max) && Number(max) > 0 ? Math.max(0, Math.min(1, Number(kg) / Number(max))) : null;
    const level = p === null ? "" : p < 0.15 ? "lv-low" : p < 0.35 ? "lv-mid" : "lv-ok";
    const clip = `hc-tank-${(this._clipN = (this._clipN || 0) + 1)}`;
    const ly = p === null ? 0 : boiler.y + boiler.h * (1 - p);
    const tank = p === null ? "" : `<clipPath id="${clip}"><rect x="${boiler.x}" y="${boiler.y}" width="${boiler.w}" height="${boiler.h}" rx="14"/></clipPath>
      <rect class="lvl" clip-path="url(#${clip})" x="${boiler.x}" y="${ly}" width="${boiler.w}" height="${boiler.y + boiler.h - ly}"/>`;
    const cx = boiler.x + boiler.w / 2, cyB = boiler.y + boiler.h / 2;
    // Hersteller statt „Wärmeerzeuger“; Vaillant zeigt die freien Schreibvorgänge (Cloud-Budget je Stunde)
    const title = { vaillant: "Vaillant", oekofen: "Ökofen" }[String(brand || "").toLowerCase()] || "Wärmeerzeuger";
    const budget = info.find((i) => has(i.t.schreib_budget_rest));
    const writes = budget ? `${budget.t.schreib_budget_rest}/${budget.t.schreib_budget}` : null;
    const big = has(kessel) ? fmt(kessel, 0) + " °C" : writes || "–";
    // Brenner (Ökofen, HEATING-24): solange er moduliert, glüht die Umrandung (Fabian: kein Wort, kein Emoji)
    const k = fuel?.attributes?.kessel;
    const burning = has(k?.modulation) ? Number(k.modulation) > 0 : null;
    s = `<rect class="box boiler ${burning === false ? "cold" : burning ? "burn" : ""}" x="${boiler.x}" y="${boiler.y}" width="${boiler.w}" height="${boiler.h}" rx="14"><title>${burning ? `Brenner an · ${fmt(k.modulation, 0)} %` : burning === false ? "Brenner aus" : ""}</title></rect>${tank}
      <text class="s mid" x="${cx}" y="${cyB - 24}">${title}</text>
      <text class="big mid" x="${cx}" y="${cyB + 4}">${big}</text>
      ${!has(kessel) && writes ? `<text class="s mid" x="${cx}" y="${cyB + 24}">${narrow ? "Writes" : "Writes frei / h"}</text>` : ""}
      ${has(kg) ? `<text class="pel mid ${level} ${narrow ? "sm" : ""}" x="${cx}" y="${cyB + 28}">${Math.round(Number(kg)).toLocaleString("de-AT")} kg</text>` : ""}` + s;
    return `<svg class="schema ${narrow ? "" : "wide"}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Anlagenschema">${s}</svg>`;
  }

  // Kesseldaten der Ökofen-Integration (HEATING-21): Außentemperatur, Starts/Tag, Laufzeit/Start, Warmwasser mit Kesselwärme
  _kessel(k) {
    if (!k) return "";
    const parts = [
      has(k.outdoor) ? `Außen <b>${fmt(k.outdoor)} °C</b>` : "",
      has(k.starts_per_day) ? `<b>${fmt(k.starts_per_day)}</b> Brennerstarts/Tag` : "",
      has(k.runtime_per_start) ? `<b>${fmt(k.runtime_per_start, 0)} min</b> je Start` : "",
    ].filter(Boolean);
    const dhw = k.dhw_boiler_heat ? this._st(k.dhw_boiler_heat) : null;
    const on = dhw?.state === "1_ein";
    return `<div class="kessel">${parts.map((x) => `<span>${x}</span>`).join("")}
      ${dhw ? `<button class="chip ${on ? "on" : ""}" data-select="${esc(k.dhw_boiler_heat)}" data-option="${on ? "0_aus" : "1_ein"}" aria-pressed="${on}"
        title="Warmwasser mit der Restwärme nach einem Heizlauf laden – spart Brennerstarts">Warmwasser mit Kesselwärme</button>` : ""}</div>`;
  }

  _legend() {
    return `<div class="legend">
      <span><i class="burnkey"></i>Brenner an</span>
      <span><i class="ln" style="background:${HOT}"></i>Vorlauf warm</span>
      <span><i class="ln" style="background:${COLD}"></i>Rücklauf</span>
      <span><i class="ln" style="background:${IDLE}"></i>steht</span>
      <span>${icon(I.pump, true, 24, 24)}Pumpe läuft</span>
      <span>${icon(I.valve, true, 20, 16)}Ventil offen</span>
      <span>${icon(I.valve, false, 20, 16)}zu</span>
      <span>${icon(I.trv, true, 20, 32)}Thermostat-Ventil</span>
      <span>${icon(I.radiator, true, 24, 20)}Heizkörper</span>
      <span>${icon(I.floor, true, 24, 20)}Fußboden</span>
    </div>`;
  }

  // ---- Seite -------------------------------------------------------------

  _circuitGroup(i) {
    const t = i.t;
    const meta = i.floor
      ? `Kessel ${fmt(t.kessel_temperatur, 0)} °C · Freigabe ${t.kessel_freigabe ? "ja" : "nein"}`
      // Budget nur, wo es eins gibt (Vaillant-Cloud); Ökofen hat keins
      : `Anlage steht auf ${fmt(t.anlage_sollwert)} °C · ${DECISIONS[t.entscheidung] || t.entscheidung || ""}${has(t.schreib_budget) ? ` · noch ${t.schreib_budget_rest} von ${t.schreib_budget} Schreibvorgängen` : ""}`;
    const would = (t.wuerde_schalten || []).map((w) => esc(w.replace("switch.", ""))).join(", ");
    const tiles = [];
    if (i.floor) {
      tiles.push(`<div class="tile ${i.flow ? "hot" : "off"}"><div class="tname">${icon(I.pump, i.flow)}<span>Kessel & Pumpe</span></div>
        <div class="bigtemp">${fmt(t.kessel_temperatur, 0)}°</div><div class="tmode">Pumpe ${t.pumpe_ist ? "läuft" : "aus"}</div>
        <div class="note">${t.pumpe_soll !== t.pumpe_ist && t.pumpe_soll != null ? `würde ${t.pumpe_soll ? "ein" : "aus"}schalten` : `Freigabe ${t.kessel_freigabe ? "ja" : "nein"}`}</div>
        ${i.ent.pre_heat ? `<button class="chip ${this._on(i.ent.pre_heat) ? "on" : ""}" data-toggle="${i.ent.pre_heat}">Vorheizen</button>` : ""}</div>`);
    } else {
      tiles.push(this._tile({ name: i.rooms.length ? "Ganzer Kreis" : i.name.replace(/^HK\d+\s*/, ""), ist: i.ist, soll: i.soll, mode: i.mode, problem: i.problem, ent: i.ent, iconSvg: icon(I.pump, i.flow) }));
    }
    for (const z of i.rooms.filter((r) => !r.passive)) { // passive Heizkörper nur im Schema, ohne Regler
      tiles.push(this._tile({ ...z, plan: z.t.zeitplan !== t.zeitplan ? z.t.zeitplan : null, seed: t.zeitplan, note: z.zone ? `Ventil ${z.t.ventile_offen ? "offen" : "zu"}` : has(z.t.trv_sollwert) && has(z.soll) && Math.abs(z.t.trv_sollwert - z.soll) > 0.1 ? `Thermostat steht noch auf ${fmt(z.t.trv_sollwert)}°` : "", iconSvg: icon(z.zone ? I.floor : I.radiator, z.flow) }));
    }
    return `<section class="group">
      <div class="ghead"><h2>${esc(i.name)}</h2>${this._badge(i.mode, i.problem)}</div>
      <div class="gmeta">${esc(meta)}</div>
      <div class="gctl">${this._planLine(t.zeitplan, i.ent.target, i.name)}${this._setback(i.ent.setback)}
        ${i.ent.enabled ? `<button class="chip ${this._on(i.ent.enabled) ? "" : "offchip"}" data-toggle="${i.ent.enabled}" aria-pressed="${!this._on(i.ent.enabled)}"
          title="Ganz aus, z. B. unbewohnt oder Sommer – Frostschutz bleibt">${this._on(i.ent.enabled) ? "Kreis ausschalten" : "Kreis ist aus · einschalten"}</button>` : ""}</div>
      ${i.problem ? `<div class="alert">${esc(PROBLEMS[i.problem] || i.problem)}</div>` : ""}
      ${would ? `<div class="would">Würde schalten: ${would}</div>` : ""}
      <div class="tiles">${tiles.join("")}</div>
    </section>`;
  }

  _system(sys) {
    const s = sys.ent, writing = this._on(s.write_enabled);
    const problems = this._a(s.problem).probleme || [];
    const info = this._info(sys);
    return `<div class="system">
      <h1>${esc(sys.name)}</h1>
      <div class="status ${writing ? "live" : "shadow"}">
        <div class="stxt"><b>${writing ? "Steuert aktiv" : "Schattenbetrieb"}</b><small>${writing ? "Heating Core schaltet die Anlage." : "Rechnet mit, schaltet aber nichts."}</small></div>
        <div class="seg">
          <button class="${writing ? "on" : ""}" data-toggle="${s.write_enabled}" aria-pressed="${writing}" title="An: Heating Core steuert die Anlage. Aus: rechnet nur mit (Schattenbetrieb).">Steuern</button>
          <button class="${this._on(s.away) ? "on" : ""}" data-toggle="${s.away}" aria-pressed="${this._on(s.away)}">Abwesend</button>
          <button class="${this._on(s.guest) ? "on" : ""}" data-toggle="${s.guest}" aria-pressed="${this._on(s.guest)}">Gast</button>
        </div>
      </div>
      ${problems.length ? `<div class="alert">${icon(I.warn, false, 20, 20)}<span>${problems.map((p) => esc(p.replace(/: (\w+)$/, (m, k) => " – " + (PROBLEMS[k] || k)))).join("<br>")}</span></div>` : ""}
      <section class="card"><div class="cardhead"><h2>Anlage</h2></div>${this._schema(info, this._narrow, this._st(s.fuel), sys.model)}${this._kessel(this._a(s.fuel).kessel)}${this._legend()}</section>
      ${info.map((i) => this._circuitGroup(i)).join("")}
      <section class="card"><h2>Grundwerte</h2><div class="sets">
        <div class="grp"><h3>Abwesend</h3>${this._setting(s.away_temp, "Temperatur", "im ganzen Haus, solange Abwesend an ist")}</div>
        <div class="grp"><h3>Präsenz</h3>${this._setting(s.presence_on_min, "Gilt nach", "so lange da, bevor Komfort beginnt")}
          ${this._setting(s.presence_off_min, "Hält noch", "Komfort nach dem Gehen", 5)}</div>
        <div class="grp"><h3>Fenster</h3>${this._setting(s.window_delay_s, "Absenken nach", "so lange offen, bevor abgesenkt wird")}
          ${this._setting(s.window_settle_s, "Danach warten", "nach dem Schließen, Fühler misst zu kalt")}</div>
        <div class="grp"><h3>Regelung</h3>${this._setting(s.hysteresis, "Hysterese", "Abstand zum Ziel, bevor nachgeregelt wird")}
          ${this._setting(s.pre_heat_timeout_min, "Vorheizen höchstens", "schaltet sich danach selbst aus")}</div>
      </div></section>
    </div>`;
  }

  _wireDial(svg) {
    const { dial: id, lo, hi, step } = svg.dataset;
    const [min, max, st] = [Number(lo), Number(hi), Number(step)];
    const knob = svg.querySelector(".mark"), label = svg.querySelector(".rv");
    let value = null;
    const at = (e) => {
      const r = svg.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 100 - 50, y = ((e.clientY - r.top) / r.height) * 100 - 50;
      let d = ((Math.atan2(y, x) * 180) / Math.PI - 135 + 720) % 360;
      if (d > 270) d = d > 315 ? 0 : 270; // Lücke unten: zum nächsten Ende
      value = Math.round((min + (d / 270) * (max - min)) / st) * st;
      const rad = (135 + (270 * (value - min)) / (max - min)) * (Math.PI / 180);
      knob.setAttribute("cx", 50 + 40 * Math.cos(rad));
      knob.setAttribute("cy", 50 + 40 * Math.sin(rad));
      label.textContent = `${fmt(value)}°`;
    };
    svg.addEventListener("pointerdown", (e) => { this._dragging = true; svg.setPointerCapture(e.pointerId); at(e); });
    svg.addEventListener("pointermove", (e) => { if (svg.hasPointerCapture(e.pointerId)) at(e); });
    const done = () => {
      if (!this._dragging) return;
      this._dragging = false;
      if (value !== null && value !== Number(this._st(id)?.state)) this._setNumber(id, value);
      else this.hass = this._hass;
    };
    svg.addEventListener("pointerup", done);
    svg.addEventListener("pointercancel", done);
    svg.addEventListener("keydown", (e) => { if (e.key === "ArrowUp" || e.key === "ArrowRight") this._step(id, 1); if (e.key === "ArrowDown" || e.key === "ArrowLeft") this._step(id, -1); });
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
    this.shadowRoot.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => {
      history.pushState(null, "", b.dataset.nav);
      window.dispatchEvent(new CustomEvent("location-changed"));
    }));
    this.shadowRoot.querySelectorAll("[data-select]").forEach((b) => b.addEventListener("click", () =>
      this._hass.callService("select", "select_option", { entity_id: b.dataset.select, option: b.dataset.option })));
    this.shadowRoot.querySelectorAll("[data-plan]").forEach((b) => b.addEventListener("click", () => this._openPlan(b)));
    this.shadowRoot.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => this._step(b.dataset.step, Number(b.dataset.d), b.dataset.by)));
    this.shadowRoot.querySelectorAll("[data-dial]").forEach((svg) => this._wireDial(svg));
  }
}

// ---- Zeitplan-Editor (HEATING-20) -------------------------------------------
// Bearbeitet den HA-Zeitplan-Helfer direkt (schedule/list, schedule/update, schedule/create): HA bleibt die einzige Quelle.
// Wochenraster Mo–So: Komfort-Blöcke anlegen, verschieben, am Rand ziehen (15 min), antippen für ±15 min/Löschen, Tag kopieren (HEATING-31).
const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const DAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const STEP = 15; // Minuten
const toMin = (t) => { const [h, m] = String(t).split(":").map(Number); return h * 60 + (m || 0); };
const toTime = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}:00`;
const hhmm = (m) => toTime(m).slice(0, 5);

// Blöcke sortieren, überlappende/anschließende zusammenlegen, leere verwerfen
function normalizeDay(blocks) {
  const out = [];
  for (const b of [...blocks].filter((b) => b.to > b.from).sort((a, b) => a.from - b.from)) {
    const last = out[out.length - 1];
    if (last && b.from <= last.to) last.to = Math.max(last.to, b.to);
    else out.push({ from: b.from, to: b.to });
  }
  return out;
}

class HcScheduleEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._sel = null; this._copy = null; }

  // opts: { hass, schedule (entity_id oder null), target (Sensor-Entität des Kreises/Raums), name, seed (Plan als Vorlage) }
  async open(opts) {
    Object.assign(this, opts);
    this._err = "";
    this._days = DAYS.map(() => []);
    this._item = null;
    try {
      const src = this.schedule || this.seed;
      if (src) {
        const reg = await this.hass.callWS({ type: "config/entity_registry/get", entity_id: src });
        const items = await this.hass.callWS({ type: "schedule/list" });
        const item = items.find((i) => i.id === reg.unique_id);
        if (!item) throw new Error("Zeitplan nicht gefunden");
        if (this.schedule) this._item = item;
        this._days = DAYS.map((d) => normalizeDay((item[d] || []).map((b) => ({ from: toMin(b.from), to: toMin(b.to) }))));
      }
    } catch (e) { this._err = e.message || String(e); }
    this._render();
  }

  _close(saved) { this.dispatchEvent(new CustomEvent("closed", { detail: { saved } })); this.remove(); }

  async _save() {
    const days = Object.fromEntries(DAYS.map((d, i) => [d, normalizeDay(this._days[i]).map((b) => ({ from: toTime(b.from), to: b.to >= 1440 ? "24:00:00" : toTime(b.to) }))]));
    this._busy = true; this._render();
    try {
      if (this._item) {
        const { id, ...rest } = this._item;
        await this.hass.callWS({ type: "schedule/update", schedule_id: id, ...rest, ...days });
      } else {
        const item = await this.hass.callWS({ type: "schedule/create", name: `Heizplan ${this.name}`, icon: "mdi:radiator", ...days });
        const ents = await this.hass.callWS({ type: "config/entity_registry/list" });
        const ent = ents.find((e) => e.platform === "schedule" && e.unique_id === item.id);
        if (!ent) throw new Error("Neuer Zeitplan hat keine Entität");
        await this.hass.callWS({ type: "heating_core/assign_schedule", entity_id: this.target, schedule: ent.entity_id });
      }
      this._close(true);
    } catch (e) {
      this._busy = false;
      this._err = e.message || String(e);
      this._render();
    }
  }

  _minAt(track, x) {
    const r = track.getBoundingClientRect();
    return Math.max(0, Math.min(1440, Math.round(((x - r.left) / r.width) * 1440 / STEP) * STEP));
  }

  _render() {
    const sel = this._sel;
    const now = new Date(), today = (now.getDay() + 6) % 7, nowMin = now.getHours() * 60 + now.getMinutes();
    const rows = this._days.map((blocks, d) => `
      <div class="row">
        <span class="day">${DAY_DE[d]}</span>
        <div class="track" data-day="${d}">
          ${[6, 12, 18].map((h) => `<i class="tick" style="left:${(h / 24) * 100}%"></i>`).join("")}
          ${d === today ? `<i class="now" style="left:${(nowMin / 1440) * 100}%" title="jetzt"></i>` : ""}
          ${blocks.map((b, k) => `<button class="blk ${sel && sel.d === d && sel.k === k ? "sel" : ""}" data-d="${d}" data-k="${k}"
              style="left:${(b.from / 1440) * 100}%;width:${((b.to - b.from) / 1440) * 100}%" aria-label="${DAY_DE[d]} ${hhmm(b.from)}–${hhmm(b.to)}">
              <i class="h l" data-edge="from"></i><span>${hhmm(b.from)}–${hhmm(b.to)}</span><i class="h r" data-edge="to"></i></button>`).join("")}
        </div>
        <button class="cp ${this._copy === d ? "on" : ""}" data-copy="${d}" aria-label="${DAY_DE[d]} kopieren" title="Tag kopieren">⧉</button>
      </div>
      ${sel && sel.d === d && blocks[sel.k] ? this._editRow(blocks[sel.k]) : ""}
      ${this._copy === d ? this._copyRow(d) : ""}`).join("");
    this.shadowRoot.innerHTML = `<style>${EDITOR_CSS}</style>
      <div class="back"></div>
      <div class="dlg" role="dialog" aria-modal="true" aria-label="Zeitplan ${esc(this.name)}">
        <h2>Zeitplan ${esc(this.name)}</h2>
        <p class="hint">Farbige Blöcke = Komfort, sonst Absenkung. Auf freier Fläche ziehen legt einen Block an; Blöcke verschieben oder am Rand ziehen, antippen zum Feinstellen.</p>
        ${this._err ? `<div class="err">${esc(this._err)}</div>` : ""}
        <div class="hours"><span></span><div>${[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<b style="left:${(h / 24) * 100}%">${h}</b>`).join("")}</div><span></span></div>
        ${rows}
        <div class="foot"><button class="ghost" data-act="cancel">Abbrechen</button>
          <button class="primary" data-act="save" ${this._busy ? "disabled" : ""}>${this._item ? "Speichern" : "Zeitplan anlegen"}</button></div>
      </div>`;
    const $ = (q) => this.shadowRoot.querySelectorAll(q);
    $("[data-act=cancel]").forEach((b) => b.addEventListener("click", () => this._close(false)));
    this.shadowRoot.querySelector(".back").addEventListener("click", () => this._close(false));
    $("[data-act=save]").forEach((b) => b.addEventListener("click", () => this._save()));
    // Maus/Finger laufen über _wireTrack; hier nur Tastatur (Enter/Leertaste, detail 0)
    $(".blk").forEach((b) => b.addEventListener("click", (e) => { if (e.detail === 0) this._toggle(Number(b.dataset.d), Number(b.dataset.k)); }));
    $(".cp").forEach((b) => b.addEventListener("click", () => { this._copy = this._copy === Number(b.dataset.copy) ? null : Number(b.dataset.copy); this._sel = null; this._render(); }));
    $(".track").forEach((t) => this._wireTrack(t));
    $("[data-step]").forEach((btn) => btn.addEventListener("click", () => {
      const b = { ...this._days[sel.d][sel.k] }, dv = Number(btn.dataset.dir) * STEP;
      if (btn.dataset.step === "from") b.from = Math.max(0, Math.min(b.to - STEP, b.from + dv));
      else b.to = Math.min(1440, Math.max(b.from + STEP, b.to + dv));
      this._focus = `[data-step=${btn.dataset.step}][data-dir="${btn.dataset.dir}"]`;
      this._commit(sel.d, sel.k, b);
    }));
    $("[data-act=del]").forEach((b) => b.addEventListener("click", () => { this._days[sel.d].splice(sel.k, 1); this._sel = null; this._render(); }));
    $("[data-to]").forEach((b) => b.addEventListener("click", () => {
      const src = this._days[this._copy];
      b.dataset.to.split(",").map(Number).forEach((i) => { if (i !== this._copy) this._days[i] = src.map((x) => ({ ...x })); });
      this._copy = null;
      this._render();
    }));
    if (this._focus) { this.shadowRoot.querySelector(this._focus)?.focus(); this._focus = null; }
  }

  _toggle(d, k) {
    this._sel = this._sel && this._sel.d === d && this._sel.k === k ? null : { d, k };
    this._copy = null;
    this._render();
  }

  // Block k (-1 = neu) durch b ersetzen, zusammenlegen, den Ergebnis-Block ausgewählt lassen
  _commit(d, k, b) {
    this._days[d] = normalizeDay([...this._days[d].filter((_, i) => i !== k), b]);
    const i = this._days[d].findIndex((x) => x.from <= b.from && b.from < x.to);
    this._sel = i >= 0 ? { d, k: i } : null;
    this._copy = null;
    this._render();
  }

  _editRow(b) {
    const st = (edge, v) => `<span class="stp"><span class="lbl">${edge === "from" ? "Beginn" : "Ende"}</span>
      <button class="rb" data-step="${edge}" data-dir="-1" aria-label="${edge === "from" ? "Beginn" : "Ende"} 15 min früher">−</button>
      <b>${v}</b><button class="rb" data-step="${edge}" data-dir="1" aria-label="${edge === "from" ? "Beginn" : "Ende"} 15 min später">+</button></span>`;
    return `<div class="edit">${st("from", hhmm(b.from))}${st("to", hhmm(b.to))}
      <button class="ghost danger" data-act="del">Löschen</button></div>`;
  }

  _copyRow(d) {
    const t = [["Mo–Fr", "0,1,2,3,4"], ["Sa–So", "5,6"], ["alle Tage", "0,1,2,3,4,5,6"]];
    return `<div class="edit">${DAY_DE[d]} kopieren auf ${t.map(([n, ids]) => `<button class="ghost" data-to="${ids}">${n}</button>`).join("")}</div>`;
  }

  // Ziehen: freie Fläche = neuer Block, Rand = Beginn/Ende, Mitte = verschieben (15-min-Raster); ohne Bewegung = Antippen
  _wireTrack(track) {
    const d = Number(track.dataset.day);
    track.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const blk = e.target.closest(".blk");
      const k = blk ? Number(blk.dataset.k) : -1;
      const orig = blk ? { ...this._days[d][k] } : null;
      const edge = e.target.closest(".h")?.dataset.edge || (blk ? "move" : "new");
      const x0 = e.clientX, m0 = this._minAt(track, x0);
      try { track.setPointerCapture(e.pointerId); } catch { /* synthetische Events im UI-Test */ }
      const el = blk || Object.assign(document.createElement("div"), { className: "blk ghostblk", innerHTML: "<span></span>" });
      const tip = Object.assign(document.createElement("div"), { className: "tip" });
      let moved = false, cur = orig;
      const move = (ev) => {
        if (!moved && Math.abs(ev.clientX - x0) < 4) return;
        if (!moved) { moved = true; if (!blk) track.appendChild(el); track.appendChild(tip); el.classList.add("drag"); }
        const m = this._minAt(track, ev.clientX);
        if (edge === "new") cur = { from: Math.min(m0, m), to: Math.max(m0, m) };
        else if (edge === "from") cur = { from: Math.min(m, orig.to - STEP), to: orig.to };
        else if (edge === "to") cur = { from: orig.from, to: Math.max(m, orig.from + STEP) };
        else { const len = orig.to - orig.from, f = Math.max(0, Math.min(1440 - len, orig.from + m - m0)); cur = { from: f, to: f + len }; }
        el.style.left = `${(cur.from / 1440) * 100}%`;
        el.style.width = `${((cur.to - cur.from) / 1440) * 100}%`;
        tip.style.left = `${((cur.from + cur.to) / 2880) * 100}%`;
        tip.textContent = el.querySelector("span").textContent = `${hhmm(cur.from)}–${hhmm(cur.to)}`;
      };
      const up = () => {
        track.removeEventListener("pointermove", move);
        track.removeEventListener("pointerup", up);
        track.removeEventListener("pointercancel", up);
        if (!moved) return k >= 0 ? this._toggle(d, k) : (this._sel = null, this._copy = null, this._render());
        if (cur.to - cur.from < STEP) return this._render();
        this._commit(d, k, cur);
      };
      track.addEventListener("pointermove", move);
      track.addEventListener("pointerup", up);
      track.addEventListener("pointercancel", up);
    });
  }
}

const EDITOR_CSS = `
  :host { position: fixed; inset: 0; z-index: 10; display: flex; align-items: center; justify-content: center; font-family: inherit; }
  .back { position: absolute; inset: 0; background: #0008; }
  .dlg { position: relative; background: var(--card-background-color); color: var(--primary-text-color); border-radius: 20px; padding: 18px 16px;
    width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto; box-sizing: border-box; }
  h2 { margin: 0 0 4px; font-size: 18px; } .hint { margin: 0 0 12px; font-size: 13px; color: var(--secondary-text-color); }
  .err { background: ${WARN}22; border: 1px solid ${WARN}; border-radius: 10px; padding: 8px 12px; margin-bottom: 10px; font-size: 13px; }
  .row, .hours { display: grid; grid-template-columns: 28px 1fr 32px; align-items: center; gap: 8px; margin: 6px 0; }
  .hours div { position: relative; height: 16px; font-size: 11px; color: var(--secondary-text-color); }
  .hours b { position: absolute; transform: translateX(-50%); font-weight: 400; } .hours b:first-child { transform: none; } .hours b:last-child { transform: translateX(-100%); }
  .day { font-size: 13px; font-weight: 600; }
  .track { position: relative; height: 40px; border-radius: 10px; touch-action: none; cursor: crosshair; user-select: none; -webkit-user-select: none;
    background: repeating-linear-gradient(to right, transparent 0 calc(100% / 24 - 1px), var(--divider-color) calc(100% / 24 - 1px) calc(100% / 24)), ${COLD}18; }
  .tick { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--secondary-text-color); opacity: .45; }
  .now { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; border-radius: 1px; background: var(--primary-color); z-index: 1; pointer-events: none; }
  .blk { position: absolute; top: 3px; bottom: 3px; background: ${HOT}; color: #fff; border: 0; border-radius: 8px; padding: 0; font: inherit; font-size: 11px;
    display: flex; align-items: center; justify-content: center; min-width: 4px; box-sizing: border-box; cursor: grab; touch-action: none; }
  .blk span { overflow: hidden; white-space: nowrap; text-overflow: clip; padding: 0 6px; pointer-events: none; }
  .blk.sel { outline: 3px solid var(--primary-color); outline-offset: 1px; z-index: 1; } .blk.drag { opacity: .85; z-index: 2; cursor: grabbing; }
  .ghostblk { opacity: .6; pointer-events: none; }
  .h { position: absolute; top: -3px; bottom: -3px; width: 18px; cursor: ew-resize; z-index: 1; } .h.l { left: -9px; } .h.r { right: -9px; }
  .h::after { content: ""; position: absolute; left: 7px; top: 30%; bottom: 30%; width: 4px; border-radius: 2px; background: #fff; opacity: 0; transition: opacity .15s; }
  .blk:hover .h::after, .blk.sel .h::after, .blk.drag .h::after { opacity: .9; }
  .tip { position: absolute; top: -26px; transform: translateX(-50%); background: var(--primary-text-color); color: var(--card-background-color);
    font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 6px; white-space: nowrap; pointer-events: none; z-index: 3; }
  .cp { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); font-size: 15px; }
  .cp.on { border-color: var(--primary-color); color: var(--primary-color); }
  .edit { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: 2px 0 10px 36px; font-size: 13px; }
  .stp { display: inline-flex; align-items: center; gap: 6px; } .lbl { color: var(--secondary-text-color); }
  .stp b { min-width: 46px; text-align: center; font-size: 16px; font-variant-numeric: tabular-nums; }
  .rb { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); font: inherit; font-size: 18px; line-height: 1; }
  .foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
  .primary, .ghost { border-radius: 999px; padding: 8px 16px; font: inherit; font-size: 14px; border: 1px solid var(--primary-color); }
  .edit .ghost { padding: 6px 14px; font-size: 13px; }
  .primary { background: var(--primary-color); color: var(--text-primary-color, #fff); } .ghost { background: transparent; color: var(--primary-text-color); border-color: var(--divider-color); }
  .danger { color: #e53935; border-color: #e5393588; }
  @media (max-width: 600px) { .blk span { display: none; } .track { height: 44px; } .edit { margin-left: 0; } }
  button:not(:disabled), label:has(input:not(:disabled)) { cursor: pointer; } :disabled { cursor: not-allowed; opacity: .6; }
  .blk:not(:disabled) { cursor: grab; } .blk.drag { cursor: grabbing; }
`;

if (!customElements.get("hc-schedule-editor")) customElements.define("hc-schedule-editor", HcScheduleEditor);

const CSS = `
  :host { display:block; background: var(--primary-background-color); color: var(--primary-text-color); min-height:100vh; }
  .page { max-width: 1100px; margin: 0 auto; padding: 0 16px 32px; font-family: var(--paper-font-body1_-_font-family, system-ui); }
  .top { display:flex; align-items:center; gap:8px; height:56px; font-size:20px; font-weight: 500; }
  h1 { font-size: 26px; font-weight: 600; margin: 4px 0 12px; } h2 { font-size: 16px; font-weight: 600; margin: 0; } .card > h2 { margin-bottom: 12px; }
  .system { margin-bottom: 32px; }
  .muted { color: var(--secondary-text-color); }
  .card { background: var(--card-background-color); border-radius: 16px; padding: 16px; border: 1px solid var(--divider-color); box-shadow: var(--ha-card-box-shadow, none); margin-bottom: 16px; }
  .cardhead { display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; }
  .status { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap: 12px; padding: 12px 16px; border-radius: 16px; margin-bottom: 12px; }
  .status.shadow { background: repeating-linear-gradient(135deg, #90a4ae1f 0 10px, #90a4ae2e 10px 20px); border: 1px dashed #90a4ae; }
  .status.live { background: #43a04722; border: 1px solid #43a047; }
  .stxt { display:flex; flex-direction:column; } .stxt small { color: var(--secondary-text-color); }
  .seg { display:inline-flex; border: 1px solid var(--divider-color); border-radius: 999px; overflow:hidden; background: var(--card-background-color); }
  .seg button { border:0; background: transparent; color: var(--primary-text-color); padding: 8px 14px; font: inherit; font-size: 14px; }
  .seg button + button { border-left: 1px solid var(--divider-color); }
  .seg button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .alert { display:flex; gap: 10px; align-items:center; padding: 10px 14px; border-radius: 12px; background: ${WARN}22; border: 1px solid ${WARN}; margin-bottom: 12px; font-size: 14px; }
  .badge { font-size: 12px; font-weight: 500; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
  .badge.hot { background: ${HOT}; color: #fff; } .badge.eco { background: ${COLD}22; color: ${COLD}; }
  .badge.off { background: var(--secondary-background-color); color: var(--secondary-text-color); } .badge.warn { background: ${WARN}33; color: var(--primary-text-color); }

  .schema { display:block; width: 100%; height: auto; } .schema.wide { max-width: 980px; margin: 0 auto; }
  .schema .box { fill: var(--card-background-color); stroke: var(--divider-color); stroke-width: 1.5; }
  .schema .box.hot { stroke: ${HOT}; } .schema .box.warnbox { stroke: ${WARN}; stroke-dasharray: 4 3; }
  .schema .lvl { fill: ${HOT}; opacity: .16; }
  .schema .pel.sm { font-size: 13px; } .schema .pel { font-size: 15px; font-weight: 600; fill: var(--primary-text-color); } .schema .pel.lv-ok { fill: #43a047; } .schema .pel.lv-mid { fill: ${WARN}; } .schema .pel.lv-low { fill: #e53935; }
  .schema .boiler { fill: ${HOT}12; stroke: ${HOT}66; } .schema .boiler.cold { fill: ${IDLE}12; stroke: ${IDLE}66; }
  .schema .boiler.burn { stroke: ${HOT}; stroke-width: 3; animation: glow 2.4s ease-in-out infinite; }
  @keyframes glow { 0%, 100% { filter: drop-shadow(0 0 2px ${HOT}66); } 50% { filter: drop-shadow(0 0 12px ${HOT}); } }
  @media (prefers-reduced-motion: reduce) { .schema .boiler.burn { animation: none; filter: drop-shadow(0 0 8px ${HOT}); } }
  .schema text { text-anchor: start; } .schema .mid { text-anchor: middle; } .schema .end { text-anchor: end; }
  .schema .t { font-size: 14px; font-weight: 600; fill: var(--primary-text-color); } .schema .t.sm { font-size: 13px; }
  .schema .s { font-size: 12px; fill: var(--secondary-text-color); }
  .schema .big { font-size: 20px; font-weight: 600; fill: var(--primary-text-color); }
  .schema .pipe { fill: none; stroke-width: 3; stroke-linecap: butt; stroke-linejoin: round; } .schema .pipe.thin { stroke-width: 2.2; }
  .schema .pipe.base { opacity: .35; } .schema .pipe.idle { stroke: ${IDLE}; opacity: .5; }
  .schema .pipe.flow { stroke-dasharray: 7 6; animation: flow 1s linear infinite; } .schema .pipe.flow.back { animation-direction: reverse; }
  @keyframes flow { to { stroke-dashoffset: -13; } }
  @media (prefers-reduced-motion: reduce) { .schema .pipe.flow { animation: none; } }
  .pump circle { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.6; } .pump path { fill: ${IDLE}; }
  .pump.on circle { stroke: ${HOT}; } .pump.on path { fill: ${HOT}; }
  .valve rect { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.5; } .valve.open rect { stroke: ${HOT}; }
  .valve path { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.8; stroke-linejoin: round; } .valve.open path { fill: ${HOT}; stroke: ${HOT}; }
  .rad rect { fill: var(--card-background-color); } .rad rect, .rad path { stroke: ${IDLE}; stroke-width: 1.8; } .rad path { fill: none; }
  .rad.on rect, .rad.on path { stroke: ${HOT}; } .rad.on rect { fill: ${HOT}22; }
  .kessel { display:flex; flex-wrap:wrap; align-items:center; gap: 6px 18px; margin-top: 10px; font-size: 13px; color: var(--secondary-text-color); }
  .kessel b { color: var(--primary-text-color); } .kessel .chip { margin-top: 0; }
  .legend { display:flex; flex-wrap:wrap; gap: 6px 16px; margin-top: 12px; font-size: 12px; color: var(--secondary-text-color); align-items:center; }
  .legend .burnkey { width: 14px; height: 18px; border: 2px solid ${HOT}; border-radius: 4px; box-shadow: 0 0 6px ${HOT}; display:inline-block; box-sizing: border-box; }
  .legend span { display:inline-flex; align-items:center; gap: 6px; } .legend .ln { width: 22px; height: 5px; border-radius: 3px; display:inline-block; }

  .group { margin: 20px 0; }
  .ghead { display:flex; align-items:center; gap: 10px; flex-wrap: wrap; margin: 0 4px 2px; }
  .gmeta { font-size: 13px; color: var(--secondary-text-color); margin: 0 4px 10px; }
  .would { font-size: 13px; background: var(--secondary-background-color); border-radius: 10px; padding: 6px 12px; margin-bottom: 10px; }
  .tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
  .tile { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 18px; padding: 12px; display:flex; flex-direction:column; align-items:center; gap: 4px; }
  .tile.hot { border-color: ${HOT}88; } .tile.warn { border-color: ${WARN}; }
  .tname { display:flex; align-items:center; gap: 6px; font-weight: 600; font-size: 14px; align-self: stretch; }
  .tname .dot { color: #43a047; font-size: 10px; }
  .ring { width: 120px; height: 120px; } .ring circle { fill: none; stroke-width: 9; stroke-linecap: round; }
  .ring .track { stroke: var(--secondary-background-color); } .ring .val { stroke: ${IDLE}; }
  .ring.hot .val { stroke: ${HOT}; } .ring.eco .val { stroke: ${COLD}; } .ring.warn .val { stroke: ${WARN}; }
  .ring .mark { fill: #fff; stroke: none; filter: drop-shadow(0 1px 2px #0006); }
  .ring.dial { touch-action: none; cursor: grab; } .ring.dial:active { cursor: grabbing; }
  .ring text { text-anchor: middle; fill: var(--primary-text-color); } .ring .rv { font-size: 22px; font-weight: 600; } .ring .rs { font-size: 10px; fill: var(--secondary-text-color); }
  .tmode { font-size: 13px; font-weight: 500; text-align: center; } .note { font-size: 12px; color: var(--secondary-text-color); text-align: center; }
  .bigtemp { font-size: 44px; font-weight: 600; color: ${HOT}; padding: 22px 0 10px; }
  .stepper { display:flex; align-items:center; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--secondary-text-color); }
  .stepper span { display:flex; flex-direction:column; align-items:center; min-width: 56px; } .stepper b { font-size: 15px; color: var(--primary-text-color); }
  .stepper button { width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-size: 18px; line-height: 1; }
  /* Bedienleiste je Heizkreis: Zeitplan | Absenkung | Ausschalten als gleich hohe Felder (Fabian 11.11.2026) */
  .gctl { display:inline-flex; flex-wrap:wrap; align-items:stretch; gap: 4px; padding: 4px; margin: 0 0 12px; background: var(--secondary-background-color); border-radius: 14px; max-width: 100%; box-sizing: border-box; }
  .gctl > * { margin: 0; min-height: 38px; box-sizing: border-box; display:flex; align-items:center; gap: 8px; padding: 0 12px; border: 0; border-radius: 10px; background: var(--card-background-color); color: var(--primary-text-color); font-size: 13px; }
  .plan .edit { opacity: .55; flex: none; margin-left: 2px; vertical-align: -2px; }
  .gctl > * { flex: 1 1 auto; } .gctl .mini { justify-content: space-between; }
  .gctl .plan, .gctl .plan.on, .gctl .chip, .gctl .mini { margin: 0; border-radius: 10px; padding: 0 12px; font-size: 13px; background: var(--card-background-color); }
  .gctl .plan::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: ${IDLE}; flex: none; }
  .gctl .plan.on::before { background: ${HOT}; } .gctl .plan.add::before { display: none; }
  .gctl .plan.add { border: 1px dashed var(--divider-color); color: var(--secondary-text-color); }
  .gctl .mini span { color: var(--secondary-text-color); } .gctl .mini b { min-width: 40px; display:inline-block; text-align:center; }
  .gctl .chip { color: var(--secondary-text-color); }
  .mini { display:flex; align-items:center; gap: 8px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .mini button { width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); font-size: 14px; line-height: 1; }
  .mini b { color: var(--primary-text-color); }
  .plan { border: 0; background: var(--secondary-background-color); color: var(--secondary-text-color); border-radius: 999px; padding: 4px 10px; font: inherit; font-size: 12px; margin-top: 4px; }
  .plan.on { background: ${HOT}22; color: var(--primary-text-color); } .plan.add { border: 1px dashed var(--divider-color); background: transparent; }
  .chip { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); border-radius: 999px; padding: 5px 12px; font-size: 13px; margin-top: 4px; }
  .chip.offchip { background: ${COLD}22; border-color: ${COLD}; color: var(--primary-text-color); }
  .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .sets { display:grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 400px), 1fr)); gap: 12px; }
  .grp { background: var(--secondary-background-color); border-radius: 12px; padding: 10px 14px; }
  .grp h3 { margin: 2px 0 4px; font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .set { display:flex; align-items:center; justify-content:space-between; gap: 10px; padding: 8px 0; }
  .set + .set { border-top: 1px solid var(--divider-color); }
  .set span { display:block; font-size: 14px; } .set small { display:block; font-size: 12px; color: var(--secondary-text-color); }
  .set .mini { margin-top: 0; flex: none; } .set .mini b { min-width: 58px; text-align: center; font-size: 15px; }
  @media (max-width: 600px) { .tiles { grid-template-columns: repeat(2, 1fr); gap: 10px; } .ring { width: 104px; height: 104px; } .seg button { padding: 8px 11px; } }
  button:not(:disabled), [role="button"], summary, label:has(input:not(:disabled)), input[type="range"]:not(:disabled) { cursor: pointer; }
  :disabled { cursor: not-allowed; }
`;

if (!customElements.get("heating-core-panel")) customElements.define("heating-core-panel", HeatingCorePanel); // HA lädt das Modul nach Updates teils doppelt
