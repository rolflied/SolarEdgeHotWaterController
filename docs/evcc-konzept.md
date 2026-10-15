# Konzept: Anbindung an evcc

Stand: 15.10.2026, umgesetzt in v2.1.0-beta.1. Geprüft gegen evcc **0.317.1** (aktuelles Release) und den
`master`-Zweig von evcc-io/evcc, die Integration **ha-evcc** (marq24/ha-evcc)
2026.10.4 sowie Home Assistant **2026.10** (Mindestversion dieser Integration).

## Ziel

Der SolarEdge Hot Water Controller (HWC) regelt den PV-Überschuss **selbst**
(Betriebsart *Automatik*). evcc soll ihn nicht regeln, sondern nur die
Betriebsart vorgeben:

| evcc-Modus des Ladepunkts | HWC |
|---------------------------|-----|
| **Aus** (`off`) | Aus (`MANUAL`, Level 0) |
| **Smart** (`smart`, alt: `pv`, `minpv`) | Automatik (`AUTO`, SolarEdge-Überschusslogik) |
| **Ein/Schnell** (`now`) | Ein mit 100 % (`MANUAL`, Level 100) |

evcc verändert weder Stromstärke noch Leistung. Die Maximaltemperatur regelt
der Heizstab selbst; die Integration berücksichtigt sie dafür nicht.

Getroffene Entscheidungen:

| Frage | Entscheidung |
|-------|--------------|
| Quelle des evcc-Modus | **Select-Entität von ha-evcc** (Ladepunkt-Modus), im Optionsdialog wählbar |
| evcc „Aus“ | Heizstab **aus** (`MANUAL`, 0 %) |
| Anzeige in evcc | Heizstab erscheint in evcc als **Ladepunkt mit Messwerten** (Leistung, Energie, Status); Befehle von evcc an dieses Gerät werden ignoriert |
| Aktivierung | Schalter **„evcc-Anbindung“ im Optionsdialog** |
| Sicherheitsnetz | „Ein“ läuft mit **Laufzeit** und wird erneuert, solange evcc „Ein“ meldet |

---

## 1. Befunde aus evcc

### 1.1 Modi

evcc 0.317 kennt nur noch drei Modi (`api/chargemodestatus.go`):
`off`, `smart`, `now`. Die alten Modi `pv` und `minpv` werden beim Setzen
auf `smart` abgebildet (`minpv` = `smart` + „Immer laden“).

### 1.2 evcc gibt den Modus nicht an das Gerät weiter

Ein evcc-Gerät („Charger“) bekommt nur **Freigabe ein/aus** und **Strom in A**
(`charger/homeassistant.go`: `Enable`, `MaxCurrent`). Den Modus erfährt es
nicht. Im Modus *Smart* schaltet evcc die Freigabe nach eigenem Überschuss,
in *Aus* sperrt es immer. Daraus lässt sich *Aus* nicht von *Smart ohne
Überschuss* unterscheiden.

Die gewünschte Zuordnung braucht deshalb den **Modus selbst**. ha-evcc stellt
ihn je Ladepunkt als `select`-Entität bereit (`pyevcc_ha/keys.py`):

| ha-evcc-Variante | Optionen |
|------------------|----------|
| `MODE_SMART` (evcc ≥ 0.315) | `off`, `smart`, `now` |
| `MODE_PV_MINPV` (ältere evcc) | `off`, `pv`, `minpv`, `now` |

Beide werden unterstützt; `pv` und `minpv` gelten als *Smart*.

### 1.3 Anzeige in evcc über das Template `homeassistant`

Damit evcc Leistung und Energie dem Heizstab zuordnet, wird er in evcc als
Gerät mit Template `homeassistant` angelegt (Gruppe „Wallbox/Heizen“).
Pflichtparameter dieses Templates sind (`templates/definition/charger/homeassistant.yaml`):

| Parameter | HA-Domain / Einheit | Hier verwendet |
|-----------|---------------------|----------------|
| `status` | `sensor`, `binary_sensor`; Werte A/B/C | neuer Sensor *evcc-Status* |
| `enabled` | `sensor`, `binary_sensor`, `switch` | neuer Schalter *evcc-Freigabe* |
| `enable` | `switch`, `input_boolean` | derselbe Schalter |
| `setMaxCurrent` | `number`, `input_number`, Einheit **A** | neue Number *evcc-Strom* |
| `power` (optional) | `sensor`, W/kW | vorhandener Sensor *Leistung* |
| `energy` (optional) | `sensor`, Wh/kWh | vorhandener Sensor *Gesamtenergie* |
| `heating`, `integrateddevice` (erweitert) | – | beide **ein** |
| `temp` (optional, nur evcc nightly) | `sensor`, °C | optional *Wassertemperatur*, reine Anzeige |

