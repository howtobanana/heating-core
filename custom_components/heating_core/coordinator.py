"""Koordinator: liest Zustände, rechnet mit logic/writes/timing und schreibt nur bei „Schreiben aktiv“."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adapters import get_adapter
from .diagnose import health
from .notify import Notifier
from .const import (
    CONF_MANUFACTURER,
    DEFAULTS,
    DOMAIN,
    F_CIRCUIT,
    F_CLIMATE,
    F_COMFORT,
    F_COMFORT_ENTITY,
    F_HUMIDITY,
    F_HVAC_MODE,
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
    F_PRE_HEAT_ENTITY,
    F_PRESENCE,
    ROLE_PASSIVE,
    F_ROLE,
    F_SCHEDULE,
    F_TEMP,
    F_WINDOW,
    OPT_ACTIVATION_MIN,
    OPT_ERROR_ENTITY,
    OPT_PRESSURE_SENSOR,
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
    OPT_PRE_HEAT_LEAD,
    OPT_ROOM_DEMAND_DELTA,
    OPT_SUMMER_ENTITY,
    OPT_SUMMER_LIMIT,
    OPT_SUMMER_MEAN_SENSOR,
    OPT_WEATHER_ENABLED,
    OPT_WEATHER_ZONE1,
    OPT_WEATHER_ZONE2,
    OPT_WEATHER_ZONE3,
    OPT_WINDOW_DELAY_S,
    OPT_WINDOW_SETTLE_S,
    STARTUP_GUARD_S,
    USER_SETTLE_S,
    GENTLE_HOLD_S,
    GENTLE_MIN_HYSTERESIS,
    GENTLE_SHORT_SETBACK_S,
    SUB_CIRCUIT,
    SUB_ROOM,
    UPDATE_INTERVAL_S,
)
from .floor import Zone, plan as floor_plan
from .logic import Globals, MasterInput, RoomInput, follower_target, master_target, room_base, room_target, summer_switch
from .timing import Reading, presence, window
from .writes import Decision, Write, WriteConfig, decide
from . import trv as trv_tools
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

_LOGGER = logging.getLogger(__name__)
TRV_READBACK_S = 5 * 60
MODE_TEXT = {"eco": "Absenkung", "presence": "Präsenz", "schedule": "Zeitplan", "pre_heat": "Vorheizen", "manual": "Komfort",
             "boost": "Boost", "away": "Abwesend", "window": "Fenster offen", "temperature_drop": "Temperatursturz",
             "summer": "Sommer", "circuit_off": "Kreis aus", "disabled": "Ausgeschaltet"}


def _de(v) -> str:
    return "–" if v is None else f"{float(v):.1f}".replace(".", ",")


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
    needs_heat: dict[str, bool] = field(default_factory=dict)  # Raum -> Wärmebedarf im letzten Lauf
    pre_heat: dict[str, float] = field(default_factory=dict)  # Subentry -> Start (Sekunden)
    source_ok: dict[str, bool] = field(default_factory=dict)  # Fußbodenkreis -> Kessel freigegeben
    comfort: dict[str, float] = field(default_factory=dict)  # Regler „Komfort“ je Kreis/Raum
    setback: dict[str, float] = field(default_factory=dict)  # Regler „Absenkung“ je Kreis/Raum
    trv_writes: dict[str, tuple[float, float]] = field(default_factory=dict)
    trv_tuned: dict[str, float] = field(default_factory=dict)  # TRV -> Zeit des letzten Abgleichs (HEATING-16)
    disabled: set[str] = field(default_factory=set)  # Heizkreise, die Fabian ganz ausgeschaltet hat (HEATING-27)
    summer_off: set[str] = field(default_factory=set)  # Master, die Heating Core wegen Sommer ausgeschaltet hat  # TRV -> (Zeit, geschriebener Sollwert)
    eco: float | None = None  # Regler „Eco“ der Anlage
    away_temp: float | None = None  # Regler „Abwesend“ der Anlage
    presence_on_min: float | None = None  # Regler „Präsenz an nach“ (min), sonst Optionen
    presence_off_min: float | None = None  # Regler „Präsenz aus nach“ (min), sonst Optionen
    write_events: dict[str, tuple] = field(default_factory=dict)  # Kreis -> Ereignislage beim letzten Write (HEATING-19)


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
        self.user_input_at = 0.0  # letzte Eingabe an Reglern/Thermostaten (Entprellung)
        self.notifier = Notifier(hass, entry)
        self._store = Store(hass, 1, f"heating_core.{entry.entry_id}")  # überlebt Neustarts: wer wegen Sommer aus ist
        self._events: list[str] = []
        self._last_message: str | None = None  # Zeit der zuletzt gesehenen Kessel-Meldung
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
            for key in (F_MASTER, F_CLIMATE, F_COMFORT_ENTITY, F_SCHEDULE, F_WINDOW, F_TEMP, F_HUMIDITY, F_PUMP, F_SOURCE_TEMP, F_PRE_HEAT_ENTITY):
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

    def user_input(self) -> None:
        """Regler/Thermostat geändert: sofort rechnen und anzeigen, aber erst nach 30 s Ruhe schreiben."""
        self.user_input_at = time.time()

    def _settled(self, now: float) -> bool:
        """Darf geschrieben werden? Startschutz vorbei und 30 s keine Eingabe mehr – mehrere Klicks am Regler
        ergeben einen Schreibvorgang statt vieler (Entprellung wie im Vaillant-Blueprint, schont Budget und Haltezeiten)."""
        return now - self._started >= STARTUP_GUARD_S and now - self.user_input_at >= USER_SETTLE_S

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

    def presence_delay(self, opt: str) -> float:
        """Präsenz-Verzögerung in Minuten: Regler auf der Seite/im Dashboard > Optionen der Anlage."""
        value = self.control.presence_on_min if opt == OPT_ACTIVATION_MIN else self.control.presence_off_min
        return float(self.opt(opt)) if value is None else value

    def _presence(self, key: str, sensors: list[str], now: float) -> bool:
        prev = self.control.presence.get(key, False)
        cur = presence(
            [self._reading(s) for s in sensors],
            now=now,
            activation_s=self.presence_delay(OPT_ACTIVATION_MIN) * 60,
            deactivation_s=self.presence_delay(OPT_DEACTIVATION_MIN) * 60,
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

    def _pre_heat(self, sid: str, now: float, took_over: bool, helper: str | None = None) -> bool:
        """Vorheizen ist aktiv bis Präsenz/Zeitplan übernimmt oder das Zeitlimit abläuft.
        Optionaler Helfer (z. B. vom Geofencing): an = vorheizen; wie im Blueprint schaltet Heating Core ihn
        nach Zeitlimit bzw. sobald Präsenz/Zeitplan übernimmt wieder aus – nur bei aktivem Schreiben."""
        if helper and self._on(helper):
            since = self.hass.states.get(helper).last_changed.timestamp()
            if not took_over and now - since < float(self.opt(OPT_PRE_HEAT_TIMEOUT_MIN)) * 60:
                return True
            if self.control.write_enabled:
                self.hass.async_create_task(
                    self.hass.services.async_call("input_boolean", "turn_off", {"entity_id": helper}, blocking=True))
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

    def setback(self, sid: str, g_eco: float) -> float:
        """Absenkung: eigener Regler > Wert aus dem Formular > Kreis des Raums > Eco der Anlage."""
        if sid in self.control.setback:
            return self.control.setback[sid]
        sub = self.entry.subentries.get(sid)
        data = sub.data if sub else {}
        if data.get("setback") is not None:
            return float(data["setback"])
        if data.get(F_CIRCUIT):
            return self.setback(data[F_CIRCUIT], g_eco)
        return g_eco

    def schedule(self, cfg: dict) -> str | None:
        """Zeitplan: eigener des Raums, sonst der seines Heizkreises (Fabian, 08.11.2026)."""
        if cfg.get(F_SCHEDULE):
            return cfg[F_SCHEDULE]
        parent = self.entry.subentries.get(cfg.get(F_CIRCUIT) or "")
        return parent.data.get(F_SCHEDULE) if parent else None

    async def async_release(self) -> None:
        """Schreiben aus: Anlage zurück an ihre eigene Steuerung (Ökofen: auto, Offset 0)."""
        release = getattr(self.adapter, "release", None)
        if release:
            for ccfg in self.circuits().values():
                if ccfg.get(F_MASTER):
                    await release(ccfg[F_MASTER])

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
        self._events = []
        await self._auto_summer(now)
        g = self.globals()
        result: dict[str, Any] = {"globals": g, "circuits": {}}
        for cid, ccfg in self.circuits().items():
            result["circuits"][cid] = await self._circuit(cid, ccfg, g, now)
        # Brennstoff (nur Ökofen): aus dem ersten Heizkreis mit Master abgeleitet
        fuel = getattr(self.adapter, "fuel", None)
        masters = [c[F_MASTER] for c in self.circuits().values() if c.get(F_MASTER)]
        result["fuel_kg"], result["fuel_max_kg"] = fuel(masters[0]) if fuel and masters else (None, None)
        result["boiler"] = self._boiler(masters[0] if masters else None)
        result["health"] = health(self.hass, self.watched_entities() | {e for e in (self.opt(OPT_PRESSURE_SENSOR), self.opt(OPT_ERROR_ENTITY)) if e},
                                  self.opt, now)
        try:
            await self.notifier.update(result, self._events, ready=now - self._started >= STARTUP_GUARD_S)
        except (HomeAssistantError, ValueError) as err:  # Meldungen dürfen die Regelung nie stoppen
            _LOGGER.warning("Benachrichtigung fehlgeschlagen: %s", err)
        return result

    async def _circuit(self, cid: str, ccfg: dict, g: Globals, now: float) -> dict[str, Any]:
        if ccfg.get(F_KIND) == KIND_FLOOR_EXTERNAL:
            return await self._floor_circuit(cid, ccfg, g, now)
        master_entity = ccfg.get(F_MASTER)
        await self._summer(master_entity, ccfg, g, now)
        state = self.adapter.read(master_entity)
        g_all, g = g, replace(g, eco=self.setback(cid, g.eco))
        out: dict[str, Any] = {"name": ccfg[F_NAME], "rooms": {}, "available": state.available}

        # Vorheizen gilt je Heizkreis; seine Räume heizen mit (Fabian 11.11.2026: nur einen Raum vorheizen ist ineffizient)
        m_presence = self._presence(cid, ccfg.get(F_PRESENCE) or [], now)
        c_pre = self._pre_heat(cid, now, m_presence or self._on(ccfg.get(F_SCHEDULE)), ccfg.get(F_PRE_HEAT_ENTITY))
        isolated: list[tuple[RoomInput, Any]] = []
        followers: list[tuple[str, dict]] = []
        for rid, rcfg in self.rooms(cid).items():
            if rcfg.get(F_ROLE) == ROLE_PASSIVE:
                out["rooms"][rid] = self._passive(rcfg)
                continue
            if rcfg.get(F_ROLE) == "follower":
                followers.append((rid, rcfg))
                continue
            r_in = self._room_input(rid, rcfg, now, c_pre)
            g_room = replace(g_all, eco=self.setback(rid, g_all.eco))
            if r_in is None:
                out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": "unavailable", "target": None, "problem": "room_unavailable"}
                continue
            r_res = room_target(g_room, r_in)
            self.control.needs_heat[rid] = r_res.needs_heat
            isolated.append((r_in, r_res))
            out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": r_res.mode, "target": r_res.target, "entity": rcfg[F_CLIMATE],
                                 "setpoint": r_in.current_setpoint, "presence": r_in.presence_on, "current": r_in.current_temp,
                                 "heat_demand": r_res.needs_heat, "sensor": rcfg.get(F_TEMP)}
            # Rücklesen: 5 min nach dem Schreiben muss der TRV den Sollwert zeigen (Blueprint „TRV Write Failed“)
            sent = self.control.trv_writes.get(rcfg[F_CLIMATE])
            if sent and now - sent[0] >= TRV_READBACK_S:
                if abs(r_in.current_setpoint - sent[1]) <= 0.5:
                    self.control.trv_writes.pop(rcfg[F_CLIMATE])
                else:
                    out["rooms"][rid]["problem"] = "room_write_failed"

        if not state.available:
            # Master weg (z. B. Cloud aus): Räume mit TRV trotzdem regeln – Fenster-/Sommer-Minimum (HEATING-17)
            out["problem"] = "master_unavailable"
            await self._write_rooms(out, g, now)
            return out

        lim = self.adapter.limits(master_entity)
        if cid in self.control.disabled:
            return await self._disabled(master_entity, state, lim, out, g, now)
        win = self._window(ccfg.get(F_WINDOW), now)
        any_window = any(
            self._on(w) for w in [ccfg.get(F_WINDOW), *(r.get(F_WINDOW) for r in self.rooms(cid).values())] if w
        )
        current = self._num(ccfg.get(F_TEMP))
        if current is None:
            current = state.current
        if current is None:
            # Keine Ist-Temperatur am Master: dort nicht raten, die Räume aber weiter regeln.
            out["problem"] = "temperature_unknown"
            await self._write_rooms(out, g, now)
            return out
        plan = self._gentle_schedule(ccfg.get(F_SCHEDULE), now) if lim.gentle else ("on" if self._on(ccfg.get(F_SCHEDULE)) else None)
        m_schedule = plan is not None
        m_in = MasterInput(
            comfort=self._comfort(ccfg, cid),
            current_temp=current,
            set_now=state.setpoint or 0.0,
            schedule_on=m_schedule,
            presence_on=m_presence,
            pre_heat_on=c_pre,
            has_demand_source=bool(ccfg.get(F_SCHEDULE) or ccfg.get(F_PRESENCE)),
            window_open_too_long=win.open_too_long,
            any_window_open=any_window,
            min_temp=lim.min_temp,
            max_temp=lim.max_temp,
            modulating=lim.modulating,
            boost_enabled=bool(self.opt(OPT_BOOST_ENABLED)),
            boost_amount=float(self.opt(OPT_BOOST_AMOUNT)),
            boost_threshold=float(self.opt(OPT_BOOST_THRESHOLD)),
            weather_enabled=bool(self.opt(OPT_WEATHER_ENABLED)) and not lim.modulating,  # Heizkurve der Anlage kompensiert selbst (HEATING-21)
            outdoor_temp=self._num(self.opt(OPT_OUTDOOR_SENSOR)),
            weather_zones=(
                float(self.opt(OPT_WEATHER_ZONE1)),
                float(self.opt(OPT_WEATHER_ZONE2)),
                float(self.opt(OPT_WEATHER_ZONE3)),
            ),
            humidity_enabled=bool(self.opt(OPT_HUMIDITY_ENABLED)),
            humidity=self._num(ccfg.get(F_HUMIDITY)),
            humidity_drop=float(self.opt(OPT_HUMIDITY_DROP)),
            room_demand_delta=float(self.opt(OPT_ROOM_DEMAND_DELTA)) if lim.gentle else 0.0,
        )
        m_res = master_target(g, m_in, isolated)
        if state.room_sensor_off and any(res.active and res.needs_heat for _, res in isolated):
            # Raumfühler der Anlage sperrt den Kreis, obwohl ein Raum Wärme braucht: an der Anlage umstellen (HEATING-29)
            out["problem"] = "room_sensor_blocks"
            # Prominent unter Einstellungen → Reparaturen, mit Anleitung; bleibt bis zur Bestätigung (repairs.py)
            ir.async_create_issue(self.hass, DOMAIN, f"room_sensor_blocks_{cid}", is_fixable=True,
                                  severity=ir.IssueSeverity.WARNING, translation_key="room_sensor_blocks",
                                  translation_placeholders={"circuit": ccfg[F_NAME]})
        out.update(target=m_res.target, state=m_res.state, set_now=state.setpoint, presence=m_presence, window_open=win.open_too_long, pump_on=state.pump_on,
                   current=current, budget_left=None, mode=_circuit_mode(m_res, m_in, g))
        if plan in ("lead", "skip"):
            # Komfort früher bzw. kurze Absenkung übersprungen: auf der Seite erklären (HEATING-30)
            out["plan_hint"] = plan
            if plan == "lead" and out["mode"] == "schedule":
                out["mode"] = "pre_heat"

        for rid, rcfg in followers:
            t = follower_target(g, m_res.target_before_mods, float(rcfg.get(F_OFFSET, -2.0)), self._window(rcfg.get(F_WINDOW), now).open_too_long)
            out["rooms"][rid] = {"name": rcfg[F_NAME], "mode": "follower", "target": t, "entity": rcfg[F_CLIMATE], "setpoint": self._attr(rcfg[F_CLIMATE], "temperature")}

        writes = self.control.writes.setdefault(cid, [])
        # Ereignis seit dem letzten Write (Abwesend, Sommer, Fenster/Minimum, Vorheizen) hebt die Haltezeit auf
        events = (g.away_effective, g.summer, m_res.forced_min, m_in.pre_heat_on)
        event_changed = cid in self.control.write_events and self.control.write_events[cid] != events
        hold_s = GENTLE_HOLD_S if lim.gentle else 0.0
        held = bool(writes) and now - writes[-1].ts < hold_s and not event_changed
        dec = decide(
            now=now,
            target=m_res.target,
            set_now=state.setpoint,
            writes=writes,
            cfg=WriteConfig(budget_per_hour=int(self.opt(OPT_BUDGET)), confirm_delay_s=lim.confirm_delay_s, budget_limited=lim.write_budget,
                            hysteresis=max(g.hysteresis, GENTLE_MIN_HYSTERESIS) if lim.gentle else g.hysteresis,
                            min_hold_s=hold_s, symmetric_hysteresis=lim.gentle),
            bypass=event_changed,
            forced_min=m_res.forced_min,
            away=g.away_effective,
            renew_due=state.renew_due,
            startup_done=self._settled(now),
        )
        if state.heating_off and not m_res.forced_min:
            # Kreis von der Anlage selbst abgeschaltet: nicht übersteuern.
            dec = Decision(False, "none", "circuit_off")
            out["mode"] = "circuit_off"
        out["decision"] = dec.reason
        out["budget_total"] = WriteConfig(budget_per_hour=int(self.opt(OPT_BUDGET))).budget if lim.write_budget else None
        out["budget_left"] = (max(0, WriteConfig(budget_per_hour=int(self.opt(OPT_BUDGET))).budget - len([w for w in writes if now - w.ts < 3600]))
                              if lim.write_budget else None)
        out["would_write"] = dec.write
        # Variante B: läuft die Anlage noch im eigenen Zeitprogramm, einmal übernehmen
        takeover = getattr(self.adapter, "needs_takeover", None)
        takeover = (bool(takeover and takeover(master_entity, m_res.target)) and not state.heating_off and not held
                    and self._settled(now))
        if (dec.write or takeover) and self.control.write_enabled:
            await self.adapter.write_setpoint(master_entity, m_res.target)
            self._events.append(f"{ccfg[F_NAME]}: {_de(state.setpoint)} → {_de(m_res.target)} °C ({MODE_TEXT.get(out['mode'], out['mode'])})")
            writes.append(Write(now, m_res.target, dec.kind))
            del writes[:-20]
            self.control.write_events[cid] = events

        await self._write_rooms(out, g, now)
        return out

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.control.summer_off = set(data.get("summer_off", []))
        self.control.disabled = set(data.get("disabled", []))

    async def _save(self) -> None:
        await self._store.async_save({"summer_off": sorted(self.control.summer_off), "disabled": sorted(self.control.disabled)})

    def _boiler(self, master_entity: str | None) -> dict | None:
        """Kesseldaten der Hersteller-Integration; neue Meldung der Anlage -> Push (HEATING-21)."""
        boiler = getattr(self.adapter, "boiler", None)
        info = boiler(master_entity) if boiler and master_entity else None
        if info and info.get("message_time"):
            if self._last_message is not None and info["message_time"] != self._last_message and info.get("message"):
                self._events.append(f"Kessel meldet: {info['message']}")
            self._last_message = info["message_time"]
        return info

    async def _auto_summer(self, now: float) -> None:
        """Sommer/Winter aus dem 72-h-Außenmittel am Sommer-Schalter (input_boolean) setzen, wie der Blueprint (HEATING-32).
        Nur bei aktivem Schreiben: im Schattenbetrieb schaltet noch der Blueprint."""
        switch_id = self.opt(OPT_SUMMER_ENTITY)
        if not switch_id or not str(switch_id).startswith("input_boolean.") or not self.opt(OPT_SUMMER_MEAN_SENSOR):
            return
        want = summer_switch(self._on(switch_id), self._num(self.opt(OPT_SUMMER_MEAN_SENSOR)), float(self.opt(OPT_SUMMER_LIMIT)))
        if want is None or not self.control.write_enabled or now - self._started < STARTUP_GUARD_S:
            return
        await self.hass.services.async_call("input_boolean", "turn_on" if want else "turn_off", {"entity_id": switch_id}, blocking=True)
        self._events.append("Sommer erkannt – Heizung aus" if want else "Heizsaison erkannt – Heizung an")

    def _gentle_schedule(self, entity_id: str | None, now: float) -> str | None:
        """Träger Kessel (HEATING-19): "on" = Zeitplan an, "lead" = Komfort vor dem Zeitplan (Vorlauf, Option),
        "skip" = Absenkphase unter 3 h übersprungen, None = Absenkung."""
        if not entity_id:
            return None
        if self._on(entity_id):
            return "on"
        st = self.hass.states.get(entity_id)
        nxt = dt_util.parse_datetime(str(st.attributes.get("next_event"))) if st and st.attributes.get("next_event") else None
        if nxt is None:
            return None
        remaining = nxt.timestamp() - now
        if 0 <= remaining <= float(self.opt(OPT_PRE_HEAT_LEAD)) * 3600:
            return "lead"
        # Nur überspringen, wenn Heating Core den Wechsel auf „aus“ selbst gesehen hat: nach einem HA-Neustart steht
        # last_changed auf dem Neustart, und eine lange Nachtabsenkung sähe sonst kurz aus (HEATING-39)
        if 0 < nxt.timestamp() - st.last_changed.timestamp() < GENTLE_SHORT_SETBACK_S and st.last_changed.timestamp() > self._started:
            return "skip"
        return None

    async def _summer(self, master_entity: str, ccfg: dict, g: Globals, now: float) -> None:
        """Vaillant: im Sommer Therme aus, danach Betriebsart zurück – nur, wenn Heating Core sie ausgeschaltet hat."""
        summer = getattr(self.adapter, "summer", None)
        if not summer or not self.control.write_enabled or now - self._started < STARTUP_GUARD_S:
            return
        if g.summer:
            if master_entity not in self.control.summer_off:
                await summer(master_entity, True, None)
                self.control.summer_off.add(master_entity)
                await self._save()
                self._events.append(f"{ccfg[F_NAME]}: Sommer – Heizung aus")
        elif master_entity in self.control.summer_off:
            await summer(master_entity, False, ccfg.get(F_HVAC_MODE) or "heat_cool")
            self.control.summer_off.discard(master_entity)
            await self._save()
            self._events.append(f"{ccfg[F_NAME]}: Sommer vorbei – Heizung wieder an")

    async def _write_rooms(self, out: dict[str, Any], g: Globals, now: float) -> None:
        """TRV-Sollwerte schreiben; ein Fehler bei einem Raum stoppt die anderen nicht."""
        if not self.control.write_enabled or not self._settled(now):
            return
        for room in out["rooms"].values():
            if room.get("entity") is None:
                continue
            await self._tune_trv(room, now)
            tgt, cur = room.get("target"), room.get("setpoint")
            if tgt is not None:  # auf die Schrittweite des TRV (Moes: ganze Grad), sonst schreibt er jedes Mal neu
                tgt = trv_tools.step_round(tgt, self._attr(room["entity"], "target_temp_step"))
            if tgt is None or (cur is not None and abs(tgt - cur) <= g.hysteresis):
                continue
            try:
                await self.hass.services.async_call(
                    "climate", "set_temperature", {"entity_id": room["entity"], "temperature": tgt}, blocking=True
                )
                self.control.trv_writes[room["entity"]] = (now, tgt)
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("Thermostat %s: Sollwert %s nicht geschrieben: %s", room["entity"], tgt, err)
                room["problem"] = "room_write_failed"

    async def set_disabled(self, cid: str, off: bool) -> None:
        """Heizkreis ganz aus/an (HEATING-27); Zustand übersteht Neustarts."""
        (self.control.disabled.add if off else self.control.disabled.discard)(cid)
        self.control.writes[cid] = []  # keine Haltezeit nach dem Wiedereinschalten
        await self._save()
        await self.async_request_refresh()

    async def _disabled(self, master_entity: str, state, lim, out: dict[str, Any], g: Globals, now: float) -> dict[str, Any]:
        """Kreis ausgeschaltet: Anlage aus (Ökofen „aus“, Frostschutz der Anlage bleibt), Räume auf das TRV-Minimum."""
        out.update(mode="disabled", state="disabled", target=None, set_now=state.setpoint, current=state.current,
                   decision="disabled", pump_on=state.pump_on)
        for room in out["rooms"].values():
            if room.get("entity"):
                room.update(target=g.min_trv, mode="disabled")
        if self.control.write_enabled and now - self._started >= STARTUP_GUARD_S:
            try:
                off = getattr(self.adapter, "turn_off", None)
                if off:
                    await off(master_entity)
                elif state.setpoint is None or abs(state.setpoint - lim.min_temp) > 0.1:
                    await self.adapter.write_setpoint(master_entity, lim.min_temp)
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("%s: Ausschalten fehlgeschlagen: %s", out.get("name"), err)
        await self._write_rooms(out, g, now)
        return out

    def _companions(self, climate: str) -> list[str]:
        """Alle Entitäten am selben Gerät wie der TRV (Kalibrierung, externer Fühler, Eco-Schalter)."""
        reg = er.async_get(self.hass)
        ent = reg.async_get(climate)
        if ent is None or ent.device_id is None:
            return []
        return [e.entity_id for e in er.async_entries_for_device(reg, ent.device_id)]

    async def _tune_trv(self, room: dict, now: float) -> None:
        """TRV gehorchen lassen und mit dem Raumfühler abgleichen (HEATING-16)."""
        climate = room["entity"]
        st = self.hass.states.get(climate)
        if st is None or st.state in ("unavailable", "unknown"):
            return
        others = self._companions(climate)
        try:
            eco = trv_tools.pick(others, trv_tools.ECO_SUFFIXES)
            if eco and self._on(eco):
                await self.hass.services.async_call("switch", "turn_off", {"entity_id": eco}, blocking=True)
            presets = st.attributes.get("preset_modes") or []
            if "manual" in presets and st.attributes.get("preset_mode") not in ("manual", None):
                await self.hass.services.async_call("climate", "set_preset_mode", {"entity_id": climate, "preset_mode": "manual"}, blocking=True)
            sensor = self._num(room.get("sensor"))
            if sensor is None:
                return  # ohne Raumfühler bleibt die Kalibrierung, wie sie am TRV steht
            ext = trv_tools.pick(others, trv_tools.EXT_SUFFIXES)
            last = self.control.trv_tuned.get(climate, 0.0)
            if ext:
                old = self._num(ext)
                if now - last >= trv_tools.EXT_INTERVAL_S and (old is None or abs(old - sensor) > trv_tools.EXT_THRESHOLD):
                    await self.hass.services.async_call("number", "set_value", {"entity_id": ext, "value": round(sensor, 1)}, blocking=True)
                    self.control.trv_tuned[climate] = now
                return
            cal = trv_tools.pick(others, trv_tools.CAL_SUFFIXES)
            shown, cal_now = _float(st.attributes.get("current_temperature")), self._num(cal)
            if not cal or shown is None or cal_now is None or now - last < trv_tools.CAL_INTERVAL_S:
                return
            a = self.hass.states.get(cal).attributes
            new = trv_tools.new_calibration(sensor, shown, cal_now, float(a.get("min", -9)), float(a.get("max", 9)), float(a.get("step", 1)))
            if new is not None:
                await self.hass.services.async_call("number", "set_value", {"entity_id": cal, "value": new}, blocking=True)
                self.control.trv_tuned[climate] = now
                _LOGGER.info("%s: Thermostat abgeglichen, Kalibrierung %+.0f → %+.0f °C", room.get("name"), cal_now, new)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Thermostat %s: Abgleich fehlgeschlagen: %s", climate, err)

    async def _floor_circuit(self, cid: str, ccfg: dict, g: Globals, now: float) -> dict[str, Any]:
        """Fußboden mit eigener Pumpe und Ventil-Kanälen (Sonderfall Perg)."""
        out: dict[str, Any] = {"name": ccfg[F_NAME], "rooms": {}, "available": True, "target": None}
        zones: list[Zone] = []
        valves_by_zone: dict[str, list[str]] = {}
        c_pre = self._pre_heat(cid, now, self._on(ccfg.get(F_SCHEDULE)), ccfg.get(F_PRE_HEAT_ENTITY))
        for rid, rcfg in self.rooms(cid).items():
            if rcfg.get(F_ROLE) == ROLE_PASSIVE:
                out["rooms"][rid] = self._passive(rcfg)
                continue
            valves = rcfg.get(F_VALVES) or []
            valves_by_zone[rid] = valves
            readings = [self._reading(v) for v in valves]
            open_now = bool(valves) and all(r.state == "on" for r in readings)
            open_since = max(r.since for r in readings) if open_now else None
            temp = self._num(rcfg.get(F_TEMP))
            win = self._window(rcfg.get(F_WINDOW), now)
            presence_on = self._presence(rid, rcfg.get(F_PRESENCE) or [], now)
            sched = self.schedule(rcfg)
            schedule_on = self._on(sched)
            target, _active = room_base(replace(g, eco=self.setback(rid, g.eco)), RoomInput(
                comfort=self._comfort(rcfg, rid), current_temp=temp or 0.0, current_setpoint=0.0,
                schedule_on=schedule_on, presence_on=presence_on,
                pre_heat_on=c_pre,
                has_demand_source=bool(sched or rcfg.get(F_PRESENCE)),
                window_open_too_long=win.open_too_long,
            ))
            if cid in self.control.disabled:
                target = g.min_trv  # Kreis ausgeschaltet: nur noch Frostschutz (HEATING-27)
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
        if switches and self.control.write_enabled and self._settled(now):
            for entity_id, on in switches:
                await self.hass.services.async_call(
                    "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
                )
            self._events.append(f"{ccfg[F_NAME]}: " + ", ".join(f"{e.split('.')[-1]} {'an' if on else 'aus'}" for e, on in switches))
        return out

    def _passive(self, rcfg: dict) -> dict[str, Any]:
        """Heizkörper ohne TRV (HEATING-38): wird vom Heizkreis mitversorgt, nur Anzeige, keine Regelung."""
        return {"name": rcfg[F_NAME], "mode": ROLE_PASSIVE, "target": None, "current": self._num(rcfg.get(F_TEMP)), "passive": True}

    def _room_input(self, rid: str, rcfg: dict, now: float, circuit_pre_heat: bool = False) -> RoomInput | None:
        climate = rcfg.get(F_CLIMATE)
        st = self.hass.states.get(climate) if climate else None
        if st is None or st.state in ("unavailable", "unknown"):
            return None
        current = self._num(rcfg.get(F_TEMP)) or _float(st.attributes.get("current_temperature"))
        if current is None:
            return None
        win = self._window(rcfg.get(F_WINDOW), now)
        r_presence = self._presence(rid, rcfg.get(F_PRESENCE) or [], now)
        sched = self.schedule(rcfg)
        r_schedule = self._on(sched)
        return RoomInput(
            comfort=self._comfort(rcfg, rid),
            current_temp=current,
            current_setpoint=_float(st.attributes.get("temperature")) or 0.0,
            schedule_on=r_schedule,
            presence_on=r_presence,
            pre_heat_on=circuit_pre_heat,
            has_demand_source=bool(sched or rcfg.get(F_PRESENCE)),
            window_open_too_long=win.open_too_long,
            window_closed_recently=win.closed_recently,
            needed_heat=self.control.needs_heat.get(rid, False),
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
    return "eco"
