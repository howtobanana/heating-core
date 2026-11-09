// Zusatz für build.mjs: öffnet den Zeitplan-Editor (HEATING-20) mit einem nachgebauten Wochenplan.
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
    ed.shadowRoot.querySelector(".blk").click();       // Block antippen -> Uhrzeit-Felder
    ed.shadowRoot.querySelector("[data-copy='0']").click(); // Montag kopieren
  }, 150);
}, 200);
