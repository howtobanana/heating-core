# Heating Core – Konzept

Stand 08.11.2026 · Karte HEATING-1 · Entwurf, wartet auf Fabians Freigabe

## 1. Ziel und Grundsätze

Eine eigene Home-Assistant-Integration (HACS), die die Heizung eines Hauses
steuert: eine gemeinsame Logik für alle Hersteller, dazu ein schmaler Adapter
je Hersteller. Zuerst Vaillant (Wien), danach Ökofen (Perg).

Grundsätze (Entscheidungen Fabian, 08.11.2026):

- Erst die allgemeine Logik, dann Vaillant, wenn alles läuft Ökofen.
- Keine Funktion des Vaillant-Blueprints fällt weg (Follower, Räume, Leitstand).
- Einführung im Schattenbetrieb: rechnen, nicht schreiben, mit dem Blueprint vergleichen.
- Privat, bis Vaillant stabil läuft; dann öffentlich über HACS.

Weitere Regeln:

- Die Logik kennt keine Hersteller-Entitäten, nur die Adapter-Schnittstelle.
- Jede Regel der Logik hat einen Test (pytest), bevor sie in Wien läuft.
- Sicher im Zweifel: Ist ein Wert unbekannt, wird nicht geschrieben (kein Raten wie
  „21 °C als Fallback“).

## 2. Datenmodell

```
Anlage (eine Config-Entry je Haus, ein Hersteller)
├── globale Einstellungen: Eco, Abwesend, Gast, Sommer, Budget, Holds, Hysterese
└── Heizkreis 1..n            (Vaillant: Zone; Ökofen: HK1, HK2 …)
    ├── Typ: Heizkörper | Fußboden   → Trägheit, Hysterese, Vorheizzeit
    ├── Master-Raum (führt den Kreis-Sollwert)
    ├── Räume 0..n  (eigenes TRV, Präsenz, Zeitplan, Fenster, Pre-Heat, Komfort)
    ├── Follower 0..n (TRV folgt Master mit Offset)
    └── FBH-Zonen 0..n (Ventil-Schalter, Raumsensor, Komfort; Rohrtemperatur-Grenze)
```

Räume und Follower sind Listen, keine festen Blöcke: beliebig viele, in der
Oberfläche hinzufügen und entfernen (Subentries). Damit entfallen die Kopien
„Raum 1–5“ aus dem Blueprint, ohne eine Funktion zu verlieren.

## 3. Kernlogik (aus dem Blueprint übernommen)

| Bereich | Verhalten | Herkunft |
|---|---|---|
| Bedarf | Komfort bei Zeitplan, Präsenz (mit Aktivierungs-/Nachlaufzeit), manuell, Pre-Heat; sonst Eco | Blueprint |
| Abwesend / Gast | Abwesend → Away-Temp für Master und Räume; Gast hebt Abwesend auf; Pre-Heat schlägt Abwesend | Blueprint |
| Räume → Master | Master-Soll = max(Master-Bedarf, Räume mit echtem Wärmebedarf); Master-Priorität optional | Blueprint |
| Bang-Bang mit Deadband | Ein/aus über Hysterese, kein Pendeln | Blueprint |
| Fenster | offen > Verzögerung → TRV-Minimum; nach Schließen Settling; Smart-Drop bei Temperatursturz | Blueprint |
| Boost | Raum/Master zu kalt → Aufschlag, mit Abschalt-Hysterese | Blueprint |
| Gebäude-Kompensation | Aufschlag nach Außentemperatur (oder Sensor), **nicht bei Abwesenheit** | VAILLANT-4 |
| Feuchte-Kompensation | Absenkung bei > 60 % rF | Blueprint |
| Sommer | 72-h-Mittel mit ±1,5 °C Hysterese → Heizung aus, TRVs Minimum | Blueprint |
| Anti-Takt | Holds nach Raise/Drop, Mindestlaufzeit (Ökofen) | Blueprint / Ökofen-Entwurf |
| Schreib-Budget | N Writes je 60 min, gleicher Wert nicht doppelt, solange die Rückmeldung aussteht | VAILLANT-5 |
| Startschutz | nach HA-Start erst schreiben, wenn Sensoren Werte haben | Blueprint |

Nicht mehr nötig in der Integration: Präsenz-Helfer, Write-Log-Textfeld,
3-Minuten-Takt mit `mode: restart`. Die Integration hört auf Zustandsänderungen
und rechnet nur bei Bedarf neu (plus ein Sicherheitslauf alle 5 min).

## 4. Adapter-Schnittstelle

Jeder Hersteller liefert eine Klasse mit diesen Fähigkeiten:

```python
class HeatingAdapter(Protocol):
    def circuits(self) -> list[CircuitInfo]: ...            # Kreise, Typ, Name
    def read(self, circuit) -> CircuitState: ...            # Soll, Ist, Betrieb, an/aus, letzte Bestätigung
    async def write_setpoint(self, circuit, value) -> None: ...
    async def set_heating(self, circuit, on: bool) -> None: ...  # Sommer-Aus
    async def ensure_mode(self, circuit) -> None: ...       # gewünschte Betriebsart herstellen
    def limits(self) -> AdapterLimits: ...                  # min/max, Schrittweite, Rate-Limit, Bestätigungs-Verzögerung
```

