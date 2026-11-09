// Zusatz für build.mjs: HK2 ausgeschaltet (HEATING-27), die anderen Kreise mit Schalter „an“.
setTimeout(() => {
  const panel = document.querySelector("heating-core-panel");
  const h = panel._hass;
  for (const [id, e] of Object.entries(h.entities)) {
    if (e.translation_key !== "target" || h.states[id].attributes.anlage === undefined) continue;
    const sw = `switch.${e.device_id.replace(/\W/g, "_").toLowerCase()}_enabled`;
    const off = /HK2/.test(e.device_id);
    h.entities[sw] = { entity_id: sw, platform: "heating_core", device_id: e.device_id, translation_key: "enabled" };
    h.states[sw] = { entity_id: sw, state: off ? "off" : "on", attributes: {} };
    if (off) { const m = Object.values(h.entities).find((x) => x.device_id === e.device_id && x.translation_key === "mode"); if (m) h.states[m.entity_id].state = "disabled"; }
  }
  panel._entObj = null; panel._sig = null; panel.hass = { ...h, entities: { ...h.entities } };
}, 200);
