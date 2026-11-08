// PROTOTYP – wegwerfen. Drei Entwürfe der Seite „Heizung“ (HEATING-9/10), umschaltbar über window.__variant = A | B | C.
// Läuft nur im Screenshot-Harness (tests/ui/build.mjs), nicht in Home Assistant.

const HOT = "#f4511e", COLD = "#1e88e5", IDLE = "#9aa5b1", WARN = "#f5a623";
const de = (v, d = 1) => (v === null || v === undefined || v === "" || isNaN(Number(v)) ? "–" : Number(v).toLocaleString("de-AT", { minimumFractionDigits: d, maximumFractionDigits: d }));
const OFF_MODES = new Set(["circuit_off", "summer", "away", "window", "unavailable"]);
const floorOf = (name) => (/\bOG\b/.test(name) ? "OG" : /\bUG\b/.test(name) ? "UG" : "EG");

// ---- Symbole -------------------------------------------------------------
const I = {
  flame: (x, y, s = 1) => `<g transform="translate(${x} ${y}) scale(${s})"><path fill="${HOT}" d="M0-14C7-7 10 0 6 7 4 11-4 11-6 7-9 1-4-3 0-14Z"/><path fill="#ffd54f" d="M0-2C3 1 4 4 2 7 1 8-1 8-2 7-4 4-2 2 0-2Z"/></g>`,
  pump: (x, y, on) => `<g class="pump ${on ? "on" : ""}" transform="translate(${x} ${y})"><circle r="11"/><path d="M-5-6 7 0-5 6Z"/></g>`,
  valve: (x, y, open, vertical) => `<g class="valve ${open ? "open" : ""}" transform="translate(${x} ${y})${vertical ? " rotate(90)" : ""}"><path d="M-7-6 7 6V-6L-7 6Z"/></g>`,
  radiator: (x, y, on) => `<g class="rad ${on ? "on" : ""}" transform="translate(${x} ${y})"><rect x="-10" y="-8" width="20" height="16" rx="2"/><path d="M-5-8v16M0-8v16M5-8v16"/></g>`,
  floor: (x, y, on) => `<g class="rad ${on ? "on" : ""}" transform="translate(${x} ${y})"><path fill="none" d="M-10-7H7a2.5 2.5 0 0 1 0 5H-7a2.5 2.5 0 0 0 0 5H7a2.5 2.5 0 0 1 0 5H-10"/></g>`,
  warn: (x, y) => `<g transform="translate(${x} ${y})"><path fill="${WARN}" d="M0-8 8 7H-8Z"/><path stroke="#000" stroke-width="1.6" d="M0-3v5M0 4.5v.5"/></g>`,
};
const elbow = (x1, y1, xm, x2, y2) => {
  if (Math.abs(y2 - y1) < 1) return `M${x1} ${y1}H${x2}`;
  const r = Math.min(8, Math.abs(y2 - y1) / 2), s = y2 > y1 ? 1 : -1;
  return `M${x1} ${y1}H${xm - r}Q${xm} ${y1} ${xm} ${y1 + s * r}V${y2 - s * r}Q${xm} ${y2} ${xm + r} ${y2}H${x2}`;
};

class HeatingCorePrototype extends HeatingCorePanel {
  // ---- gemeinsames Datenmodell für alle Entwürfe ---------------------------
  _info(sys) {
    return sys.circuits.map((c) => {
      const t = this._a(c.ent.target);
      const mode = this._st(c.ent.mode)?.state;
      const soll = this._st(c.ent.target)?.state;
      const floor = t.kessel_temperatur !== undefined && t.kessel_temperatur !== null;
      const flow = floor ? !!t.pumpe_ist : !OFF_MODES.has(mode) && Number(t.ist_temperatur) < Number(soll);
      const rooms = c.rooms.map((r) => {
        const rt = this._a(r.ent.target);
        const zone = rt.ventile_offen !== undefined && rt.ventile_offen !== null;
        return { r, name: r.name, t: rt, zone, mode: this._st(r.ent.mode)?.state, soll: this._st(r.ent.target)?.state, ist: rt.ist_temperatur,
          flow: zone ? !!t.pumpe_ist && rt.ventile_offen : flow && rt.waermebedarf !== false, problem: rt.problem };
      });
      return { c, name: c.name, t, mode, soll, ist: t.ist_temperatur, floor, flow, rooms, problem: t.problem };
    });
  }
  _tone(mode, problem) {
    if (problem) return "warn";
    if (HEATING.has(mode)) return "hot";
    if (mode === "eco" || mode === "floor_idle") return "eco";
    return "off";
  }
  _badge(mode, problem) {
    return `<span class="badge ${this._tone(mode, problem)}">${esc(problem ? PROBLEMS[problem] || problem : MODES[mode] || mode || "–")}</span>`;
  }
  _sub(i) {
    if (i.floor) return `Pumpe ${i.t.pumpe_ist ? "läuft" : "aus"}${i.t.pumpe_soll !== i.t.pumpe_ist ? ` · würde ${i.t.pumpe_soll ? "einschalten" : "ausschalten"}` : ""}`;
    return `${de(i.ist)} → ${de(i.soll)} °C`;
  }