Die Logik entscheidet **was** (Soll je Kreis), der Adapter **wie**.

### Vaillant (myVaillant)

- Sollwert: `climate.set_temperature` auf die Zone.
- Betriebsart: Handbetrieb (`heat_cool` = MANUAL) empfohlen, Sollwert ohne Ablauf.
  Im Zeitprogramm-Betrieb (`auto`) ist jeder Sollwert eine Quick-Veto; der Adapter
  erneuert sie vor `quick_veto_end_date_time` (Lehre aus VAILLANT-2).
- Sommer: HVAC `off`, danach zurück in die gewählte Betriebsart.
- Cloud meldet Änderungen bis zu 30 min verzögert → Bestätigungs-Verzögerung 30 min.
- Räume: Zigbee-TRVs (`climate.*`), direkt geschrieben.

### Ökofen (oekofen-pellematic-compact)

- Perg: HK1 „Heizung OG“, HK2 „Heizung UG“.
- Sollwert: `number.pellematic_heating_circuit_N_remote_override` (Offset in K,
  begrenzt), alternativ `*_temp_heat` / `*_temp_setback`.
- Betriebsart: `select.pellematic_heating_circuit_N_mode_auto` (auto/heizen/absenken/aus).
- Pelletkessel: Mindestlaufzeit, längere Holds, größere Hysterese.
- Fußboden (Entwurf): Zonen mit Ventil-Schalter (`switch.*`), Raumsensor,
  Rohrtemperatur-Grenze (Estrichschutz, alle Ventile zu bei Überschreitung).

## 5. Entitäten der Integration

Je Anlage: `switch` Abwesend, `switch` Gast, `switch` Schreiben aktiv
(Schattenbetrieb = aus), `sensor` Status (Grund in Attributen), `sensor`
Schreib-Budget, `binary_sensor` Problem (ersetzt die HA-Meldung), Diagnose-Download.

Je Kreis: `sensor` berechneter Sollwert, `sensor` Modus (Komfort/Eco/Abwesend/
Fenster/Sommer/Boost), `binary_sensor` Wärmebedarf.

Je Raum: `sensor` Ziel, `sensor` Modus, `binary_sensor` Präsenz (entprellt),
`switch` Pre-Heat.

Der Leitstand (Normal, Expert) wird zu einem Dashboard aus diesen Entitäten;
Push optional über eine Benachrichtigungs-Einstellung.

## 6. Einrichtung (Config Flow)

1. Hersteller wählen, Master-Entität(en) wählen → Kreise werden erkannt.
2. Globale Werte (Eco, Abwesend, Gast, Sommer-Sensor, Budget).
3. Räume, Follower und FBH-Zonen je Kreis als Subentries hinzufügen.
4. Alles später über „Optionen“ änderbar, ohne Neustart.

Übernahme aus dem Blueprint: ein Import-Schritt liest die Eingaben der
bestehenden Automation und füllt die Felder vor.

## 7. Schattenbetrieb und Umschaltung

- Schalter „Schreiben aktiv“ aus: Die Integration rechnet und zeigt, was sie
  schreiben würde; ein Vergleichs-Sensor stellt ihr Soll dem Blueprint-Soll gegenüber.
- Umschalten (HEATING-5): Blueprint-Automation aus, „Schreiben aktiv“ an.
  Rückweg in beide Richtungen ohne Datenverlust.

## 8. Tests und Qualität

- pytest mit `pytest-homeassistant-custom-component`; die Logik als reine Funktionen
  (Eingaben → Soll), dadurch ohne HA testbar.
- Je Regel aus Abschnitt 3 mindestens ein Test, dazu die realen Fälle aus
  VAILLANT-2 bis -6 als Regressionstests.
- GitHub Actions: Tests, hassfest, HACS-Prüfung.
- Testumgebung: HA im Docker auf Unraid (`dev-unraid.sh`), keine Tests auf dem Mac.

## 9. Nicht im Umfang

Geofencing, Lüftung, System-Diagnose bleiben vorerst Blueprints (Entscheidung
offen in HEATING-3). Warmwasser wird nicht gesteuert.

## 10. Offene Fragen an Fabian

1. **Fußbodenheizung Perg:** In HA Perg gibt es einen Controller mit vier Ventil-
   Kanälen (`switch.coordinator_fussbodenheizung_l1` … `l4`); der Ökofen-Entwurf
   kennt nur drei Zonen. Welcher Kanal ist welcher Raum, und aus welchem Kreis
   (HK1 OG / HK2 UG) wird die FBH gespeist? Gibt es den Rohrtemperatur-Sensor schon?
2. **Räume Perg:** Welche Räume und TRVs gehören zu HK1 (OG) und HK2 (UG)?
   In HA Perg ist bisher ein Zigbee-TRV (`climate.0xa4c138351b5c1ab7`) eingebunden.
3. **Ökofen-Sollwert:** Steuern über den Offset `remote_override` (Empfehlung,
   die Kessellogik bleibt aktiv) oder direkt über `temp_heat`/`temp_setback`?
4. **Mindest-HA-Version:** Empfehlung 2026.10 (Wien und Perg laufen auf 2026.10.4), ältere nicht unterstützen.
5. **Name in HACS / Domain:** `heating_core` („Heating Core“) – passt das?
