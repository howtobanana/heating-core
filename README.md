# Heating Core Blueprints

Herstellerunabhängige Heizungslogik für Home Assistant als ein Blueprint.
Eine Einstellung „Hersteller“ wählt nur die gerätespezifischen Teile
(Sollwert schreiben, Betriebsart, Sommer-Aus).

## Hersteller
- Vaillant (myVaillant) – Basis, aus `howtobanana/vaillant-suite-blueprints`
- Ökofen (Pellematic) – folgt, wenn Vaillant auf dem Kern läuft

## Struktur
- `blueprints/` Blueprints
- `docs/` Doku und Changelog
