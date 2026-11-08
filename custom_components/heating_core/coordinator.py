"""Koordinator: liest Zustände, rechnet mit logic/writes/timing und schreibt nur bei „Schreiben aktiv“."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .adapters import get_adapter
from .const import (
    CONF_MANUFACTURER,
    DEFAULTS,
    DOMAIN,
    F_CIRCUIT,
    F_CLIMATE,
    F_COMFORT,
    F_COMFORT_ENTITY,
    F_HUMIDITY,
    F_KIND,
    F_PUMP,
    F_SOURCE_OFF,
    F_SOURCE_ON,
    F_SOURCE_TEMP,
    F_VALVE_DELAY,
    F_VALVES,
    KIND_FLOOR_EXTERNAL,
    F_MASTER,
    F_NAME,
    F_OFFSET,
    F_PRESENCE,
    F_ROLE,
    F_SCHEDULE,
    F_TEMP,
    F_WINDOW,
    OPT_ACTIVATION_MIN,
    OPT_AWAY_ENTITIES,
    OPT_AWAY_TEMP,
    OPT_BOOST_AMOUNT,
    OPT_BOOST_ENABLED,
    OPT_BOOST_THRESHOLD,
    OPT_BUDGET,
    OPT_DEACTIVATION_MIN,
    OPT_ECO,
    OPT_GUEST_ENTITY,
    OPT_HUMIDITY_DROP,
    OPT_HUMIDITY_ENABLED,
    OPT_HYSTERESIS,
    OPT_MIN_TRV,
    OPT_OUTDOOR_SENSOR,
    OPT_PRE_HEAT_TIMEOUT_MIN,
    OPT_SUMMER_ENTITY,
    OPT_WEATHER_ENABLED,
    OPT_WEATHER_ZONE1,
    OPT_WEATHER_ZONE2,
    OPT_WEATHER_ZONE3,
    OPT_WINDOW_DELAY_S,
    OPT_WINDOW_SETTLE_S,
    STARTUP_GUARD_S,
    SUB_CIRCUIT,
    SUB_ROOM,
    UPDATE_INTERVAL_S,
)
from .floor import Zone, plan as floor_plan
from .logic import Globals, MasterInput, RoomInput, follower_target, master_target, room_base, room_target
from .timing import Reading, presence, window
from .writes import Decision, Write, WriteConfig, decide

_LOGGER = logging.getLogger(__name__)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ControlState:
    """Laufzeit-Zustand, der nicht in Home Assistant steht."""

    away: bool = False
    guest: bool = False
    write_enabled: bool = False  # Schattenbetrieb, bis jemand bewusst einschaltet
    writes: dict[str, list[Write]] = field(default_factory=dict)
    presence: dict[str, bool] = field(default_factory=dict)
    pre_heat: dict[str, float] = field(default_factory=dict)  # Subentry -> Start (Sekunden)
    source_ok: dict[str, bool] = field(default_factory=dict)  # Fußbodenkreis -> Kessel freigegeben
    comfort: dict[str, float] = field(default_factory=dict)  # Regler „Komfort“ je Kreis/Raum
    eco: float | None = None  # Regler „Eco“ der Anlage
    away_temp: float | None = None  # Regler „Abwesend“ der Anlage


class HeatingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Eine Anlage = ein Koordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.title}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_S),
        )
        self.entry = entry
        self.control = ControlState()
        self.adapter = get_adapter(hass, entry.data.get(CONF_MANUFACTURER, ""))
        self._started = time.time()
        self._unsub = None

    # ---- Konfiguration -----------------------------------------------------

    def opt(self, key: str) -> Any:
        return self.entry.options.get(key, DEFAULTS.get(key))

    def circuits(self) -> dict[str, dict]:
        return {
            sid: dict(sub.data, name=sub.title)
            for sid, sub in self.entry.subentries.items()
            if sub.subentry_type == SUB_CIRCUIT
        }

    def rooms(self, circuit_id: str) -> dict[str, dict]:
        return {
            sid: dict(sub.data, name=sub.title)
            for sid, sub in self.entry.subentries.items()
            if sub.subentry_type == SUB_ROOM and sub.data.get(F_CIRCUIT) == circuit_id
        }

    def watched_entities(self) -> set[str]:
        ids: set[str] = set(self.opt(OPT_AWAY_ENTITIES) or [])
        for key in (OPT_GUEST_ENTITY, OPT_SUMMER_ENTITY, OPT_OUTDOOR_SENSOR):
            if self.opt(key):
                ids.add(self.opt(key))
        for cfg in [*self.circuits().values(), *(s.data for s in self.entry.subentries.values() if s.subentry_type == SUB_ROOM)]:
            for key in (F_MASTER, F_CLIMATE, F_COMFORT_ENTITY, F_SCHEDULE, F_WINDOW, F_TEMP, F_HUMIDITY, F_PUMP, F_SOURCE_TEMP):
                if cfg.get(key):
                    ids.add(cfg[key])
            ids.update(cfg.get(F_PRESENCE) or [])
            ids.update(cfg.get(F_VALVES) or [])
        return ids

    @callback
    def start_listening(self) -> None:
        @callback
        def _changed(_event: Event) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        ids = self.watched_entities()
        if ids:
            self._unsub = async_track_state_change_event(self.hass, list(ids), _changed)

    @callback
    def stop_listening(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    # ---- Zustände lesen ----------------------------------------------------

    def _on(self, entity_id: str | None) -> bool:
        return bool(entity_id) and self.hass.states.is_state(entity_id, "on")

    def _num(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        return _float(st.state) if st else None

    def _attr(self, entity_id: str | None, attr: str) -> float | None:
        st = self.hass.states.get(entity_id) if entity_id else None
        return _float(st.attributes.get(attr)) if st else None

    def _reading(self, entity_id: str) -> Reading:
        st = self.hass.states.get(entity_id)
        if st is None:
            return Reading("unavailable", 0.0)
        return Reading(st.state, st.last_changed.timestamp())

    def _presence(self, key: str, sensors: list[str], now: float) -> bool:
        prev = self.control.presence.get(key, False)
        cur = presence(
            [self._reading(s) for s in sensors],
            now=now,
            activation_s=float(self.opt(OPT_ACTIVATION_MIN)) * 60,
            deactivation_s=float(self.opt(OPT_DEACTIVATION_MIN)) * 60,
            previous=prev,
        )
        self.control.presence[key] = cur
        return cur

    def _window(self, entity_id: str | None, now: float):
        return window(
            self._reading(entity_id) if entity_id else None,
            now=now,
            open_delay_s=float(self.opt(OPT_WINDOW_DELAY_S)),
            settle_s=float(self.opt(OPT_WINDOW_SETTLE_S)),
        )

    def _pre_heat(self, sid: str, now: float, took_over: bool) -> bool:
        """Vorheizen ist aktiv bis Präsenz/Zeitplan übernimmt oder das Zeitlimit abläuft."""
        start = self.control.pre_heat.get(sid)
        if start is None:
            return False
        if took_over or now - start >= float(self.opt(OPT_PRE_HEAT_TIMEOUT_MIN)) * 60:
            del self.control.pre_heat[sid]
            return False
        return True

    def _comfort(self, cfg: dict, sid: str | None = None) -> float:
        """Komfort: eigener Regler > gewählter Helfer > Wert aus dem Formular."""
        if sid in self.control.comfort:
            return self.control.comfort[sid]
        return self._num(cfg.get(F_COMFORT_ENTITY)) or float(cfg.get(F_COMFORT, 20.0))

    def globals(self) -> Globals:
        return Globals(
            eco=self.control.eco if self.control.eco is not None else float(self.opt(OPT_ECO)),
            away_temp=self.control.away_temp if self.control.away_temp is not None else float(self.opt(OPT_AWAY_TEMP)),
            min_trv=float(self.opt(OPT_MIN_TRV)),
            hysteresis=float(self.opt(OPT_HYSTERESIS)),
            away=self.control.away or any(self._on(e) for e in self.opt(OPT_AWAY_ENTITIES) or []),
            guest=self.control.guest or self._on(self.opt(OPT_GUEST_ENTITY)),
            summer=self._on(self.opt(OPT_SUMMER_ENTITY)),
        )

    # ---- Rechnen und schreiben ---------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        now = time.time()
        g = self.globals()
        result: dict[str, Any] = {"globals": g, "circuits": {}}
        for cid, ccfg in self.circuits().items():
            result["circuits"][cid] = await self._circuit(cid, ccfg, g, now)
        # Brennstoff (nur Ökofen): aus dem ersten Heizkreis mit Master abgeleitet
        fuel = getattr(self.adapter, "fuel", None)
        masters = [c[F_MASTER] for c in self.circuits().values() if c.get(F_MASTER)]
        result["fuel_kg"] = fuel(masters[0]) if fuel and masters else None
        return result

    async def _circuit(self, cid: str, ccfg: dict, g: Globals, now: float) -> dict[str, Any]:
        if ccfg.get(F_KIND) == KIND_FLOOR_EXTERNAL:
            return await self._floor_circuit(cid, ccfg, g, now)
        master_entity = ccfg.get(F_MASTER)
        state = self.adapter.read(master_entity)
        out: dict[str, Any] = {"name": ccfg[F_NAME], "rooms": {}, "available": state.available}
        if not state.available:
            out["problem"] = "master_unavailable"
            return out

        isolated: list[tuple[RoomInput, Any]] = []
        followers: list[tuple[str, dict]] = []
        for rid, rcfg in self.rooms(cid).items():
            if rcfg.get(F_ROLE) == "follower":
                followers.append((rid, rcfg))
                continue
            r_in = self._room_input(rid, rcfg, now)
            if r_in is None:
                out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": "unavailable", "target": None, "problem": "room_unavailable"}
                continue
            r_res = room_target(g, r_in)
            isolated.append((r_in, r_res))
            out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": r_res.mode, "target": r_res.target, "entity": rcfg[F_CLIMATE],
                                 "setpoint": r_in.current_setpoint, "presence": r_in.presence_on, "current": r_in.current_temp,
                                 "heat_demand": r_res.needs_heat}

        lim = self.adapter.limits(master_entity)
        win = self._window(ccfg.get(F_WINDOW), now)
        any_window = any(
            self._on(w) for w in [ccfg.get(F_WINDOW), *(r.get(F_WINDOW) for r in self.rooms(cid).values())] if w
        )
        current = self._num(ccfg.get(F_TEMP))
        if current is None:
            current = state.current
        if current is None:
            # Keine Ist-Temperatur: nicht raten, nichts schreiben.
            out["problem"] = "temperature_unknown"
            return out
        m_presence = self._presence(cid, ccfg.get(F_PRESENCE) or [], now)
        m_schedule = self._on(ccfg.get(F_SCHEDULE))
        m_in = MasterInput(
            comfort=self._comfort(ccfg, cid),
            current_temp=current,
            set_now=state.setpoint or 0.0,
            schedule_on=m_schedule,
            presence_on=m_presence,
            pre_heat_on=self._pre_heat(cid, now, m_presence or m_schedule),
            has_demand_source=bool(ccfg.get(F_SCHEDULE) or ccfg.get(F_PRESENCE)),
            window_open_too_long=win.open_too_long,
            any_window_open=any_window,
            min_temp=lim.min_temp,
            max_temp=lim.max_temp,
            boost_enabled=bool(self.opt(OPT_BOOST_ENABLED)),
            boost_amount=float(self.opt(OPT_BOOST_AMOUNT)),
            boost_threshold=float(self.opt(OPT_BOOST_THRESHOLD)),
            weather_enabled=bool(self.opt(OPT_WEATHER_ENABLED)),
            outdoor_temp=self._num(self.opt(OPT_OUTDOOR_SENSOR)),
            weather_zones=(
                float(self.opt(OPT_WEATHER_ZONE1)),
                float(self.opt(OPT_WEATHER_ZONE2)),
                float(self.opt(OPT_WEATHER_ZONE3)),
            ),
            humidity_enabled=bool(self.opt(OPT_HUMIDITY_ENABLED)),
            humidity=self._num(ccfg.get(F_HUMIDITY)),
            humidity_drop=float(self.opt(OPT_HUMIDITY_DROP)),
        )
        m_res = master_target(g, m_in, isolated)
        out.update(target=m_res.target, state=m_res.state, set_now=state.setpoint, presence=m_presence,
                   current=current, budget_left=None, mode=_circuit_mode(m_res, m_in, g))

        for rid, rcfg in followers:
            t = follower_target(g, m_res.target_before_mods, float(rcfg.get(F_OFFSET, -2.0)), self._window(rcfg.get(F_WINDOW), now).open_too_long)
            out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": "follower", "target": t, "entity": rcfg[F_CLIMATE], "setpoint": self._attr(rcfg[F_CLIMATE], "temperature")}

        writes = self.control.writes.setdefault(cid, [])
        dec = decide(
            now=now,
            target=m_res.target,
            set_now=state.setpoint,
            writes=writes,
            cfg=WriteConfig(budget_per_hour=int(self.opt(OPT_BUDGET)), hysteresis=g.hysteresis, confirm_delay_s=lim.confirm_delay_s),
            forced_min=m_res.forced_min,
            away=g.away_effective,
            renew_due=state.renew_due,
            startup_done=now - self._started >= STARTUP_GUARD_S,
        )
        if state.heating_off and not m_res.forced_min:
            # Kreis von der Anlage selbst abgeschaltet: nicht übersteuern.
            dec = Decision(False, "none", "circuit_off")
            out["mode"] = "circuit_off"
        out["decision"] = dec.reason
        out["budget_left"] = max(0, WriteConfig(budget_per_hour=int(self.opt(OPT_BUDGET))).budget - len([w for w in writes if now - w.ts < 3600]))
        out["would_write"] = dec.write
        if dec.write and self.control.write_enabled:
            await self.adapter.write_setpoint(master_entity, m_res.target)
            writes.append(Write(now, m_res.target, dec.kind))
            del writes[:-20]

        if self.control.write_enabled and now - self._started >= STARTUP_GUARD_S:
            for room in out["rooms"].values():
                tgt, cur = room.get("target"), room.get("setpoint")
                if tgt is not None and (cur is None or abs(tgt - cur) > g.hysteresis):
                    await self.hass.services.async_call(
                        "climate", "set_temperature", {"entity_id": room["entity"], "temperature": tgt}, blocking=True
                    )
        return out

    async def _floor_circuit(self, cid: str, ccfg: dict, g: Globals, now: float) -> dict[str, Any]:
        """Fußboden mit eigener Pumpe und Ventil-Kanälen (Sonderfall Perg)."""
        out: dict[str, Any] = {"name": ccfg[F_NAME], "rooms": {}, "available": True, "target": None}
        zones: list[Zone] = []
        valves_by_zone: dict[str, list[str]] = {}
        for rid, rcfg in self.rooms(cid).items():
            valves = rcfg.get(F_VALVES) or []
            valves_by_zone[rid] = valves
            readings = [self._reading(v) for v in valves]
            open_now = bool(valves) and all(r.state == "on" for r in readings)
            open_since = max(r.since for r in readings) if open_now else None
            temp = self._num(rcfg.get(F_TEMP))
            win = self._window(rcfg.get(F_WINDOW), now)
            presence_on = self._presence(rid, rcfg.get(F_PRESENCE) or [], now)
            schedule_on = self._on(rcfg.get(F_SCHEDULE))
            target, _active = room_base(g, RoomInput(
                comfort=self._comfort(rcfg, rid), current_temp=temp or 0.0, current_setpoint=0.0,
                schedule_on=schedule_on, presence_on=presence_on,
                pre_heat_on=self._pre_heat(rid, now, presence_on or schedule_on),
                has_demand_source=bool(rcfg.get(F_SCHEDULE) or rcfg.get(F_PRESENCE)),
                window_open_too_long=win.open_too_long,
            ))
            zones.append(Zone(rid, temp, target, open_now, open_since, any(r.state == "on" for r in readings)))
            out["rooms"][rid] = {"name": rcfg[F_NAME], "target": target, "current": temp, "valves_open": open_now,
                                 "presence": presence_on}

        source = self._num(ccfg.get(F_SOURCE_TEMP))
        pump_entity = ccfg.get(F_PUMP)
        p = floor_plan(
            zones,
            now=now,
            source_temp=source,
            source_on=float(ccfg.get(F_SOURCE_ON, 50.0)),
            source_off=float(ccfg.get(F_SOURCE_OFF, 45.0)),
            source_ok_before=self.control.source_ok.get(cid, False),
            pump_on=self._on(pump_entity),
            valve_delay_s=float(ccfg.get(F_VALVE_DELAY, 180)),
            hysteresis=0.5,
        )
        self.control.source_ok[cid] = p.source_ok
        for z in zones:
            room = out["rooms"][z.key]
            room["valves_wanted"] = p.zones[z.key]
            if z.key in p.problems:
                room["problem"] = p.problems[z.key]
                room["mode"] = "sensor_missing"
            else:
                room["mode"] = "floor_heating" if p.zones[z.key] else "floor_idle"
        out.update(source_temp=source, source_ok=p.source_ok, pump_wanted=p.pump, pump_on=self._on(pump_entity),
                   mode="floor_heating" if p.pump else ("source_cold" if not p.source_ok else "floor_idle"),
                   state="shadow" if not self.control.write_enabled else "active")
        if source is None:
            out["problem"] = "source_temperature_unknown"

        switches: list[tuple[str, bool]] = []
        for rid, wanted in p.zones.items():
            if wanted is None:
                continue
            switches += [(v, wanted) for v in valves_by_zone[rid] if self._on(v) != wanted]
        if pump_entity and self._on(pump_entity) != p.pump:
            # Pumpe zuerst aus bzw. zuletzt an
            switches = [(pump_entity, p.pump)] + switches if not p.pump else switches + [(pump_entity, p.pump)]
        out["would_switch"] = [f"{e} → {'an' if on else 'aus'}" for e, on in switches]
        out["would_write"] = bool(switches)
        if switches and self.control.write_enabled and now - self._started >= STARTUP_GUARD_S:
            for entity_id, on in switches:
                await self.hass.services.async_call(
                    "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
                )
        return out

    def _room_input(self, rid: str, rcfg: dict, now: float) -> RoomInput | None:
        climate = rcfg.get(F_CLIMATE)
        st = self.hass.states.get(climate) if climate else None
        if st is None or st.state in ("unavailable", "unknown"):
            return None
        current = self._num(rcfg.get(F_TEMP)) or _float(st.attributes.get("current_temperature"))
        if current is None:
            return None
        win = self._window(rcfg.get(F_WINDOW), now)
        r_presence = self._presence(rid, rcfg.get(F_PRESENCE) or [], now)
        r_schedule = self._on(rcfg.get(F_SCHEDULE))
        return RoomInput(
            comfort=self._comfort(rcfg, rid),
            current_temp=current,
            current_setpoint=_float(st.attributes.get("temperature")) or 0.0,
            schedule_on=r_schedule,
            presence_on=r_presence,
            pre_heat_on=self._pre_heat(rid, now, r_presence or r_schedule),
            has_demand_source=bool(rcfg.get(F_SCHEDULE) or rcfg.get(F_PRESENCE)),
            window_open_too_long=win.open_too_long,
            window_closed_recently=win.closed_recently,
        )


def _circuit_mode(res, m_in: MasterInput, g: Globals) -> str:
    """Verständlicher Modus des Heizkreises für Anzeige und Oberfläche."""
    if g.summer:
        return "summer"
    if m_in.window_open_too_long:
        return "window"
    if res.forced_min:
        return "temperature_drop"
    if g.away_effective and not m_in.pre_heat_on:
        return "away"
    if res.boost_active:
        return "boost"
    if m_in.pre_heat_on:
        return "pre_heat"
    if m_in.schedule_on:
        return "schedule"
    if m_in.presence_on:
        return "presence"
    if not m_in.has_demand_source:
        return "manual"
    return "eco"