Freigabe und Strom sind für evcc Pflicht, haben hier aber **keine Wirkung**.
Die Integration stellt sie als Platzhalter bereit, damit kein Helfer von Hand
angelegt werden muss.

Wichtiges Verhalten von evcc (`core/loadpoint.go`):

- evcc liest die Freigabe in jedem Zyklus zurück und meldet „charger out of
  sync“, wenn sie nicht dem befohlenen Wert entspricht. Der Platzhalter-Schalter
  zeigt daher immer genau den zuletzt von evcc gesetzten Zustand.
- Statuswerte erkennt evcc ohne Zusatzkonfiguration: `connected` → B,
  `charging` → C.

### 1.4 Verbindung evcc → Home Assistant

- evcc findet HA per mDNS (`_home-assistant._tcp`) und meldet sich per OAuth
  mit einem HA-Benutzer an (kein Long-Lived-Token). In evcc muss dafür die
  externe URL gesetzt sein.
- Die Entitätsauswahl in evcc filtert nach Domain und hebt passende Einheiten
  hervor. Die Platzhalter tragen deshalb die erwarteten Einheiten.

### 1.5 Überschussverteilung mit weiteren Verbrauchern (z. B. Wallbox)

Im Modus *Smart* regelt SolarEdge den Heizstab selbst, evcc sieht seinen
Verbrauch über `power`. Hat die Wallbox in evcc eine **höhere Priorität** als
der Heizstab-Ladepunkt, rechnet evcc dessen Leistung der Wallbox als
verfügbar zu und erhöht deren Strom. Der Heizstab sieht dann weniger
Überschuss und regelt von selbst zurück. Das ist das gewünschte Verhalten;
Priorität des Heizstabs daher **niedriger** als die der Wallbox setzen.

---

## 2. Umsetzung in der Integration

### 2.1 Optionen

| Option | Typ | Standard |
|--------|-----|----------|
| evcc-Anbindung | Schalter | aus |
| evcc-Modus-Entität | Entitätsauswahl: `select`/`input_select`, vorgefiltert auf Integration `evcc_intg` | – (Pflicht, wenn Anbindung an) |

Prüfung beim Speichern: Die Entität muss existieren und mindestens `off`,
`now` sowie `smart` oder `pv` als Option haben. Sonst Fehler „Keine
evcc-Modus-Entität“.

Ist genau eine passende ha-evcc-Entität vorhanden, wird sie vorausgewählt.

### 2.2 Modus folgen (neue Klasse `EvccModeFollower`, analog zu `TemperatureLimiter`)

- Lauscht per `async_track_state_change_event` auf die Modus-Entität.
- Bei **Änderung** des Modus wird die zugehörige HWC-Betriebsart gesendet:

  | Modus | Befehl |
  |-------|--------|
  | `off` | `MANUAL`, Level 0, ohne Laufzeit |
  | `smart`, `pv`, `minpv` | `AUTO` |
  | `now` | `MANUAL`, Level 100, Laufzeit 15 min |

- **Start und Neuladen:** Der aktuelle Modus wird einmal angewendet, falls
  der HWC nicht schon in der passenden Betriebsart ist.
- **Nur Flanken:** Danach wird nur bei einer Modus-Änderung gesendet.
  Ändert jemand die Betriebsart in HA oder in der SolarEdge-App, bleibt diese
  bis zur nächsten Modus-Änderung in evcc bestehen (bewusster Handeingriff).
  Ausnahme: die Erneuerung von „Ein“ (siehe 2.3) läuft nur weiter, solange der
  HWC noch im von evcc gesetzten „Ein“ steht.
- **Unbekannt/nicht verfügbar** (`unknown`, `unavailable`, unbekannte
  Option): kein Befehl. Bei „Ein“ endet damit die Erneuerung (siehe 2.3).
  Nach 10 min Dauer ein Reparaturhinweis „evcc-Modus nicht verfügbar“.
- **Drosselung:** höchstens ein Befehl pro 60 s; schnelle Wechsel werden
  zusammengefasst, nur der letzte Modus wird gesendet. `SolarEdgeRateLimitError`
  verschiebt um `retry_after`, Fehler werden beim nächsten Intervall wiederholt.
- **Rückmeldung:** Attribute am evcc-Status-Sensor: `evcc_mode`,
  `applied_operation`, `last_command`, `override` (Handeingriff erkannt).

### 2.3 Sicherheitsnetz für „Ein“