  // ---- Schema (A und B): Kessel → Verteiler → Pumpe → Heizkreis → Räume ----
  _schemaSvg(sys, narrow) {
    const info = this._info(sys);
    const kessel = info.find((i) => i.floor)?.t.kessel_temperatur;
    const W = narrow ? 360 : 820;
    const L = narrow
      ? { rl: 22, vl: 36, pump: 62, box: [84, 344], room: [130, 344], branch: 106, valve: 118, roomStep: 52 }
      : { rl: 178, vl: 194, pump: 232, box: [262, 470], room: [560, 804], branch: 500, valve: 530, roomStep: 56 };
    let y = narrow ? 104 : 8;
    const rows = info.map((i) => {
      const n = i.rooms.length;
      let cy, rooms;
      if (narrow) {
        cy = y + 24;
        rooms = i.rooms.map((r, k) => ({ ...r, y: cy + 58 + k * L.roomStep }));
        y = cy + 30 + (n ? n * L.roomStep + 18 : 18);
      } else {
        const h = Math.max(1, n) * L.roomStep + 20;
        cy = y + h / 2;
        rooms = i.rooms.map((r, k) => ({ ...r, y: cy - ((n - 1) * L.roomStep) / 2 + k * L.roomStep }));
        y += h;
      }
      return { ...i, cy, rooms };
    });
    const H = y + (narrow ? 4 : 10);
    const top = rows[0].cy, bottom = rows[rows.length - 1].cy;
    const any = rows.some((r) => r.flow);
    const boiler = narrow ? { x: 12, y: 12, w: 336, h: 64 } : { x: 16, y: (top + bottom) / 2 - 60, w: 136, h: 120 };
    const vlc = any ? HOT : IDLE, rlc = any ? COLD : IDLE;
    let s = "";
    // Rücklauf-Schiene und -Abzweige zuerst, Vorlauf mit Halo darüber (saubere Kreuzungen)
    const barTop = narrow ? boiler.y + boiler.h : top + 6;
    const rlA = narrow ? barTop : Math.min(top + 6, boiler.y + 74), rlB = narrow ? bottom + 6 : Math.max(bottom + 6, boiler.y + 74);
    const vlA = narrow ? barTop : Math.min(top - 6, boiler.y + 46), vlB = narrow ? bottom - 6 : Math.max(bottom - 6, boiler.y + 46);
    s += `<path class="pipe ${any ? "flow back" : ""}" style="stroke:${rlc}" d="M${L.rl} ${rlA}V${rlB}"/>`;
    if (!narrow) s += `<path class="pipe ${any ? "flow back" : ""}" style="stroke:${rlc}" d="M${boiler.x + boiler.w} ${boiler.y + 74}H${L.rl}"/>`;
    for (const r of rows) s += `<path class="pipe ${r.flow ? "flow back" : ""}" style="stroke:${r.flow ? COLD : IDLE}" d="M${L.rl} ${r.cy + 6}H${L.box[0]}"/>`;
    s += `<path class="halo" d="M${L.vl} ${vlA}V${vlB}"/><path class="pipe ${any ? "flow" : ""}" style="stroke:${vlc}" d="M${L.vl} ${vlA}V${vlB}"/>`;
    if (!narrow) s += `<path class="halo" d="M${boiler.x + boiler.w} ${boiler.y + 46}H${L.vl}"/><path class="pipe ${any ? "flow" : ""}" style="stroke:${vlc}" d="M${boiler.x + boiler.w} ${boiler.y + 46}H${L.vl}"/>`;
    for (const r of rows) {
      s += `<path class="pipe ${r.flow ? "flow" : ""}" style="stroke:${r.flow ? HOT : IDLE}" d="M${L.vl} ${r.cy - 6}H${L.box[0]}"/>${I.pump(L.pump, r.cy - 6, r.flow)}`;
      const [bx, bx2] = L.box;
      s += `<rect class="box ${r.flow ? "hot" : ""} ${r.problem ? "warnbox" : ""}" x="${bx}" y="${r.cy - 24}" width="${bx2 - bx}" height="48" rx="12"/>
        <text class="t" x="${bx + 14}" y="${r.cy - 4}">${esc(r.name)}</text>
        <text class="s" x="${bx + 14}" y="${r.cy + 14}">${esc(this._sub(r))}</text>`;
      for (const z of r.rooms) {
        const c = z.flow ? HOT : IDLE;
        const path = narrow ? `M${L.branch} ${r.cy + 24}V${z.y - 8}Q${L.branch} ${z.y} ${L.branch + 8} ${z.y}H${L.room[0]}` : elbow(bx2, r.cy, L.branch, L.room[0], z.y);
        s += `<path class="pipe thin ${z.flow ? "flow" : ""}" style="stroke:${c}" d="${path}"/>`;
        s += z.zone ? I.valve(L.valve, z.y, z.flow) : I.radiator(L.valve, z.y, z.flow);
        const [rx, rx2] = L.room;
        s += `<rect class="box room ${z.flow ? "hot" : ""} ${z.problem ? "warnbox" : ""}" x="${rx}" y="${z.y - 21}" width="${rx2 - rx}" height="42" rx="10"/>
          ${z.zone ? I.floor(rx + 20, z.y, z.flow) : I.radiator(rx + 20, z.y, z.flow)}
          <text class="t sm" x="${rx + 40}" y="${z.y - 3}">${esc(z.name)}</text>
          <text class="s" x="${rx + 40}" y="${z.y + 13}">${z.problem ? esc(PROBLEMS[z.problem] || z.problem) : `${de(z.ist)} → ${de(z.soll)} °C`}${z.zone ? (z.t.ventile_offen ? " · Ventil offen" : " · Ventil zu") : z.t.trv_sollwert != null ? ` · TRV ${de(z.t.trv_sollwert)}` : ""}</text>
          ${z.problem ? I.warn(rx2 - 16, z.y) : ""}`;
      }
    }
    s = `<rect class="box boiler" x="${boiler.x}" y="${boiler.y}" width="${boiler.w}" height="${boiler.h}" rx="14"/>
      ${narrow ? I.flame(boiler.x + 28, boiler.y + 33, 1.2) : I.flame(boiler.x + boiler.w / 2, boiler.y + 30, 1.4)}
      <text class="t ${narrow ? "" : "mid"}" x="${narrow ? boiler.x + 54 : boiler.x + boiler.w / 2}" y="${narrow ? boiler.y + 28 : boiler.y + 66}">Pelletkessel</text>
      <text class="big ${narrow ? "" : "mid"}" x="${narrow ? boiler.x + 54 : boiler.x + boiler.w / 2}" y="${narrow ? boiler.y + 50 : boiler.y + 96}">${kessel != null ? de(kessel, 0) + " °C" : "–"}</text>` + s;
    return `<svg class="schema" viewBox="0 0 ${W} ${H}" width="100%">${s}</svg>`;
  }

