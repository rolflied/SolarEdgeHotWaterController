# SolarEdge Hot Water Controller – Home Assistant Integration

> **Disclaimer:** This is an **unofficial**, community-maintained integration and is **not affiliated with, endorsed by, or supported by SolarEdge Technologies**. It uses the internal API of the SolarEdge monitoring portal, which SolarEdge does not document and may change at any time. Use at your own risk.

Custom integration for Home Assistant that reads **and controls** a SolarEdge Home Hot Water Controller (HWC, e.g. `SMRT-HOT-WTR-…`) through the SolarEdge monitoring portal.

The integration UI is available in **English** (default) and **German**.

## Features

- Live values: power, heating level, water temperature, activation mode, reason the heater is off, device status
- Energy counter for the **Energy dashboard** (integrated from the power, survives restarts)
- **Control**: operating mode (Automatic / On / Off / Schedule), manual heating switch, boost with adjustable duration and level
- **Actions** `solaredge_hwc.set_operation_mode` and `solaredge_hwc.boost` for automations, e.g. "heat for 30 minutes at 50 %"
- Login with **username and password** (token renewed automatically) or with a **browser cookie**
- Automatic device discovery, reauthentication when the login expires, reconfiguration after a hardware swap, diagnostics download

## Prerequisites

- Home Assistant 2024.12 or newer (2026.3+ shows the integration icon)
- A SolarEdge monitoring account with access to the Hot Water Controller
- Your **Site ID** (the number in the portal URL, e.g. `…/v/s/XXXXXXX/…`)

## Installation

### HACS (custom repository)

1. Open HACS → three-dot menu → **Custom repositories**
2. Enter this repository URL, category: **Integration**
3. Install the integration and restart Home Assistant

### Manual

1. Copy `custom_components/solaredge_hwc/` into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.

Then add it under **Settings → Devices & services → Add integration → SolarEdge Hot Water Controller**.

## Setup

The first dialog asks how the integration should log in.

### Username and password (recommended)

Enter the email address and password of your SolarEdge account and the Site ID. The integration logs in the same way the web portal does (OAuth2 with PKCE), keeps the access token in memory and renews it on its own. All load devices of the site are listed; with a single device it is picked automatically.

The password is stored in the Home Assistant configuration so that the login can be renewed. Accounts with two-factor authentication or a CAPTCHA cannot log in this way; use the cookie method for those.

### Browser cookie

