// Heating Core – eigene Seite „Heizung“ (HEATING-9) mit animiertem Anlagenschema (HEATING-10).
// Liest nur Entitäten der Integration heating_core; schaltet über normale HA-Dienste.
// Aufbau (Entwurf „A mit Kacheln aus B“, Fabian 08.11.2026): Status, Schema mit Legende, je Heizkreis Kacheln.

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
const OFF_MODES = new Set(["circuit_off", "summer", "away", "window", "unavailable"]);
const HOT = "#f4511e", COLD = "#1e88e5", IDLE = "#9aa5b1", WARN = "#f5a623";

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
    if (this._dragging || this._queued) return;
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

  // Was die Anlage meldet, aufbereitet für Schema und Kacheln. Wärme „fließt“ nur, wenn Pumpe/Ventil es melden
  // bzw. ein Heizkreis an ist und Ist < Soll – einen echten Durchfluss misst keine Anlage.
  _info(sys) {
    return sys.circuits.map((c) => {
      const t = this._a(c.ent.target);
      const mode = this._st(c.ent.mode)?.state;
      const soll = this._st(c.ent.target)?.state;
      const floor = has(t.kessel_temperatur);
      const flow = floor ? !!t.pumpe_ist : !OFF_MODES.has(mode) && Number(t.ist_temperatur) < Number(soll);
      const rooms = c.rooms.map((r) => {
        const rt = this._a(r.ent.target);
        const zone = rt.ventile_offen !== undefined && rt.ventile_offen !== null;
        return { ent: r.ent, name: r.name, t: rt, zone, mode: this._st(r.ent.mode)?.state, soll: this._st(r.ent.target)?.state,
          ist: rt.ist_temperatur, problem: rt.problem, flow: zone ? !!t.pumpe_ist && rt.ventile_offen : flow && rt.waermebedarf !== false };
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

  _step(id, dir) {
    const st = this._st(id);
    if (!st) return;
    const a = st.attributes, step = Number(a.step) || 0.5;
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

  _slider(id, label) {
    const st = this._st(id);
    if (!st) return "";
    const a = st.attributes;
    return `<label class="slider"><span>${esc(label)}</span>
      <input type="range" data-number="${id}" min="${a.min}" max="${a.max}" step="${a.step}" value="${st.state}">
      <b data-out="${id}">${fmt(st.state)} °C</b></label>`;
  }

  // Drehregler wie die HA-Thermostat-Karte: Bogen = Ist, Knopf = Komfort (ziehbar), Mitte = Komfort groß.
  _dial(ist, comfortId, tone) {
    const st = this._st(comfortId);
    const a = st?.attributes || {}, lo = Number(a.min ?? 16), hi = Number(a.max ?? 26);
    const f = (v) => Math.max(0, Math.min(1, (Number(v) - lo) / (hi - lo)));
    const C = 2 * Math.PI * 40, arc = C * 0.75;
    const knob = (v) => { const r = (135 + 270 * f(v)) * (Math.PI / 180); return [50 + 40 * Math.cos(r), 50 + 40 * Math.sin(r)]; };
    const [kx, ky] = st ? knob(st.state) : [0, 0];
    return `<svg class="ring ${tone} ${st ? "dial" : ""}" viewBox="0 0 100 100" ${st ? `data-dial="${comfortId}" data-lo="${lo}" data-hi="${hi}" data-step="${a.step || 0.5}"` : ""}
        role="${st ? "slider" : "img"}" ${st ? `tabindex="0"` : ""} aria-label="Komfort" aria-valuemin="${lo}" aria-valuemax="${hi}" aria-valuenow="${st?.state ?? ""}">
      <circle class="track" cx="50" cy="50" r="40" stroke-dasharray="${arc} ${C}" transform="rotate(135 50 50)"/>
      <circle class="val" cx="50" cy="50" r="40" stroke-dasharray="${has(ist) ? arc * f(ist) : 0} ${C}" transform="rotate(135 50 50)"/>
      ${st ? `<circle class="mark" cx="${kx}" cy="${ky}" r="6.5"/>` : ""}
      <text x="50" y="52" class="rv">${st ? fmt(st.state) + "°" : has(ist) ? fmt(ist) + "°" : "–"}</text>
      <text x="50" y="67" class="rs">${st ? `Ist ${fmt(ist)}°` : "Ist"}</text></svg>`;
  }

  _tile({ name, ist, soll, mode, problem, ent, note, iconSvg }) {
    const tone = this._tone(mode, problem);
    const comfort = this._st(ent.comfort);
    const presence = this._on(ent.presence);
    const now = has(soll) ? ` · jetzt ${fmt(soll)}°` : "";
    return `<div class="tile ${tone}">
      <div class="tname">${iconSvg || ""}<span>${esc(name)}</span>${presence ? '<span class="dot" title="Präsenz">●</span>' : ""}</div>
      ${this._dial(ist, ent.comfort, tone)}
      <div class="tmode">${esc((problem ? PROBLEMS[problem] || problem : MODES[mode] || mode || "–") + now)}</div>
      ${note ? `<div class="note">${esc(note)}</div>` : ""}
      ${comfort ? `<div class="stepper"><button data-step="${ent.comfort}" data-d="-1" aria-label="Komfort niedriger">−</button>
        <span>Komfort</span>
        <button data-step="${ent.comfort}" data-d="1" aria-label="Komfort höher">+</button></div>` : ""}
      ${ent.pre_heat ? `<button class="chip ${this._on(ent.pre_heat) ? "on" : ""}" data-toggle="${ent.pre_heat}">Vorheizen</button>` : ""}
    </div>`;
  }

  // ---- Schema: Kessel → Verteiler (Vorlauf/Rücklauf) → Pumpe → Heizkreis → Räume ----

  _schema(info, narrow, fuel) {
    if (!info.length) return "";
    const kessel = info.find((i) => i.floor)?.t.kessel_temperatur;
    const W = narrow ? 360 : 820;
    const L = narrow
      ? { rl: 22, vl: 36, pump: 62, box: [84, 344], room: [130, 344], branch: 106, valve: 118, step: 52 }
      : { rl: 178, vl: 194, pump: 232, box: [262, 470], room: [560, 804], branch: 500, valve: 530, step: 56 };
    let y = narrow ? 104 : 8;
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
    const boiler = narrow ? { x: 12, y: 12, w: 336, h: 64 } : { x: 16, y: Math.max(8, (top + bottom) / 2 - 60), w: 136, h: 120 };
    const H = Math.max(y, boiler.y + boiler.h) + 8;
    const pipe = (on, back, color, d, thin) => `<path class="pipe ${thin ? "thin" : ""} ${on ? "flow" : ""} ${back ? "back" : ""}" style="stroke:${on ? color : IDLE}" d="${d}"/>`;
    const barTop = boiler.y + boiler.h;
    const rlA = narrow ? barTop : Math.min(top + 6, boiler.y + 74), rlB = narrow ? bottom + 6 : Math.max(bottom + 6, boiler.y + 74);
    const vlA = narrow ? barTop : Math.min(top - 6, boiler.y + 46), vlB = narrow ? bottom - 6 : Math.max(bottom - 6, boiler.y + 46);
    // Rücklauf zuerst, Vorlauf mit Halo darüber: so bleiben Kreuzungen sauber lesbar
    let s = pipe(any, true, COLD, `M${L.rl} ${rlA}V${rlB}`);
    if (!narrow) s += pipe(any, true, COLD, `M${boiler.x + boiler.w} ${boiler.y + 74}H${L.rl}`);
    for (const r of rows) s += pipe(r.flow, true, COLD, `M${L.rl} ${r.cy + 6}H${L.box[0]}`);
    s += `<path class="halo" d="M${L.vl} ${vlA}V${vlB}"/>` + pipe(any, false, HOT, `M${L.vl} ${vlA}V${vlB}`);
    if (!narrow) s += `<path class="halo" d="M${boiler.x + boiler.w} ${boiler.y + 46}H${L.vl}"/>` + pipe(any, false, HOT, `M${boiler.x + boiler.w} ${boiler.y + 46}H${L.vl}`);
    for (const r of rows) {
      const [bx, bx2] = L.box;
      const sub = r.floor ? `Pumpe ${r.t.pumpe_ist ? "läuft" : "aus"}${r.t.pumpe_soll !== r.t.pumpe_ist && r.t.pumpe_soll != null ? ` · würde ${r.t.pumpe_soll ? "ein" : "aus"}schalten` : ""}` : `${fmt(r.ist)} → ${fmt(r.soll)} °C`;
      s += pipe(r.flow, false, HOT, `M${L.vl} ${r.cy - 6}H${bx}`) + I.pump(L.pump, r.cy - 6, r.flow);
      s += `<rect class="box ${r.flow ? "hot" : ""} ${r.problem ? "warnbox" : ""}" x="${bx}" y="${r.cy - 24}" width="${bx2 - bx}" height="48" rx="12"/>
        <text class="t" x="${bx + 14}" y="${r.cy - 4}">${esc(r.name)}</text>
        <text class="s" x="${bx + 14}" y="${r.cy + 14}">${esc(sub)}</text>`;
      for (const z of r.rooms) {
        const d = narrow ? `M${L.branch} ${r.cy + 24}V${z.y - 8}Q${L.branch} ${z.y} ${L.branch + 8} ${z.y}H${L.room[0]}` : elbow(bx2, r.cy, L.branch, L.room[0], z.y);
        const [rx, rx2] = L.room;
        const info2 = z.problem ? PROBLEMS[z.problem] || z.problem : `${fmt(z.ist)} → ${fmt(z.soll)} °C`;
        const extra = z.zone ? (z.t.ventile_offen ? " · Ventil offen" : " · Ventil zu") : has(z.t.trv_sollwert) ? ` · TRV ${fmt(z.t.trv_sollwert)}` : "";
        s += pipe(z.flow, false, HOT, d, true) + (z.zone ? I.valve : I.trv)(L.valve, z.y, z.flow);
        s += `<rect class="box ${z.flow ? "hot" : ""} ${z.problem ? "warnbox" : ""}" x="${rx}" y="${z.y - 21}" width="${rx2 - rx}" height="42" rx="10"/>
          ${z.zone ? I.floor(rx + 20, z.y, z.flow) : I.radiator(rx + 20, z.y, z.flow)}
          <text class="t sm" x="${rx + 40}" y="${z.y - 3}">${esc(z.name)}</text>
          <text class="s" x="${rx + 40}" y="${z.y + 13}">${esc(info2 + extra)}</text>
          ${z.problem ? I.warn(rx2 - 16, z.y) : ""}`;
      }
    }
    const bx = narrow ? boiler.x + 18 : boiler.x + boiler.w / 2;
    // Pelletlager: die Kessel-Box füllt sich von unten wie ein Tank (Stand / Maximum der Anlage)
    const kg = fuel?.state, max = fuel?.attributes?.max_kg;
    const p = has(kg) && has(max) && Number(max) > 0 ? Math.max(0, Math.min(1, Number(kg) / Number(max))) : null;
    const clip = `hc-tank-${(this._clipN = (this._clipN || 0) + 1)}`;
    const tank = p === null ? "" : `<clipPath id="${clip}"><rect x="${boiler.x}" y="${boiler.y}" width="${boiler.w}" height="${boiler.h}" rx="14"/></clipPath>
      <rect class="tankfill ${p < 0.15 ? "low" : ""}" clip-path="url(#${clip})" x="${boiler.x}" y="${boiler.y + boiler.h * (1 - p)}" width="${boiler.w}" height="${boiler.h * p}"/>`;
    const label = has(kg) ? `${narrow ? "Pellets " : ""}${Math.round(Number(kg)).toLocaleString("de-AT")} kg${p !== null ? ` · ${Math.round(p * 100)} %` : ""}` : "";
    const pellets = label ? `<text class="t sm ${narrow ? "end" : "mid"}" x="${narrow ? boiler.x + boiler.w - 16 : bx}" y="${narrow ? boiler.y + 38 : boiler.y + 96}">${label}</text>` : "";
    s = `<rect class="box boiler" x="${boiler.x}" y="${boiler.y}" width="${boiler.w}" height="${boiler.h}" rx="14"/>${tank}
      <text class="s ${narrow ? "" : "mid"}" x="${bx}" y="${narrow ? boiler.y + 24 : boiler.y + 34}">${fuel ? "Pelletkessel" : "Wärmeerzeuger"}</text>
      <text class="big ${narrow ? "" : "mid"}" x="${bx}" y="${narrow ? boiler.y + 48 : boiler.y + 64}">${has(kessel) ? fmt(kessel, 0) + " °C" : "–"}</text>
      ${pellets}` + s;
    return `<svg class="schema ${narrow ? "" : "wide"}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Anlagenschema">${s}</svg>`;
  }

  _legend() {
    return `<div class="legend">
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
      : `Anlage meldet ${fmt(t.anlage_sollwert)} °C · ${DECISIONS[t.entscheidung] || t.entscheidung || ""}${has(t.schreib_budget_rest) ? ` · Budget ${t.schreib_budget_rest}` : ""}`;
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
    for (const z of i.rooms) {
      tiles.push(this._tile({ ...z, note: z.zone ? `Ventil ${z.t.ventile_offen ? "offen" : "zu"}` : has(z.t.trv_sollwert) ? `Thermostat ${fmt(z.t.trv_sollwert)}°` : "", iconSvg: icon(z.zone ? I.floor : I.radiator, z.flow) }));
    }
    return `<section class="group">
      <div class="ghead"><h2>${esc(i.name)}</h2>${this._badge(i.mode, i.problem)}</div>
      <div class="gmeta">${esc(meta)}</div>
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
          <button class="${writing ? "on" : ""}" data-toggle="${s.write_enabled}" aria-pressed="${writing}">Schreiben</button>
          <button class="${this._on(s.away) ? "on" : ""}" data-toggle="${s.away}" aria-pressed="${this._on(s.away)}">Abwesend</button>
          <button class="${this._on(s.guest) ? "on" : ""}" data-toggle="${s.guest}" aria-pressed="${this._on(s.guest)}">Gast</button>
        </div>
      </div>
      ${problems.length ? `<div class="alert">${icon(I.warn, false, 20, 20)}<span>${problems.map((p) => esc(p.replace(/: (\w+)$/, (m, k) => " – " + (PROBLEMS[k] || k)))).join("<br>")}</span></div>` : ""}
      <section class="card"><div class="cardhead"><h2>Anlage</h2></div>${this._schema(info, this._narrow, this._st(s.fuel))}${this._legend()}</section>
      ${info.map((i) => this._circuitGroup(i)).join("")}
      <section class="card"><h2>Grundwerte</h2>${this._slider(s.eco, "Eco")}${this._slider(s.away_temp, "Abwesend")}</section>
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
    this.shadowRoot.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => this._step(b.dataset.step, Number(b.dataset.d))));
    this.shadowRoot.querySelectorAll("[data-dial]").forEach((svg) => this._wireDial(svg));
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
  .page { max-width: 1100px; margin: 0 auto; padding: 0 16px 32px; font-family: var(--paper-font-body1_-_font-family, system-ui); }
  .top { display:flex; align-items:center; gap:8px; height:56px; font-size:20px; font-weight: 500; }
  h1 { font-size: 26px; font-weight: 600; margin: 4px 0 12px; } h2 { font-size: 16px; font-weight: 600; margin: 0; }
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
  .schema .tankfill { fill: #c8a165; opacity: .45; } .schema .tankfill.low { fill: ${WARN}; }
  .schema .boiler { fill: ${HOT}12; stroke: ${HOT}66; }
  .schema text { text-anchor: start; } .schema .mid { text-anchor: middle; } .schema .end { text-anchor: end; }
  .schema .t { font-size: 14px; font-weight: 600; fill: var(--primary-text-color); } .schema .t.sm { font-size: 13px; }
  .schema .s { font-size: 12px; fill: var(--secondary-text-color); }
  .schema .big { font-size: 20px; font-weight: 600; fill: var(--primary-text-color); }
  .schema .pipe { fill: none; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; } .schema .pipe.thin { stroke-width: 2.2; }
  .schema .pipe.flow { stroke-dasharray: 7 6; animation: flow 1s linear infinite; } .schema .pipe.flow.back { animation-direction: reverse; }
  .schema .halo { fill: none; stroke: var(--card-background-color); stroke-width: 8; }
  @keyframes flow { to { stroke-dashoffset: -13; } }
  @media (prefers-reduced-motion: reduce) { .schema .pipe.flow { animation: none; } }
  .pump circle { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.6; } .pump path { fill: ${IDLE}; }
  .pump.on circle { stroke: ${HOT}; } .pump.on path { fill: ${HOT}; }
  .valve rect { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.5; } .valve.open rect { stroke: ${HOT}; }
  .valve path { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.8; stroke-linejoin: round; } .valve.open path { fill: ${HOT}; stroke: ${HOT}; }
  .rad rect { fill: var(--card-background-color); } .rad rect, .rad path { stroke: ${IDLE}; stroke-width: 1.8; } .rad path { fill: none; }
  .rad.on rect, .rad.on path { stroke: ${HOT}; } .rad.on rect { fill: ${HOT}22; }
  .legend { display:flex; flex-wrap:wrap; gap: 6px 16px; margin-top: 12px; font-size: 12px; color: var(--secondary-text-color); align-items:center; }
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
  .chip { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); border-radius: 999px; padding: 5px 12px; font-size: 13px; margin-top: 4px; }
  .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .slider { display:grid; grid-template-columns: 90px 1fr 70px; align-items:center; gap:8px; font-size: 14px; margin: 8px 0; }
  .slider input { width: 100%; accent-color: var(--primary-color); }
  .slider b { text-align: right; }
  @media (max-width: 600px) { .tiles { grid-template-columns: repeat(2, 1fr); gap: 10px; } .ring { width: 104px; height: 104px; } .seg button { padding: 8px 11px; } }
  button:not(:disabled), [role="button"], summary, label:has(input:not(:disabled)), input[type="range"]:not(:disabled) { cursor: pointer; }
  :disabled { cursor: not-allowed; }
`;

customElements.define("heating-core-panel", HeatingCorePanel);