  _legend() {
    return `<div class="legend">
      <span><i class="ln" style="background:${HOT}"></i>Vorlauf warm</span>
      <span><i class="ln" style="background:${COLD}"></i>Rücklauf</span>
      <span><i class="ln" style="background:${IDLE}"></i>steht</span>
      <span><svg width="24" height="24" viewBox="-12 -12 24 24">${I.pump(0, 0, true)}</svg>Pumpe läuft</span>
      <span><svg width="22" height="18" viewBox="-11 -9 22 18">${I.valve(0, 0, true)}</svg>Ventil offen</span>
      <span><svg width="22" height="18" viewBox="-11 -9 22 18">${I.valve(0, 0, false)}</svg>zu</span>
      <span><svg width="24" height="20" viewBox="-12 -10 24 20">${I.radiator(0, 0, true)}</svg>Thermostat</span>
    </div>`;
  }

  _statusBar(sys) {
    const s = sys.ent, writing = this._on(s.write_enabled);
    const problems = this._a(s.problem).probleme || [];
    return `<div class="status ${writing ? "live" : "shadow"}">
        <div class="stxt"><b>${writing ? "Steuert aktiv" : "Schattenbetrieb"}</b><small>${writing ? "Heating Core schaltet die Anlage." : "Rechnet mit, schaltet aber nichts."}</small></div>
        <div class="seg">
          <button class="${writing ? "on" : ""}" data-toggle="${s.write_enabled}">Schreiben</button>
          <button class="${this._on(s.away) ? "on" : ""}" data-toggle="${s.away}">Abwesend</button>
          <button class="${this._on(s.guest) ? "on" : ""}" data-toggle="${s.guest}">Gast</button>
        </div>
      </div>
      ${problems.length ? `<div class="alert">${I.warn ? `<svg width="20" height="20" viewBox="-10 -10 20 20">${I.warn(0, 1)}</svg>` : ""}<span>${problems.map((p) => esc(p.replace(/: (\w+)$/, (m, k) => " – " + (PROBLEMS[k] || k)))).join("<br>")}</span></div>` : ""}`;
  }

