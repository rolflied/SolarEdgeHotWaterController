# Konzept: Anbindung an evcc

Stand: 15.10.2026. Geprüft gegen evcc **0.317.1** (aktuelles Release) und den
`master`-Zweig von evcc-io/evcc sowie Home Assistant **2026.10** (Mindestversion
der Integration).

Ziel: evcc soll den SolarEdge Hot Water Controller (HWC) als **Heizgerät** über
Home Assistant stufenlos mit PV-Überschuss steuern. Die Integration stellt dafür
alles bereit, sodass in evcc möglichst nur noch Entitäten ausgewählt (oder ein
fertiger YAML-Block eingefügt) werden müssen.

Getroffene Entscheidungen:

| Frage | Entscheidung |
|-------|--------------|
| evcc schaltet ab | Heizstab **aus** (`MANUAL`, Level 0). Die SolarEdge-eigene Überschusslogik konkurriert nicht mit evcc. |
| Aktivierung | Schalter **„evcc-Steuerung bereitstellen“ im Optionsdialog**. Erst dann werden die evcc-Entitäten angelegt. |
| Sicherheitsnetz | evcc-Befehle laufen mit **Laufzeit** (Watchdog) und werden erneuert. |

---

## 1. Was evcc erwartet

### 1.1 Passendes evcc-Template: `homeassistant` (Gerätetyp „Wallbox“/Heizgerät)

evcc bringt zwei Home-Assistant-Templates mit:

| Template | Steuerung | Eignung für den HWC |
|----------|-----------|---------------------|
| `homeassistant-switch` (Typ `switchsocket`) | nur Ein/Aus mit fester Leistung | ungeeignet: der HWC kann stufenlos 1–100 % und würde so nur volle Leistung oder nichts nutzen |
| **`homeassistant`** (Typ `homeassistant`) | Ein/Aus **und Strom in A** | **geeignet**: evcc regelt den Strom, die Integration rechnet ihn in Level % um |

Parameter des Templates `homeassistant` (aus `templates/definition/charger/homeassistant.yaml`
und `charger/homeassistant.go`):

