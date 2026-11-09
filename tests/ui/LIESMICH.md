# Screenshots der Seite „Heizung“

Rendert `frontend/heating-core-panel.js` mit einem nachgebauten `hass` in Playwright auf Unraid (kein Browser am Mac).

```bash
node tests/ui/build.mjs > /tmp/heizung.mjs && ~/Developer/_werkzeuge/ui-test-unraid.sh /tmp/heizung.mjs tests/ui/out
```

Ergebnis: Desktop und Handy, je hell und dunkel. `perg.json` ist ein Abzug aus HA Perg
(Template über `integration_entities('heating_core')`, `key` = translation_key der Entität).

Zeitplan-Editor (HEATING-20) geöffnet zeigen:

```bash
node tests/ui/build.mjs tests/ui/perg.json tests/ui/zeitplan.js > /tmp/zeitplan.mjs && ~/Developer/_werkzeuge/ui-test-unraid.sh /tmp/zeitplan.mjs tests/ui/out
```

Heizkreis ausgeschaltet (HEATING-27): `node tests/ui/build.mjs tests/ui/perg.json tests/ui/aus.js`