  // ---- Entwurf A: Anlage zuerst --------------------------------------------
  _variantA(sys) {
    const info = this._info(sys);
    return `<div class="headrow"><h1>${esc(sys.name)}</h1></div>
      ${this._statusBar(sys)}
      <section class="card"><div class="cardhead"><h2>Anlage</h2><span class="muted small">live</span></div>
        ${this._schemaSvg(sys, this._narrow)}${this._legend()}</section>
      <h2 class="sect">Heizkreise</h2>
      <div class="list">${info.map((i) => `<section class="card circ ${this._tone(i.mode, i.problem)}">
        <div class="cardhead"><div><h2>${esc(i.name)}</h2><div class="small muted">${esc(i.floor ? `Kessel ${de(i.t.kessel_temperatur, 0)} °C · Freigabe ${i.t.kessel_freigabe ? "ja" : "nein"}` : `Anlage meldet ${de(i.t.anlage_sollwert)} °C · ${DECISIONS[i.t.entscheidung] || ""}`)}</div></div>${this._badge(i.mode, i.problem)}</div>
        ${i.floor ? `<div class="kv"><span>Pumpe</span><b>${i.t.pumpe_ist ? "läuft" : "aus"}</b><span>Soll</span><b>${i.t.pumpe_soll ? "läuft" : "aus"}</b></div>
          ${(i.t.wuerde_schalten || []).length ? `<div class="would">Würde schalten: ${i.t.wuerde_schalten.map((w) => esc(w.replace("switch.", ""))).join(", ")}</div>` : ""}`
          : `<div class="temps"><div><small>Ist</small><b>${de(i.ist)}°</b></div><div class="arrow">→</div><div><small>Soll</small><b>${de(i.soll)}°</b></div></div>`}
        ${this._slider(i.c.ent.comfort, "Komfort")}
        ${i.rooms.map((z) => `<div class="roomrow"><div class="ricon">${`<svg width="26" height="22" viewBox="-13 -11 26 22">${z.zone ? I.floor(0, 0, z.flow) : I.radiator(0, 0, z.flow)}</svg>`}</div>
          <div class="rname"><b>${esc(z.name)}</b><small>${z.problem ? esc(PROBLEMS[z.problem]) : `${de(z.ist)} → ${de(z.soll)} °C`}</small></div>${this._badge(z.mode, z.problem)}</div>`).join("")}
      </section>`).join("")}</div>
      <section class="card"><h2>Grundwerte</h2>${this._slider(sys.ent.eco, "Eco")}${this._slider(sys.ent.away_temp, "Abwesend")}</section>`;
  }

