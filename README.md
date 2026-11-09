# Heating Core

Eigene Home-Assistant-Integration (HACS) für die Heizungssteuerung: eine
gemeinsame Logik für Räume, Präsenz, Fenster, Abwesenheit, Sommer und
Schreib-Budget, dazu ein Adapter je Hersteller.

## Hersteller
- Ökofen (Pellematic, Integration `oekofen-pellematic-compact`) – läuft in Perg
- Vaillant (myVaillant) – in Wien im Schattenbetrieb neben dem Blueprint `howtobanana/vaillant-suite-blueprints`

## Ökofen: Einstellungen an der Pellematic

Diese Punkte lassen sich weder über die Ökofen-Integration noch über Heating Core
ändern, nur am Display der Pellematic, in der Ökofen-App oder auf my.oekofen.com.
Fehlt eine Einstellung im Menü, liegt sie in der Fachmann-Ebene (Code beim Installateur).

| Einstellung | Wo | Empfehlung | Warum |
|---|---|---|---|
| Raumfühler / Raumeinfluss | je Heizkreis | **aus bzw. 0**, sobald der Kreis mehrere Räume mit TRVs versorgt | Sonst schaltet die Pellematic den ganzen Kreis ab („Raumtemperatur erreicht“), sobald der Raum mit ihrem Fühler warm ist – die anderen Räume bleiben kalt, obwohl ihre Ventile offen sind. Heating Core meldet das als Problem „Raumfühler der Pellematic schaltet den Kreis ab“. |
| Heizkurve | je Heizkreis | so niedrig, dass die Räume gerade noch warm werden | Die Heizkurve ist die Gebäude-Kompensation; Heating Core rechnet bei Ökofen nichts dazu. Niedriger Vorlauf = Brennwert nutzen, weniger Takten. |
| Heiz- und Absenktemperatur | je Heizkreis | nahe an Komfort bzw. Absenkung aus Heating Core | Heating Core schreibt nur Betriebsart (heizen/absenken) und einen Offset von höchstens ±3 ganzen Grad auf diese Werte. Ziele weiter weg erreicht die Pellematic nicht. |
| Ökomodus | je Heizkreis | **aus** | Er verschiebt die Heizgrenze selbst und regelt damit gegen Heating Core. |
| Zeitprogramm | je Heizkreis | egal | Solange Heating Core schreibt, steht der Kreis auf „heizen“/„absenken“ und das Zeitprogramm der Pellematic ruht. Bei „Schreiben aus“ geht der Kreis auf „auto“ zurück und das Zeitprogramm gilt wieder. |
| Warmwasser mit Kesselwärme | Warmwasser | **an** (auch als Knopf auf der Seite „Heizung“) | Lädt das Warmwasser mit der Restwärme nach einem Heizlauf – spart Brennerstarts. |

Zeitpläne, Absenkung, Abwesend, Fenster und „Heizkreis aus“ kommen aus Heating Core,
nicht aus der Pellematic.

## Stand
Perg (Ökofen) wird von Heating Core gesteuert, Wien (Vaillant) läuft im Schattenbetrieb.
Privat, bis beides stabil läuft (HEATING-7).