„Ein“ wird mit `duration` = 15 min gesendet und alle 10 min erneuert, solange
die Modus-Entität `now` meldet. Fällt evcc, ha-evcc oder HA aus, wird nicht
mehr erneuert; der Controller beendet den manuellen Lauf in der Cloud und
kehrt in die vorherige Betriebsart zurück (in der Regel *Automatik*, weil
evcc vorher meist auf *Smart* stand). So heizt der Stab nie dauerhaft mit
100 %, ohne dass evcc das noch will.

*Aus* (`MANUAL 0`) und *Smart* (`AUTO`) sind sichere Dauerzustände und
brauchen keine Laufzeit.

### 2.4 Platzhalter- und Status-Entitäten (nur bei aktivierter Anbindung)

| Entität | Typ | Eigenschaften |
|---------|-----|---------------|
| evcc-Status | `sensor`, `device_class: enum`, Optionen `connected`, `charging` | `charging`, wenn der Heizstab heizt (Leistung > 10 W), sonst `connected`. Übersetzt als „Bereit“ / „Heizt“. |
| evcc-Freigabe | `switch` | Speichert nur den zuletzt von evcc gesetzten Zustand (`RestoreEntity`), **ohne Wirkung** auf den HWC. |
| evcc-Strom | `number`, `device_class: current`, Einheit A, 0–32 A, Schritt 0,1 | Speichert nur den Wert (`RestoreNumber`), **ohne Wirkung**. |

Freigabe und Strom: `entity_category: diagnostic`, standardmäßig
ausgeblendet (`entity_registry_visible_default = False`), damit sie im
Dashboard nicht als Bedienelement missverstanden werden. evcc kann sie
trotzdem lesen und schreiben.

### 2.5 Zusammenspiel mit vorhandenen Funktionen