  // ---- Entwurf B: Räume zuerst (Kacheln mit Ring) --------------------------
  _ring(ist, soll, tone) {
    const lo = 14, hi = 28, f = (v) => Math.max(0, Math.min(1, (Number(v) - lo) / (hi - lo)));
    const C = 2 * Math.PI * 40, arc = C * 0.75;
    const p = isNaN(Number(ist)) ? 0 : f(ist);
    const sa = (-225 + 270 * f(soll)) * (Math.PI / 180);
    return `<svg class="ring ${tone}" viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="40" stroke-dasharray="${arc} ${C}" transform="rotate(135 50 50)"/>
      <circle class="val" cx="50" cy="50" r="40" stroke-dasharray="${arc * p} ${C}" transform="rotate(135 50 50)"/>
      ${isNaN(Number(soll)) ? "" : `<circle class="mark" cx="${50 + 40 * Math.cos(sa)}" cy="${50 + 40 * Math.sin(sa)}" r="5"/>`}
      <text x="50" y="52" class="rv">${de(ist)}°</text><text x="50" y="68" class="rs">Soll ${de(soll)}°</text></svg>`;
  }
  _tile(name, ist, soll, mode, problem, comfortId, extra) {
    const tone = this._tone(mode, problem);
    const st = this._st(comfortId);
    return `<div class="tile ${tone}"><div class="tname">${esc(name)}</div>${this._ring(ist, soll, tone)}
      <div class="tmode">${esc(problem ? PROBLEMS[problem] || problem : MODES[mode] || mode || "–")}</div>
      ${extra ? `<div class="small muted center">${extra}</div>` : ""}
      ${st ? `<div class="stepper"><button data-step="${comfortId}" data-d="-1">−</button><span>Komfort <b>${de(st.state)}°</b></span><button data-step="${comfortId}" data-d="1">+</button></div>` : ""}</div>`;
  }
  _variantB(sys) {
    const info = this._info(sys);
    const strip = (i) => `<span class="strip">${i.flow ? "🔥" : "○"} ${i.floor ? (i.t.pumpe_ist ? "Pumpe läuft" : "Pumpe aus") : i.flow ? "heizt" : "steht"}</span>`;
    return `<div class="headrow"><h1>${esc(sys.name)}</h1></div>${this._statusBar(sys)}
      ${info.map((i) => `<div class="group"><div class="ghead"><h2>${esc(i.name)}</h2>${strip(i)}</div>
        <div class="tiles">
          ${i.floor ? `<div class="tile info"><div class="tname">Kessel & Pumpe</div><div class="bigtemp">${de(i.t.kessel_temperatur, 0)}°</div><div class="tmode">Kessel · Freigabe ${i.t.kessel_freigabe ? "ja" : "nein"}</div>
              <div class="small muted center">Pumpe ${i.t.pumpe_ist ? "läuft" : "aus"}${i.t.pumpe_soll !== i.t.pumpe_ist ? ` – würde ${i.t.pumpe_soll ? "ein" : "aus"}schalten` : ""}</div></div>`
            : this._tile(i.rooms.length ? "Ganzer Kreis" : i.name.replace(/^HK\d\s*/, ""), i.ist, i.soll, i.mode, i.problem, i.c.ent.comfort, `Anlage meldet ${de(i.t.anlage_sollwert)}°`)}
          ${i.rooms.map((z) => this._tile(z.name, z.ist, z.soll, z.mode, z.problem, z.r.ent.comfort, z.zone ? `Ventil ${z.t.ventile_offen ? "offen" : "zu"}` : `Thermostat ${de(z.t.trv_sollwert)}°`)).join("")}
        </div></div>`).join("")}
      <details class="card"><summary><h2>Anlagenschema</h2></summary>${this._schemaSvg(sys, true)}${this._legend()}</details>
      <section class="card"><h2>Grundwerte</h2>${this._slider(sys.ent.eco, "Eco")}${this._slider(sys.ent.away_temp, "Abwesend")}</section>`;
  }

