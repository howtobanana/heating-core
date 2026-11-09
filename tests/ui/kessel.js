// Zusatz für build.mjs: Kesseldaten der Ökofen-Integration (HEATING-21) einspielen.
setTimeout(() => {
  const panel = document.querySelector("heating-core-panel");
  const h = panel._hass;
  h.states["sensor.perg_pellets"].attributes.kessel = { outdoor: 4.1, starts_per_day: 5.1, runtime_per_start: 161, dhw_boiler_heat: "select.pellematic_hot_water_1_use_boiler_heat", burner_text: "Leistungsbrand", modulation: 94 };
  for (const [id, e] of Object.entries(h.states)) if (e.attributes && e.attributes.anlage !== undefined && e.attributes.kessel_temperatur == null) e.attributes.pumpe_ist = false;
  h.states["select.pellematic_hot_water_1_use_boiler_heat"] = { state: "0_aus", attributes: {} };
  panel._sig = null; panel.hass = { ...h };
}, 200);