| Funktion | Regel |
|----------|-------|
| Betriebsart-Select, Schalter „Manuelles Heizen“, Boost, Aktionen | bleiben unverändert nutzbar; gelten als Handeingriff bis zur nächsten Modus-Änderung in evcc. |
| Temperaturbegrenzung der Integration | keine Sonderbehandlung. Die Maximaltemperatur regelt der Heizstab. Ist die Begrenzung trotzdem eingeschaltet, wirkt sie wie bisher nur in *Automatik*/*Zeitplan*. |
| SolarEdge-Überschussheizen | muss in der SolarEdge-App **aktiviert** sein, sonst heizt *Smart* (= *Automatik*) nicht mit Überschuss. Die Diagnose-Entität „Überschussheizen“ zeigt den Zustand; ist sie aus, erscheint ein Hinweis. |

### 2.6 Hilfe bei der Einrichtung

- Abschlussseite des Optionsdialogs und Diagnose-Download zeigen einen
  fertigen evcc-Konfigurationsblock mit den **tatsächlichen Entity-IDs** aus
  der Entity-Registry.
- README-Abschnitt „evcc“ mit Schritt-für-Schritt-Anleitung.

Beispiel (die evcc-Entitäten haben feste IDs; Leistung und Energie je nach Gerätename):

```yaml
chargers:
  - name: warmwasser
    type: template
    template: homeassistant
    uri: http://homeassistant.local:8123
    status: sensor.solaredge_hwc_evcc_status
    enabled: switch.solaredge_hwc_evcc_enable
    enable: switch.solaredge_hwc_evcc_enable
    setMaxCurrent: number.solaredge_hwc_evcc_current
    power: sensor.solaredge_hot_water_controller_power
    energy: sensor.solaredge_hot_water_controller_total_energy
    heating: true
    integrateddevice: true

loadpoints:
  - title: Warmwasser
    charger: warmwasser
    mode: smart
    phases: 1
    priority: 0   # niedriger als die Wallbox
```

In der evcc-Oberfläche: *Konfiguration → Laden & Heizen → Hinzufügen →
Home Assistant → Wallbox*, HA-Instanz wählen, anmelden, die Entitäten
auswählen und unter „Erweitert“ `heating` und `integrateddevice` einschalten.
Danach in ha-evcc den neuen Ladepunkt übernehmen (Integration neu laden) und
dessen Modus-Entität in den Optionen dieser Integration wählen.

---

## 3. Voraussetzungen

**evcc**
- evcc ≥ 0.315 (neue Modi `off`/`smart`/`now`); ältere Versionen mit
  `pv`/`minpv` funktionieren ebenfalls. Empfohlen: 0.317.1.
- Externe URL in evcc gesetzt (OAuth-Login bei HA), HA im Netz erreichbar.

**Home Assistant**
- HA 2026.10.
- **ha-evcc** (marq24/ha-evcc, HACS) mit dem Heizstab-Ladepunkt eingerichtet.
- HA-Benutzer für evcc (am besten eigener, nicht-administrativer Benutzer).

**SolarEdge**
- Überschussheizen in der SolarEdge-App aktiviert.

---

## 4. Umsetzungsschritte

1. `const.py`: `CONF_EVCC`, `CONF_EVCC_MODE_ENTITY`, Modus-Zuordnung,
   `EVCC_ON_DURATION` (15 min), `EVCC_RENEW_INTERVAL` (10 min),
   `EVCC_UNAVAILABLE_ISSUE_DELAY` (10 min).
2. `evcc.py`: `EvccModeFollower` (Zustandsverfolgung, Flanken, Drosselung,
   Erneuerung, Handeingriff-Erkennung, Reparaturhinweis).
3. `__init__.py`: Follower starten/stoppen; Platzhalter beim Abschalten aus
   der Entity-Registry entfernen.
4. Plattformen: Status in `sensor.py`, Freigabe in `switch.py`, Strom in
   `number.py`, nur bei `CONF_EVCC`.
5. `config_flow.py`: Optionen mit `EntitySelector(domain=["select",
   "input_select"])`, Validierung, Abschlussseite mit Block.
6. `diagnostics.py`: Abschnitt `evcc` (Modus, letzter Befehl, Block).
7. Übersetzungen (`strings.json`, `en.json`, `de.json`), `icons.json`.
8. Tests: Zuordnung aller Modi inkl. `pv`/`minpv`, Start-Abgleich, nur Flanken,
   Drosselung, Erneuerung und Ende bei `unavailable`, Handeingriff,
   Platzhalter ohne Wirkung, Optionsflow-Validierung.
9. README (DE/EN), CHANGELOG, Version 2.1.0.

---

## 5. Risiken und offene Punkte

| Punkt | Bewertung / Vorschlag |
|-------|-----------------------|
| evcc schaltet im Modus *Smart* den Platzhalter nach eigenem Überschuss | ohne Wirkung; evcc zeigt evtl. „Heizt“, obwohl es selbst „gesperrt“ hat. Rein kosmetisch. |
| Abhängigkeit von ha-evcc | Entitäts-IDs/Optionen können sich mit ha-evcc-Versionen ändern; daher Prüfung der Optionen statt fester IDs. Später optional evcc-API direkt (evcc meldet sich per mDNS als `_http._tcp` „evcc-…“, `GET /api/state` ist ohne Login lesbar). |
| Verzögerung | ha-evcc aktualisiert im eigenen Intervall, die SolarEdge-Cloud setzt Befehle mit 5–60 s Verzögerung um. Für Modus-Wechsel unkritisch. |
| SolarEdge-API inoffiziell | Es wird nur der bereits genutzte Endpunkt `activationState` verwendet. |
| Pläne/Tarife in evcc | Ein evcc-Plan schaltet den Ladepunkt nicht auf `now`, sondern regelt intern über die Freigabe. Diese wirkt hier nicht; Pläne werden also nicht umgesetzt. Bei Bedarf später: Freigabe in *Smart* als „Ein“ werten (Option). |

---

## Quellen

- evcc-Quellcode 0.317.1 / `master`:
  [`api/chargemodestatus.go`](https://github.com/evcc-io/evcc/blob/master/api/chargemodestatus.go),
  [`templates/definition/charger/homeassistant.yaml`](https://github.com/evcc-io/evcc/blob/master/templates/definition/charger/homeassistant.yaml),
  [`charger/homeassistant.go`](https://github.com/evcc-io/evcc/blob/master/charger/homeassistant.go),
  [`util/homeassistant/`](https://github.com/evcc-io/evcc/tree/master/util/homeassistant),
  [`core/loadpoint.go`](https://github.com/evcc-io/evcc/blob/master/core/loadpoint.go),
  [`core/site.go`](https://github.com/evcc-io/evcc/blob/master/core/site.go)
- ha-evcc: [`pyevcc_ha/keys.py`](https://github.com/marq24/ha-evcc/blob/main/custom_components/evcc_intg/pyevcc_ha/keys.py),
  [HA_CONTROLLED_BY_EVCC.md](https://github.com/marq24/ha-evcc/blob/main/HA_CONTROLLED_BY_EVCC.md)
- [evcc-Doku: Home Assistant Charger](https://docs.evcc.io/en/chargers/home-assistant-charger/)
- [evcc-Doku: Heizen](https://docs.evcc.io/en/heating)
- [evcc Release-Blog](https://docs.evcc.io/en/blog/tags/release/)
- [Home Assistant Auth API](https://developers.home-assistant.io/docs/auth_api)