  // ---- Entwurf C: Haus im Schnitt ------------------------------------------
  _house(sys, narrow) {
    const info = this._info(sys);
    const W = narrow ? 380 : 760, floors = ["OG", "UG"], fh = 128, roofH = 56, kh = 104;
    const nC = info.length, rx0 = 24 + nC * 16 + 18;
    const kessel = info.find((i) => i.floor)?.t.kessel_temperatur;
    const fy = (f) => roofH + floors.indexOf(f) * fh;
    const kTop = roofH + floors.length * fh;
    let s = `<path class="house" d="M8 ${roofH}L${W / 2} 8 ${W - 8} ${roofH}Z"/>`;
    floors.forEach((f) => (s += `<rect class="floorband" x="8" y="${fy(f)}" width="${W - 16}" height="${fh}"/><text class="fl" x="${W - 18}" y="${fy(f) + 18}">${f}</text>`));
    s += `<rect class="floorband cellar" x="8" y="${kTop}" width="${W - 16}" height="${kh}"/><text class="fl" x="${W - 18}" y="${kTop + 18}">Keller</text>`;
    // Räume je Geschoss sammeln (Heizkreis ohne Räume steht für sich)
    const items = { OG: [], UG: [] };
    info.forEach((i, k) => {
      if (!i.rooms.length) items[floorOf(i.name) === "EG" ? "UG" : floorOf(i.name)].push({ k, name: i.name.replace(/^HK\d\s*/, ""), ist: i.ist, soll: i.soll, flow: i.flow, zone: false, mode: i.mode, problem: i.problem, circ: true });
      i.rooms.forEach((z) => items[floorOf(z.name) === "EG" ? "UG" : floorOf(z.name)].push({ k, ...z }));
    });
    const reach = info.map(() => ({ top: Infinity, xEnd: 0 }));
    let rooms = "", lines = "";
    for (const f of floors) {
      const list = items[f], n = Math.max(1, list.length), gap = 10, bw = (W - 16 - rx0 - gap * (n - 1)) / n;
      list.forEach((z, j) => {
        const x = rx0 + j * (bw + gap), y = fy(f) + 26, ly = fy(f) + fh - 14 - z.k * 6, cx = x + bw / 2;
        const tone = this._tone(z.mode, z.problem);
        rooms += `<rect class="box room ${z.flow ? "hot" : ""} ${z.problem ? "warnbox" : ""}" x="${x}" y="${y}" width="${bw}" height="58" rx="10"/>
          <text class="t sm mid" x="${cx}" y="${y + 20}">${esc(z.name)}</text>
          <text class="big mid ${tone}" x="${cx}" y="${y + 44}">${z.problem ? "?" : de(z.ist) + "°"}</text>`;
        lines += `<path class="pipe thin ${z.flow ? "flow" : ""}" style="stroke:${z.flow ? HOT : IDLE}" d="M${cx} ${ly}V${y + 58}"/>` + (z.zone ? I.valve(cx, ly - 12, z.flow, true) : I.radiator(cx, ly - 13, z.flow));
        const r = reach[z.k]; r.top = Math.min(r.top, ly); r.xEnd = Math.max(r.xEnd, cx);
        r.ys = [...(r.ys || []), ly];
      });
    }
    // Steigleitungen vom Kessel in die Geschosse
    let risers = "";
    info.forEach((i, k) => {
      const x = 24 + k * 16, r = reach[k], c = i.flow ? HOT : IDLE;
      if (r.top === Infinity) return;
      risers += `<path class="halo" d="M${x} ${kTop + 34}V${r.top}"/><path class="pipe ${i.flow ? "flow" : ""}" style="stroke:${c}" d="M${x} ${kTop + 34}V${r.top}"/>`;
      for (const ly of new Set(r.ys)) risers += `<path class="pipe ${i.flow ? "flow" : ""}" style="stroke:${c}" d="M${x} ${ly}H${r.xEnd}"/>`;
      risers += I.pump(x, kTop + 46 + (k % 2) * 0, i.flow).replace("<circle r=\"11\"", "<circle r=\"7\"").replace("M-5-6 7 0-5 6Z", "M-3-4 5 0-3 4Z");
    });
    s += risers + lines + rooms;
    s += `<rect class="box boiler" x="16" y="${kTop + 56}" width="${Math.max(120, nC * 16 + 90)}" height="40" rx="10"/>${I.flame(36, kTop + 76)}
      <text class="t sm" x="54" y="${kTop + 74}">Pelletkessel</text><text class="s" x="54" y="${kTop + 89}">${kessel != null ? de(kessel, 0) + " °C" : ""}</text>`;
    return `<svg class="schema" viewBox="0 0 ${W} ${kTop + kh + 6}" width="100%">${s}</svg>`;
  }
  _variantC(sys) {
    const info = this._info(sys);
    const row = (name, sub, mode, problem, comfortId, icon) => `<details class="lrow"><summary>${icon}<div class="rname"><b>${esc(name)}</b><small>${esc(sub)}</small></div>${this._badge(mode, problem)}</summary>${this._slider(comfortId, "Komfort")}</details>`;
    return `<div class="headrow"><h1>${esc(sys.name)}</h1></div>${this._statusBar(sys)}
      <div class="split"><section class="card">${this._house(sys, this._narrow)}${this._legend()}</section>
      <div><section class="card">${info.map((i) => `<div class="lgroup"><div class="lghead">${esc(i.name)}<span class="small muted">${esc(this._sub(i))}</span></div>
        ${i.floor ? "" : row("Heizkreis", `${de(i.ist)} → ${de(i.soll)} °C`, i.mode, i.problem, i.c.ent.comfort, `<svg width="26" height="22" viewBox="-13 -11 26 22">${I.pump(0, 0, i.flow).replace('r="11"', 'r="9"')}</svg>`)}
        ${i.rooms.map((z) => row(z.name, z.problem ? PROBLEMS[z.problem] : `${de(z.ist)} → ${de(z.soll)} °C`, z.mode, z.problem, z.r.ent.comfort, `<svg width="26" height="22" viewBox="-13 -11 26 22">${z.zone ? I.floor(0, 0, z.flow) : I.radiator(0, 0, z.flow)}</svg>`)).join("")}</div>`).join("")}</section>
      <section class="card"><h2>Grundwerte</h2>${this._slider(sys.ent.eco, "Eco")}${this._slider(sys.ent.away_temp, "Abwesend")}</section></div></div>`;
  }

