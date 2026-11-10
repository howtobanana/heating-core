// Zusatz für build.mjs: Zeitplan-Editor (HEATING-20/31) öffnen, Ziehen/Verschieben/Anlegen/Feinstellen/Kopieren prüfen.
// Fehlschlag wirft einen Fehler -> ui-test-unraid.sh zeigt „Fehler: Prüfung …“.
setTimeout(() => {
  const panel = document.querySelector("heating-core-panel");
  const item = { id: "heizplan_hk1", name: "Heizplan HK1", icon: "mdi:radiator",
    monday: [{ from: "05:30:00", to: "08:00:00" }, { from: "16:00:00", to: "22:00:00" }],
    tuesday: [{ from: "05:30:00", to: "08:00:00" }, { from: "16:00:00", to: "22:00:00" }],
    wednesday: [{ from: "05:30:00", to: "22:00:00" }], thursday: [{ from: "05:30:00", to: "08:00:00" }, { from: "16:00:00", to: "22:00:00" }],
    friday: [{ from: "05:30:00", to: "08:00:00" }, { from: "14:00:00", to: "23:00:00" }],
    saturday: [{ from: "07:00:00", to: "23:00:00" }], sunday: [{ from: "07:00:00", to: "22:00:00" }] };
  panel._hass.callWS = async (m) => m.type === "schedule/list" ? [item] : m.type === "config/entity_registry/get" ? { unique_id: "heizplan_hk1" } : {};
  const b = panel.shadowRoot.querySelector("[data-plan]:not([data-plan=''])") || panel.shadowRoot.querySelector("[data-plan]");
  b.click();
  setTimeout(() => {
    const ed = panel.shadowRoot.querySelector("hc-schedule-editor");
    const q = (s) => ed.shadowRoot.querySelector(s);
    const track = (d) => q(`.track[data-day='${d}']`);
    const x = (d, min) => { const r = track(d).getBoundingClientRect(); return r.left + (min / 1440) * r.width; };
    const ev = (el, type, cx) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0, pointerId: 1, clientX: cx, clientY: 0 }));
    const drag = (d, el, from, to) => { ev(el, "pointerdown", x(d, from)); ev(track(d), "pointermove", x(d, (from + to) / 2)); ev(track(d), "pointermove", x(d, to)); ev(track(d), "pointerup", x(d, to)); };
    const days = (d) => JSON.stringify(ed._days[d]);
    const check = (ok, what) => { if (!ok) throw new Error(`Prüfung ${what}: ${JSON.stringify(ed._days)}`); };

    drag(0, q(".blk[data-d='0'][data-k='0'] .h.r"), 480, 540);       // Mo Ende 08:00 -> 09:00
    check(ed._days[0][0].to === 540, "Rand ziehen");
    drag(0, q(".blk[data-d='0'][data-k='1']"), 1020, 1080);           // Mo 16–22 um 1 h verschieben
    check(ed._days[0][1].from === 1020 && ed._days[0][1].to === 1380, "verschieben");
    const before = days(1);
    ev(track(1), "pointerdown", x(1, 720)); ev(track(1), "pointerup", x(1, 720)); // Tippen auf freie Fläche
    check(days(1) === before, "Tippen legt nichts an");
    drag(1, track(1), 600, 720);                                       // Di 10–12 neu
    check(ed._days[1].some((b) => b.from === 600 && b.to === 720), "neuer Block");
    q("[data-step=to][data-dir='1']").click();                         // neuer Block ist gewählt: Ende +15 min
    check(ed._days[1].some((b) => b.from === 600 && b.to === 735), "Feinstellen");
    q("[data-copy='0']").click(); q("[data-to='0,1,2,3,4']").click();  // Mo -> Mo–Fr
    check([1, 2, 3, 4].every((d) => days(d) === days(0)) && days(5) !== days(0), "kopieren");

    // Bild: Montag-Block gewählt -> Leiste mit −/+ und Löschen
    const blk = q(".blk[data-d='0'][data-k='0']");
    ev(blk, "pointerdown", x(0, 400)); ev(track(0), "pointerup", x(0, 400));
    check(q(".edit [data-step=from]"), "Antippen zeigt Leiste");
    console.log("zeitplan: alle Prüfungen ok");
  }, 150);
}, 200);
