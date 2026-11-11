"""System-Diagnose wie der Vaillant-Blueprint „System-Diagnose“ (HEATING-41): meldet nur, schaltet nie.

Batterien und Erreichbarkeit aller Geräte, die Heating Core benutzt (automatisch über die Geräte der
eingetragenen Entitäten), Störcode der Therme, Wasserdruck; dazu das tägliche Briefing.
Die Zeilen landen in der Problem-Meldung und als Push (notify.py), Texte bleiben gleich, solange sich
der Zustand nicht ändert – sonst käme bei jedem Messwert ein neuer Push.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import OPT_BATTERY_MIN, OPT_EFFICIENCY_SENSOR, OPT_ERROR_ENTITY, OPT_PRESSURE_MIN, OPT_PRESSURE_SENSOR

OFFLINE_S = 15 * 60  # wie der Blueprint: erst nach 15 min melden, Funk-Aussetzer bleiben still
PRESSURE_WARN_BAND = 0.2  # Warnstufe liegt 0,2 bar über der kritischen Grenze (Blueprint)
NO_ERROR = {"", "ok", "0", "none", "no_error", "no error", "off", "unknown", "unavailable"}


def _de(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def _num(hass: HomeAssistant, entity_id: str | None) -> float | None:
    st = hass.states.get(entity_id) if entity_id else None
    try:
        return float(st.state) if st else None
    except ValueError:
        return None


def health(hass: HomeAssistant, entities: set[str], opt, now: float) -> list[str]:
    """Diagnose-Zeilen für die Problem-Meldung."""
    out: list[str] = []
    reg = er.async_get(hass)
    devices: set[str] = set()
    for eid in sorted(entities):
        ent = reg.async_get(eid)
        if ent and ent.device_id:
            devices.add(ent.device_id)
        st = hass.states.get(eid)
        # Thermostate und Kessel meldet die Regelung schon selbst (room_unavailable/master_unavailable)
        if st and st.state == "unavailable" and not eid.startswith("climate.") and now - st.last_changed.timestamp() >= OFFLINE_S:
            out.append(f"📡 Seit über 15 min nicht erreichbar: {st.name}")

    limit = float(opt(OPT_BATTERY_MIN))
    for dev in sorted(devices):
        for e in er.async_entries_for_device(reg, dev):
            if (e.device_class or e.original_device_class) != "battery":
                continue
            st = hass.states.get(e.entity_id)
            if st is None:
                continue
            low = st.state == "on" if e.domain == "binary_sensor" else (_num(hass, e.entity_id) or 100) < limit
            if low:
                out.append(f"🔋 Batterie schwach (unter {limit:.0f} %): {st.name}")

    err = opt(OPT_ERROR_ENTITY)
    st = hass.states.get(err) if err else None
    if st and st.state.lower() not in NO_ERROR:
        codes = st.attributes.get("diagnostic_trouble_codes")
        detail = codes if codes else (st.state if not err.startswith("binary_sensor.") else "Details an der Therme")
        out.append(f"🚨 Heizung meldet Störung: {detail}")

    pressure, p_min = _num(hass, opt(OPT_PRESSURE_SENSOR)), float(opt(OPT_PRESSURE_MIN))
    if pressure is not None and pressure < p_min:
        out.append(f"🚨 Wasserdruck unter {_de(p_min)} bar – sofort nachfüllen")
    elif pressure is not None and pressure < p_min + PRESSURE_WARN_BAND:
        out.append(f"🟠 Wasserdruck unter {_de(p_min + PRESSURE_WARN_BAND)} bar – bald nachfüllen")
    return out


def briefing(hass: HomeAssistant, data: dict, problems: list[str], opt) -> str:
    """Tägliches System-Briefing (Blueprint: Druck, Effizienz, Master online) plus Pellets und Probleme."""
    lines = []
    pressure = _num(hass, opt(OPT_PRESSURE_SENSOR))
    if opt(OPT_PRESSURE_SENSOR):
        lines.append(f"💧 Druck: {_de(pressure, 2)} bar" if pressure is not None else "💧 Druck: ⚠️ nicht verfügbar")
    eff_id = opt(OPT_EFFICIENCY_SENSOR)
    if eff_id:
        eff = _num(hass, eff_id)
        unit = (hass.states.get(eff_id).attributes.get("unit_of_measurement") or "") if eff is not None else ""
        lines.append(f"⚡ Effizienz: {_de(eff)} {unit}".rstrip() if eff is not None else "⚡ Effizienz: ⚠️ nicht verfügbar")
    circuits = (data or {}).get("circuits", {}).values()
    offline = [c.get("name") for c in circuits if c.get("problem") == "master_unavailable"]
    lines.append(f"🏠 Nicht erreichbar: {', '.join(offline)} ❌" if offline else "🏠 Heizkreise erreichbar ✅")
    if (data or {}).get("fuel_kg") is not None:
        lines.append(f"🪵 Pellets: {data['fuel_kg']:.0f} kg")
    lines.append("✅ Keine Probleme" if not problems else f"⚠️ {len(problems)} offen:\n" + "\n".join(problems))
    return "\n".join(lines)