  _render() {
    if (!this._hass) return;
    const v = window.__variant || "A";
    const systems = this._model();
    this.shadowRoot.innerHTML = `<style>${CSS}${PCSS}</style><div class="page v${v}">
      <div class="top"><span>Heizung</span><span class="proto">Entwurf ${v}</span></div>
      ${systems.map((s) => this[`_variant${v}`](s)).join("")}</div>`;
    this.shadowRoot.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => this._toggle(b.dataset.toggle)));
  }
}

const PCSS = `
  .page { max-width: 1100px; }
  .top { font-weight: 500; justify-content: space-between; }
  .proto { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: #7c4dff; color: #fff; }
  .headrow h1 { font-size: 26px; font-weight: 600; margin: 4px 0 12px; }
  h2 { font-size: 16px; font-weight: 600; }
  .sect { margin: 20px 4px 10px; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .card { border-radius: 16px; padding: 16px; border: 1px solid var(--divider-color); box-shadow: 0 1px 2px #0000000d; }
  .cardhead { display:flex; justify-content:space-between; align-items:flex-start; gap: 8px; margin-bottom: 8px; }
  .status { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap: 12px; padding: 12px 16px; border-radius: 16px; margin-bottom: 12px; }
  .status.shadow { background: repeating-linear-gradient(135deg, #90a4ae1f 0 10px, #90a4ae2e 10px 20px); border: 1px dashed #90a4ae; }
  .status.live { background: #43a04722; border: 1px solid #43a047; }
  .stxt { display:flex; flex-direction:column; } .stxt small { color: var(--secondary-text-color); }
  .seg { display:inline-flex; border: 1px solid var(--divider-color); border-radius: 999px; overflow:hidden; background: var(--card-background-color); }
  .seg button { border:0; background: transparent; color: var(--primary-text-color); padding: 8px 14px; font: inherit; font-size: 14px; }
  .seg button + button { border-left: 1px solid var(--divider-color); }
  .seg button.on { background: var(--primary-color); color: #fff; }
  .alert { display:flex; gap: 10px; align-items:center; padding: 10px 14px; border-radius: 12px; background: ${WARN}22; border: 1px solid ${WARN}; margin-bottom: 12px; font-size: 14px; }
  .badge { font-size: 12px; font-weight: 500; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
  .badge.hot { background: ${HOT}; color: #fff; } .badge.eco { background: ${COLD}22; color: ${COLD}; }
  .badge.off { background: var(--secondary-background-color); color: var(--secondary-text-color); } .badge.warn { background: ${WARN}33; color: var(--primary-text-color); }
  .schema { display:block; min-width: 0; overflow: visible; }
  .schema .box { fill: var(--card-background-color); stroke: var(--divider-color); stroke-width: 1.5; }
  .schema .box.hot { stroke: ${HOT}; } .schema .box.warnbox { stroke: ${WARN}; stroke-dasharray: 4 3; }
  .schema .boiler { fill: ${HOT}14; stroke: ${HOT}88; }
  .schema .t, .schema .s, .schema .big { text-anchor: start; } .schema .pipe { opacity: 1; }
  .schema .t { font-size: 14px; font-weight: 600; fill: var(--primary-text-color); } .schema .t.sm { font-size: 13px; }
  .schema .s { font-size: 12px; fill: var(--secondary-text-color); } .schema .end { text-anchor: end; } .schema .mid { text-anchor: middle; }
  .schema .big { font-size: 20px; font-weight: 600; fill: var(--primary-text-color); } .schema .big.hot { fill: ${HOT}; } .schema .big.warn { fill: ${WARN}; }
  .schema .pipe { fill: none; stroke-width: 5; stroke-linecap: round; stroke-linejoin: round; } .schema .pipe.thin { stroke-width: 3.5; }
  .schema .pipe.flow { stroke-dasharray: 10 8; animation: flow 1.2s linear infinite; } .schema .pipe.flow.back { animation-direction: reverse; }
  .schema .halo { fill: none; stroke: var(--card-background-color); stroke-width: 11; }
  .pump circle { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 2; } .pump path { fill: ${IDLE}; }
  .pump.on circle { stroke: ${HOT}; } .pump.on path { fill: ${HOT}; }
  .valve path { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.8; stroke-linejoin: round; } .valve.open path { fill: ${HOT}; stroke: ${HOT}; }
  .rad rect, .rad path { fill: var(--card-background-color); stroke: ${IDLE}; stroke-width: 1.8; } .rad path { fill: none; }
  .rad.on rect, .rad.on path { stroke: ${HOT}; } .rad.on rect { fill: ${HOT}22; }
  .legend { display:flex; flex-wrap:wrap; gap: 6px 16px; margin-top: 12px; font-size: 12px; color: var(--secondary-text-color); align-items:center; }
  .legend span { display:inline-flex; align-items:center; gap: 6px; } .legend .ln { width: 22px; height: 5px; border-radius: 3px; display:inline-block; }
  .list { display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; margin-bottom: 12px; } .list .card { margin: 0; }
  .circ { border-left: 5px solid var(--divider-color); } .circ.hot { border-left-color: ${HOT}; } .circ.eco { border-left-color: ${COLD}; } .circ.warn { border-left-color: ${WARN}; }
  .temps { display:flex; align-items:flex-end; gap: 14px; margin: 6px 0 4px; } .temps div { display:flex; flex-direction:column; }
  .temps small { font-size: 12px; color: var(--secondary-text-color); } .temps b { font-size: 30px; font-weight: 600; line-height: 1.1; } .temps .arrow { font-size: 22px; color: var(--secondary-text-color); padding-bottom: 4px; }
  .kv { display:grid; grid-template-columns: auto 1fr auto 1fr; gap: 4px 10px; font-size: 14px; margin: 6px 0; } .kv span { color: var(--secondary-text-color); }
  .would { font-size: 13px; background: var(--secondary-background-color); border-radius: 8px; padding: 6px 10px; margin: 6px 0; }
  .roomrow { display:flex; align-items:center; gap: 10px; padding: 10px 0 0; margin-top: 10px; border-top: 1px solid var(--divider-color); }
  .rname { display:flex; flex-direction:column; flex: 1; min-width: 0; } .rname small { font-size: 12px; color: var(--secondary-text-color); }
  .group { margin-bottom: 18px; } .ghead { display:flex; align-items:center; gap: 10px; margin: 0 4px 8px; } .strip { font-size: 13px; color: var(--secondary-text-color); }
  .tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; }
  .tile { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 18px; padding: 12px; display:flex; flex-direction:column; align-items:center; gap: 4px; }
  .tile.hot { border-color: ${HOT}88; } .tile.warn { border-color: ${WARN}; }
  .tname { font-weight: 600; font-size: 14px; align-self: stretch; }
  .ring { width: 120px; height: 120px; } .ring circle { fill: none; stroke-width: 9; stroke-linecap: round; }
  .ring .track { stroke: var(--secondary-background-color); } .ring .val { stroke: ${IDLE}; } .ring.hot .val { stroke: ${HOT}; } .ring.eco .val { stroke: ${COLD}; } .ring.warn .val { stroke: ${WARN}; }
  .ring .mark { fill: var(--card-background-color); stroke: var(--primary-text-color); stroke-width: 2.5; }
  .ring .rv { font-size: 22px; font-weight: 600; text-anchor: middle; fill: var(--primary-text-color); } .ring .rs { font-size: 10px; text-anchor: middle; fill: var(--secondary-text-color); }
  .tmode { font-size: 13px; font-weight: 500; } .center { text-align: center; }
  .bigtemp { font-size: 44px; font-weight: 600; color: ${HOT}; padding: 22px 0 10px; }
  .stepper { display:flex; align-items:center; gap: 8px; margin-top: 6px; font-size: 13px; }
  .stepper button { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-size: 18px; }
  details.card summary { list-style: none; cursor: pointer; } details.card summary h2 { display:inline; }
  .split { display:grid; grid-template-columns: 1.6fr 1fr; gap: 12px; align-items: start; } .split .card { margin: 0 0 12px; }
  .lgroup + .lgroup { margin-top: 12px; } .lghead { display:flex; justify-content:space-between; font-weight: 600; font-size: 14px; padding: 4px 0; }
  .lrow { border-top: 1px solid var(--divider-color); } .lrow summary { display:flex; align-items:center; gap: 10px; padding: 8px 0; list-style: none; cursor: pointer; }
  .schema .house { fill: var(--secondary-background-color); stroke: var(--divider-color); }
  .schema .floorband { fill: none; stroke: var(--divider-color); } .schema .cellar { fill: var(--secondary-background-color); }
  .schema .fl { font-size: 12px; font-weight: 600; text-anchor: end; fill: var(--secondary-text-color); }
  @media (max-width: 869px) { .split { grid-template-columns: 1fr; } .tiles { grid-template-columns: repeat(2, 1fr); } .ring { width: 104px; height: 104px; } .seg button { padding: 8px 11px; } }
`;

customElements.define("heating-core-prototype", HeatingCorePrototype);