| Parameter | Pflicht | Angebotene HA-Domains / Einheit | Bedeutung für evcc |
|-----------|---------|--------------------------------|--------------------|
| `uri` | ja | per mDNS gefundene HA-Instanzen | Adresse von Home Assistant |
| `status` | ja | `sensor`, `binary_sensor` | Ladestatus A/B/C |
| `statusA/B/C` | nein (erweitert) | – | zusätzliche Zustandstexte je Status |
| `enabled` | ja | `sensor`, `binary_sensor`, `switch` | ist das Gerät freigegeben? (`on`/`off`, `true`/`false`, …) |
| `enable` | ja | `switch`, `input_boolean` | Freigabe schalten (`turn_on`/`turn_off`) |
| `setMaxCurrent` | ja | `number`, `input_number`, Einheit **A** | Strom vorgeben (`number.set_value`) |
| `milliamps` | nein (erweitert) | – | Strom in 0,1-A-Schritten statt ganzen Ampere (ab evcc 0.316) |
| `power` | nein | `sensor`, Einheit W/kW | aktuelle Leistung |
| `energy` | nein | `sensor`, Einheit Wh/kWh/MWh | Zählerstand |
| `temp` | nein | `sensor`, `input_number`, Einheit °C/°F/K | Temperatur, bei Heizgeräten als „SoC“ angezeigt (**nur evcc nightly**, PR evcc-io/evcc#34614, noch nicht in 0.317.1) |
| `currentL1..3`, `voltageL1..3` | nein | `sensor`, A bzw. V | Phasenwerte (für den HWC nicht nötig) |
| `phaseswitch` | nein | `select` | Phasenumschaltung (nicht nötig) |
| `heating` | nein (erweitert) | – | Feature `heating`: UI zeigt „Heizen“ und °C, Temperatur statt SoC |
| `integrateddevice` | nein (erweitert) | – | Feature `integrateddevice`: immer „verbunden“, kein Fahrzeug, keine Ladesitzungen |

### 1.2 Wie evcc mit Home Assistant spricht

- **Erkennung:** evcc sucht per mDNS (`_home-assistant._tcp`) nach HA-Instanzen
  (`util/homeassistant/zeroconf.go`) und bietet sie im Konfigurationsdialog an.
- **Anmeldung:** OAuth2 gegen `/auth/authorize` bzw. `/auth/token` von HA
  (`util/homeassistant/oauth2.go`), d. h. Login mit einem HA-Benutzer im Browser,
  **kein Long-Lived-Token** mehr nötig. Voraussetzung: in evcc ist eine
  erreichbare externe URL (`network` → externe URL) gesetzt, sie dient als
  `client_id` und Callback.
- **Entitätsauswahl:** Der Dialog listet Entitäten der passenden Domain und
  markiert die mit passender `unit_of_measurement` (`service.go`,
  `entityOptions`). Richtige Einheiten sind also der Schlüssel für eine
  bequeme Auswahl.
- **Lesen:** REST `GET /api/states/<entity>` bei jedem Zyklus (Standard 30 s).
  W/kW und Wh/kWh/MWh werden skaliert, °F/K in °C umgerechnet.
- **Schreiben:** REST `POST /api/services/<domain>/<service>`
  (`switch.turn_on/off`, `number.set_value`).

### 1.3 Statuswerte

evcc kennt ohne Zusatzkonfiguration (case-insensitiv):

| evcc-Status | Zustände |
|-------------|----------|
| A (nicht verbunden) | `a`, `disconnected`, `not_plugged` |
| B (verbunden, lädt nicht) | `b`, `connected`, `plugged`, `starting`, `stopped`, `paused`, `complete`, `charging_completed` |
| C (lädt/heizt) | `c`, `charging` |

Unbekannte Zustände führen zu einem Fehler in evcc. Der Status-Sensor der
Integration muss deshalb **genau diese Schlüssel** liefern, damit
`statusA/B/C` nicht konfiguriert werden müssen.

### 1.4 Regelverhalten von evcc, das die Integration berücksichtigen muss

Aus `core/loadpoint.go` (`setLimit`, Sync-Prüfung):

1. evcc ruft `number.set_value` **nur bei Änderung** des Stroms auf und
   `switch.turn_on/off` **nur bei Änderung** der Freigabe. Es gibt keine
   periodische Wiederholung. Die Integration muss den zuletzt vorgegebenen
   Strom und die Freigabe also selbst halten (und über Neustarts retten).
2. evcc vergleicht in jedem Zyklus den gelesenen `enabled`-Zustand mit dem
   eigenen. Weicht er ab, meldet evcc „charger out of sync“ (60 s Toleranz nach
   einem Schaltvorgang). `enabled` muss daher den **von evcc befohlenen**
   Zustand zeigen, nicht den verzögerten Cloud-Zustand.
3. Die Leistung rechnet evcc fest mit 230 V × Phasen. Für den einphasigen HWC
   gilt: `P = I × 230 V`.
4. Aktiviert wird, sobald der Sollstrom ≥ `minCurrent` des Ladepunkts ist,
   darunter wird `enable(false)` gesendet.
5. Mit `heating` wird die Temperatur als „SoC“ geführt; das Ladeziel
   (`limitSoc`) ist dann eine **Zieltemperatur in °C**.

---

## 2. Abbildung auf den HWC

### 2.1 Umrechnung Strom ↔ Level

```
I_max   = Nennleistung / 230 V          (z. B. 3000 W → 13,0 A)
level % = round(I / I_max × 100), begrenzt auf 1…100
I_ist   = level / 100 × I_max           (Rückmeldung in der number-Entität)
```

- Die Nennleistung kommt aus `configuration.ratedPower` (`HWCData.rated_power`).
  Fehlt sie, gilt 3000 W als Annahme und ein Hinweis erscheint in der
  Diagnose.
- Mit `milliamps: true` sendet evcc 0,1-A-Schritte (≈ 23 W). Ein Level-Schritt
  bei 3 kW sind 30 W (≈ 0,13 A). Feiner lässt sich der HWC nicht steuern.
- Empfehlung für den evcc-Ladepunkt: `phases: 1`, `minCurrent: 0.5` (≈ 115 W),
  `maxCurrent: I_max`.

### 2.2 Neue Entitäten (nur bei aktivierter Option)

Alle bekommen eine feste `translation_key` und damit vorhersehbare Entity-IDs
mit dem Bestandteil `evcc_`, z. B. `switch.solaredge_hot_water_controller_evcc_enable`.
Die tatsächlichen IDs hängen vom Gerätenamen und von Umbenennungen ab und
werden für das Snippet deshalb aus der Entity-Registry gelesen.

| Entität | Typ | Für evcc-Parameter | Verhalten |
|---------|-----|--------------------|-----------|
| evcc-Freigabe | `switch` | `enable` **und** `enabled` | Zeigt den von evcc befohlenen Zustand (`RestoreEntity`). Ein → Heizen mit dem aktuellen Sollstrom; Aus → `MANUAL`, Level 0. |
| evcc-Sollstrom | `number`, `device_class: current`, Einheit **A**, Schritt 0,1, Bereich 0…I_max, Modus `box` | `setMaxCurrent` | Speichert den Sollwert (`RestoreNumber`); bei Freigabe wird er gedrosselt an die Cloud gesendet. |
| evcc-Status | `sensor`, `device_class: enum`, Optionen `connected`, `charging` | `status` | `charging`, wenn freigegeben **und** Heizleistung > 10 W, sonst `connected`. Übersetzt als „Bereit“ / „Heizt“. |

Bereits vorhanden und direkt verwendbar:

| Vorhandene Entität | Für evcc-Parameter | Prüfen/Anpassen |
|--------------------|--------------------|-----------------|
| Leistung (W) | `power` | Bei geschätzter Leistung (Attribut `estimated`) ist das für evcc ausreichend. |
| Gesamtenergie (Wh/kWh, `total_increasing`) | `energy` | passt |
| Wassertemperatur (°C) | `temp` (nur nightly) | Ohne Fühler im Controller: im Snippet die Fallback-Temperaturquelle aus den Optionen eintragen. |

Bewusst **kein** `binary_sensor` für `enabled`: der Schalter selbst erfüllt
beide Rollen, und evcc akzeptiert `switch` für `enabled`. Das spart eine
Entität und verhindert Abweichungen zwischen beiden.

### 2.3 Steuerlogik (neue Klasse `EvccController`, analog zu `TemperatureLimiter`)

```
Freigabe aus  → MANUAL, level 0, ohne Laufzeit       (Entscheidung „Aus“)
Freigabe ein  → MANUAL, level = f(Sollstrom), duration = Watchdog
Sollstrom neu → wie „Freigabe ein“, wenn freigegeben, sonst nur speichern
```

- **Drosselung:** höchstens ein Cloud-Befehl pro 60 s (wie der
  Temperaturbegrenzer). Neuere Sollwerte überschreiben ältere; am Ende des
  Intervalls wird nur der letzte gesendet. Änderungen < 2 Level-Prozent werden
  verworfen (Totband), außer beim Ein-/Ausschalten. Ein/Aus wird sofort
  gesendet, falls seit dem letzten Befehl ≥ 60 s vergangen sind, sonst als
  Nächstes.
- **Optimistische Anzeige:** Schalter und Sollstrom zeigen sofort den neuen
  Wert (siehe 1.4 Punkt 2). Der tatsächliche Cloud-Zustand ist weiterhin über
  die vorhandenen Sensoren sichtbar.
- **Watchdog:** Heizbefehle laufen mit `duration` = 15 min und werden alle
  10 min erneuert, solange freigegeben. Fallen HA oder die Verbindung zur
  Cloud aus, endet der manuelle Lauf in der Cloud von selbst und der
  Controller kehrt in den vorherigen Modus zurück. Da evcc-„Aus“ als
  `MANUAL 0` ohne Laufzeit gesetzt wird, ist dieser vorherige Modus in der
  Regel „Aus“, also sicher.
  Einschränkung: fällt **nur evcc** aus, erneuert HA weiter. Abhilfe siehe
  offene Punkte (evcc-Lebenszeichen).
- **Fehler:** Schlägt ein Befehl fehl, wird er beim nächsten Intervall erneut
  versucht; `SolarEdgeRateLimitError` verschiebt um `retry_after`. Der
  Schalter bleibt auf dem evcc-Wert, damit evcc nicht „out of sync“ meldet.
- **Neustart:** Freigabe und Sollstrom werden wiederhergestellt; ist die
  Freigabe an, wird der Befehl beim Start einmal neu gesendet (Watchdog wieder
  aufziehen).

### 2.4 Zusammenspiel mit vorhandenen Funktionen

| Funktion | Regel bei aktivierter evcc-Steuerung |
|----------|--------------------------------------|
| Temperaturbegrenzung | Gilt **auch** für evcc-Befehle: ist das Ziel erreicht, wird mit Level 0 statt mit dem evcc-Wert gesendet, der Status bleibt `connected`. evcc sieht dann einfach keinen Verbrauch. So wirkt die Grenze auch ohne `temp`-Unterstützung in evcc 0.317.1. Alternativ/zusätzlich Zieltemperatur in evcc (`limitSoc`) nutzen. |
| Boost, Betriebsart-Select, Aktionen, Schalter „Manuelles Heizen“ | Manuelle Eingriffe haben Vorrang. Die evcc-Steuerung pausiert bis zum Ende der Boost-Laufzeit bzw. bis die Betriebsart wieder auf „Automatik“ steht oder die evcc-Freigabe neu geschaltet wird. Ein Attribut `paused_by` am evcc-Status macht das sichtbar. |
| SolarEdge-Überschusslogik (`excessPv`) | Nur in `AUTO` aktiv. Da evcc stets `MANUAL` setzt, stört sie nicht. Hinweis in der Doku: Überschussheizen in der SolarEdge-App möglichst deaktivieren, damit nach Ende eines manuellen Eingriffs keine Doppelregelung entsteht. |
| Abfrageintervall | Option prüfen: bei aktivierter evcc-Steuerung 30–60 s empfehlen. evcc liest den HA-Zustand ohnehin alle 30 s; die Cloud-Werte kommen aber nur im Intervall der Integration. |

---

## 3. Automatisierung in Home Assistant

1. **Optionsdialog:** neuer Schalter „evcc-Steuerung bereitstellen“
   (`CONF_EVCC`, Standard aus). Speichern lädt den Eintrag neu, die drei
   Entitäten erscheinen bzw. werden beim Abschalten entfernt (Entity-Registry
   aufräumen, letzter evcc-Zustand → Freigabe aus senden).
2. **Abschlussseite des Optionsdialogs** zeigt die ermittelten Werte
   (Nennleistung, I_max, Entity-IDs) und einen fertigen evcc-YAML-Block über
   `description_placeholders`.
3. **Diagnose-Download** enthält denselben Block unter `evcc`.
4. **Entity-IDs stabil halten:** Die Entity-IDs werden aus `translation_key`
   gebildet; das Snippet liest die tatsächlichen IDs aus der Entity-Registry,
   damit Umbenennungen durch den Benutzer berücksichtigt werden.
5. **Reparaturhinweis**, wenn die Option aktiv ist, aber seit z. B. 24 h kein
   evcc-Befehl kam (Hinweis auf fehlende evcc-Konfiguration), optional.

Beispiel des generierten Blocks (evcc 0.317.1, Entity-IDs beispielhaft):

```yaml
chargers:
  - name: warmwasser
    type: template
    template: homeassistant
    uri: http://homeassistant.local:8123
    status: sensor.solaredge_hot_water_controller_evcc_status
    enabled: switch.solaredge_hot_water_controller_evcc_enable
    enable: switch.solaredge_hot_water_controller_evcc_enable
    setMaxCurrent: number.solaredge_hot_water_controller_evcc_current
    milliamps: true
    power: sensor.solaredge_hot_water_controller_power
    energy: sensor.solaredge_hot_water_controller_total_energy
    # temp: sensor.solaredge_hot_water_controller_water_temperature   # erst ab evcc nightly / nächstem Release
    heating: true
    integrateddevice: true

loadpoints:
  - title: Warmwasser
    charger: warmwasser
    mode: pv
    phases: 1
    minCurrent: 0.5
    maxCurrent: 13
```

In der evcc-Weboberfläche (empfohlen seit 0.300): *Konfiguration → Laden &
Heizen → Hinzufügen → Home Assistant → Wallbox*, HA-Instanz wählen, anmelden,
die drei `evcc_`-Entitäten sowie Leistung/Energie auswählen, unter
„Erweitert“ `heating`, `integrateddevice` und `milliamps` einschalten.

---

## 4. Voraussetzungen

**evcc**
- Version **≥ 0.316** (für `milliamps`); 0.317.1 empfohlen.
- `temp` im `homeassistant`-Template erst im nächsten Release (aktuell nur
  nightly). Bis dahin übernimmt die Temperaturbegrenzung der Integration.
- Externe URL in evcc gesetzt (für den OAuth-Login bei HA).
- evcc muss HA im Netz erreichen; mDNS für die automatische Erkennung, sonst
  URI manuell.
- evcc-Intervall ≥ 30 s (Standard).

**Home Assistant / Integration**
- HA 2026.10 (wie bisher).
- Nennleistung des Controllers bekannt (Cloud-Wert), sonst Annahme 3 kW.
- Benutzer für evcc in HA (am besten eigener, nicht-administrativer Benutzer).

---

## 5. Umsetzungsschritte

1. `const.py`: `CONF_EVCC`, `EVCC_WATCHDOG`, `EVCC_RENEW`, `EVCC_DEADBAND`,
   `NOMINAL_VOLTAGE = 230`, `DEFAULT_RATED_POWER_W = 3000`.
2. `evcc.py`: `EvccController` (Zustand, Drosselung, Watchdog, Persistenz über
   `Store`, Zusammenspiel mit `TemperatureLimiter` und manuellen Eingriffen).
3. `coordinator.py`: Hook, über den manuelle Befehle die evcc-Steuerung
   pausieren; `HWCData` um I_max ergänzen.
4. Plattformen: Schalter in `switch.py`, Number in `number.py`, Enum-Sensor in
   `sensor.py`, jeweils nur bei `CONF_EVCC`.
5. `config_flow.py`: Option plus Abschlussseite mit Snippet.
6. `diagnostics.py`: Abschnitt `evcc`.
7. Übersetzungen (`strings.json`, `en.json`, `de.json`), `icons.json`.
8. Tests: Umrechnung, Drosselung/Totband, Watchdog-Erneuerung, Neustart,
   Vorrang manueller Eingriffe, Temperaturgrenze, Optionsflow.
9. README (DE/EN-Abschnitt „evcc“), CHANGELOG, Version 2.1.0.

---

## 6. Risiken und offene Punkte

| Punkt | Bewertung / Vorschlag |
|-------|-----------------------|
| Cloud-Latenz (Befehl → Wirkung oft 5–60 s) | evcc regelt in 30-s-Schritten nach. Totband und 60-s-Drossel verhindern Schwingen; evcc-Option „Verzögerung beim Einschalten/Abschalten“ (`enable.delay`/`disable.delay`) auf ≥ 1–2 min setzen. |
| Rate-Limit der SolarEdge-Cloud | max. 1 Befehl/min plus Erneuerung alle 10 min; Retry-After wird beachtet. |
| Nur evcc fällt aus | Watchdog greift nicht, weil HA erneuert. Option: Erneuerung nur, wenn seit der letzten evcc-Änderung < X h vergangen sind, oder optionales „evcc-Lebenszeichen“ (z. B. Entität der Integration `marq24/ha-evcc`). Entscheidung bei der Umsetzung. |
| `temp` noch nicht im Release | Temperaturbegrenzung der Integration nutzen; `temp` nachrüsten, sobald evcc veröffentlicht. |
| SolarEdge-API inoffiziell | Endpunkt `activationState` wird bereits genutzt; keine neuen Endpunkte nötig. |
| Alternativ: evcc-Feature `continuous` („aus“ = Normalbetrieb) | Passt zur verworfenen Variante „zurück auf Automatik“; kann später als Option ergänzt werden. |

---

## Quellen

- evcc-Quellcode 0.317.1 / `master`:
  [`templates/definition/charger/homeassistant.yaml`](https://github.com/evcc-io/evcc/blob/master/templates/definition/charger/homeassistant.yaml),
  [`charger/homeassistant.go`](https://github.com/evcc-io/evcc/blob/master/charger/homeassistant.go),
  [`util/homeassistant/`](https://github.com/evcc-io/evcc/tree/master/util/homeassistant),
  [`core/loadpoint.go`](https://github.com/evcc-io/evcc/blob/master/core/loadpoint.go),
  [`api/feature.go`](https://github.com/evcc-io/evcc/blob/master/api/feature.go)
- [evcc-Doku: Home Assistant Charger](https://docs.evcc.io/en/chargers/home-assistant-charger/)
- [evcc-Doku: Heizen](https://docs.evcc.io/en/heating)
- [evcc PR #34614: Temperatur-Entität für Heizgeräte](https://github.com/evcc-io/evcc/pull/34614)
- [evcc Release-Blog](https://docs.evcc.io/en/blog/tags/release/)
- [Home Assistant Auth API](https://developers.home-assistant.io/docs/auth_api)