1. Log in to [monitoring.solaredge.com](https://monitoring.solaredge.com) and open **Smart Energy → Hot Water**
2. Open the developer tools (F12) → **Network** tab, reload the page
3. Select a request to `monitoring.solaredge.com` and copy the full value of the `Cookie:` request header

The Device ID is optional: if you leave it empty, the devices of the site are detected. Otherwise it is the second number in the request `/services/m/so/load-device/site/XXXXXX/device/YYYYYYYY/state`.

The cookie expires after some time. Home Assistant then shows a **repair notice**; paste a fresh cookie there.

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Operating mode | select | Automatic / On / Off / Schedule |
| Manual heating | switch | On = heat manually at the *Manual heating level*. Off = back to automatic (or stay off, see options) |
| Boost | button | Heat at the *Manual heating level* for the *Boost duration*, then return to the previous mode |
| Manual heating level | number (config) | 1–100 %, used by switch, select ("On") and boost |
| Boost duration | number (config) | 5–1440 minutes |
| Power | sensor | Measured power in W; if the controller sends no reading it is estimated from rated power × level (attribute `estimated`) |
| Heating level | sensor | Current level in % |
| Water temperature | sensor | °C, only for controllers with a temperature probe |
| Activation mode | sensor (enum) | `auto`, `manual`, `schedule`, `smart_energy`, `off` |
| Reason heating is off | sensor | e.g. `pending_excess_solar` |
| Total energy | sensor | Wh/kWh, `total_increasing`, for the Energy dashboard |
| Next scheduled start | sensor | Next start of an enabled time schedule; attribute `schedules` lists all schedules |
| Manual heating until | sensor | End of a timed manual run started from Home Assistant |
| Heating active | binary sensor | Heating element is on |
| Device online, Excess solar heating, Schedule enabled | binary sensor (diagnostic) | |
| Device status, Schedule type, Rated power | sensor (diagnostic) | |

### Actions

```yaml
# Heat for 30 minutes at 50 %, then return to the previous mode
action: solaredge_hwc.set_operation_mode
data:
  mode: "on"
  level: 50
  duration: 30

# Boost with the configured defaults
action: solaredge_hwc.boost
```

`config_entry_id` is only needed if more than one controller is set up.

### How control works

All commands go to `PUT /services/m/api/homeautomation/v1.0/{site}/devices/{device}/activationState` with `{"mode", "level", "duration"}`:

| Operating mode | Request |
|----------------|---------|
| Automatic | `AUTO` |
| Schedule | `SCHEDULE` |
| Off | `MANUAL`, level 0 |
| On | `MANUAL`, level = manual heating level, no duration |
| Boost / On with duration | `MANUAL`, level, duration in seconds |

Schedules and the excess-PV setting can only be read; SolarEdge offers no known endpoint to change them.

## Options and changing the configuration

- **Configure** (options): update interval (30–600 s, default 60), request timeout, and what the *Manual heating* switch does when turned off.
- **Reconfigure** (three-dot menu): switch between password and cookie login, change account, cookie, Site ID or Device ID. Empty password/cookie fields keep the stored value. Everything is checked against the API before it is saved.

### After replacing the controller

Enter the new Device ID (and Site ID if it changed) under **Reconfigure**. The existing device is moved to the new ID, so all entities keep their entity IDs, history and long-term statistics.

## Upgrading from 1.x

- Entries are migrated automatically. The entities keep their entity IDs and history; their internal unique IDs now include the config entry, so two controllers no longer collide.
- **The *Activation mode* and *Device status* sensors now report fixed keys** (`auto`, `manual`, `active` …) that the UI translates. Automations comparing against the old texts (`Automatic`, `Online` …) need updating, or can use the `raw_mode` / `raw_status` attributes.
- *Device online* now also counts the status `ACTIVE` as online (reported by current controllers).
- Update interval and timeout moved from the entry data to the options.

## Notes

- Do not set the polling interval too low to avoid being rate-limited (recommended ≥ 60 s).
- *Diagnostics* (device page → three-dot menu) download the raw API answers with credentials and serial number removed – useful for bug reports.
- Login flow and control endpoint follow the community projects [barnold89/solaredge_hotwater](https://github.com/barnold89/solaredge_hotwater) and [karuzo17/solaredge-api-home-assistant](https://github.com/karuzo17/solaredge-api-home-assistant) (both MIT).

## Development

```bash
pip install -r requirements_test.txt
pytest
```

---

## Deutsche Anleitung

Die Oberfläche der Integration ist vollständig ins Deutsche übersetzt. Ist Home Assistant auf Deutsch eingestellt, erscheinen Dialoge, Entitäten und Aktionen automatisch auf Deutsch.

### Kurzanleitung

1. Integration installieren (HACS als benutzerdefiniertes Repository oder manuell) und Home Assistant neu starten
2. **Einstellungen → Geräte & Dienste → Integration hinzufügen → SolarEdge Hot Water Controller**
3. Anmeldeart wählen:
   - **Benutzername und Passwort** (empfohlen): E-Mail, Passwort und Site-ID eingeben. Die Anmeldung wird automatisch erneuert. Konten mit Zwei-Faktor-Anmeldung funktionieren so nicht.
   - **Browser-Cookie**: Site-ID und Cookie eingeben, die Geräte-ID ist optional. Läuft das Cookie ab, meldet Home Assistant das als Reparaturhinweis.

### Steuerung

- **Betriebsart** (Auswahl): Automatik / Ein / Aus / Zeitplan
- **Manuell heizen** (Schalter): heizt mit der *Heizstufe manuell*; beim Ausschalten zurück in den Automatikbetrieb (oder aus bleiben, siehe Optionen)
- **Boost** (Taste): heizt für die *Boost-Dauer* und kehrt danach in die vorherige Betriebsart zurück
- Aktionen `solaredge_hwc.set_operation_mode` und `solaredge_hwc.boost` für Automatisierungen, z. B. „30 Minuten mit 50 % heizen“

Zeitpläne und die PV-Überschuss-Einstellung lassen sich nur lesen.

### Energie-Dashboard

Der Sensor *Gesamtenergie* summiert die Leistung über die Zeit auf und bleibt über Neustarts erhalten. Er lässt sich im Energie-Dashboard als Verbraucher eintragen.

### Gerät ausgetauscht

Unter **Neu konfigurieren** im Drei-Punkte-Menü die neue Geräte-ID eintragen. Das vorhandene Gerät wird auf die neue ID übernommen, die Entitäten behalten Entitäts-IDs, Verlauf und Langzeitstatistiken.

### Umstieg von Version 1.x

Bestehende Einträge werden automatisch migriert. Die Sensoren *Aktivierungsmodus* und *Gerätestatus* liefern jetzt feste Schlüssel (`auto`, `manual`, `active` …), die die Oberfläche übersetzt. Automatisierungen, die auf die alten Texte vergleichen, müssen angepasst werden oder die Attribute `raw_mode` / `raw_status` verwenden.

> **Hinweis:** Dies ist eine **inoffizielle** Integration und steht in **keiner Verbindung zu SolarEdge Technologies**. Nutzung auf eigene Verantwortung.
