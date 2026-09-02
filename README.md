# SolarEdge Hot Water Controller – Home Assistant Integration

> **Disclaimer:** This is an **unofficial**, community-maintained integration and is **not affiliated with, endorsed by, or supported by SolarEdge Technologies**. Use at your own risk.

Custom integration for Home Assistant to read data from a SolarEdge Hot Water Controller (HWC) via the SolarEdge monitoring portal.

The integration UI is available in **English** (default) and **German**.

## Prerequisites

- Home Assistant (recommended: 2024.12+, 2026.3+ for the integration icon)
- A SolarEdge account with access to the Hot Water Controller
- Site ID and Device ID from the SolarEdge monitoring portal
- Browser cookie string (see below)

## Installation

### Manual

1. Copy the `custom_components/solaredge_hwc/` folder into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.
3. In the HA UI: **Settings → Integrations → Add Integration → SolarEdge Hot Water Controller**

### HACS (custom repository)

1. Open HACS → three-dot menu → **Custom Repositories**
2. Enter this repository URL, category: **Integration**
3. Install the integration and restart Home Assistant

## Configuration

The setup flow asks for the following fields:

| Field | Description |
|-------|-------------|
| **Site ID** | Numeric ID of your site (from the URL in the SolarEdge portal) |
| **Device ID** | Numeric ID of the HWC device |
| **Cookie** | Full browser cookie string (see below) |
| **Update interval** | Seconds between API polls (default: 60, min: 30, max: 600) |
| **Timeout** | Seconds until connection timeout (default: 30) |

### How to get the cookie

Since SolarEdge does not provide an official API with key-based authentication, a browser session cookie is required:

1. Log in to [monitoring.solaredge.com](https://monitoring.solaredge.com) in your browser
2. Navigate to your device page: **Smart Energy → Hot Water**
3. Open developer tools (F12) → **Network** tab
4. Reload the page, select a request to `monitoring.solaredge.com`
5. In the request headers, copy the full value of the `Cookie:` header

> **Note:** The cookie expires after some time. When authentication fails, Home Assistant will show a banner automatically. You can update the cookie under **Settings → Integrations → SolarEdge HWC → Configure**.

All setup fields, including Site ID and Device ID, can be changed later; see [Changing the configuration](#changing-the-configuration).

## Provided entities

### Sensors

| Name | Description | Unit |
|------|-------------|------|
| Power | Current heating power | W |
| Heating level | Current heating level / percentage | % |
| Activation mode | MANUAL / AUTO / SMART_ENERGY / SCHEDULE | – |
| Device status | ONLINE / OFFLINE / ERROR | – |
| Total energy | Total consumed energy | Wh |

### Binary sensors

| Name | Description |
|------|-------------|
| Heating active | `true` when power > 10 W |
| Device online | `true` when device status is ONLINE |

## Changing the configuration

Site ID, Device ID, cookie, update interval and timeout can all be changed after setup, either
under **Settings → Integrations → SolarEdge HWC → Configure** or via **Reconfigure** in the
three-dot menu of the integration entry. Leave the cookie field empty to keep the existing cookie.

The new values are checked against the API before they are stored, so a typo in the Site ID or a
cookie that has already expired is rejected right in the dialog.

### After replacing the controller

If the hardware was replaced, enter the new Site ID and Device ID in that dialog. The integration
moves the existing device to the new ID instead of creating a second one, so all entities keep
their entity IDs, their history and their long-term statistics, and dashboards and automations
keep working unchanged.

## Notes

- This integration uses the unofficial SolarEdge monitoring API – changes by SolarEdge may affect functionality.
- Do not set the polling interval too low to avoid being rate-limited by SolarEdge (recommended: >= 60 seconds).

---

## Deutsche Anleitung

Eine vollständige deutsche Übersetzung der Benutzeroberfläche ist in der Integration enthalten. Wenn Home Assistant auf Deutsch eingestellt ist, werden alle Konfigurationsdialoge und Entitätsnamen automatisch auf Deutsch angezeigt.

### Kurzanleitung

1. Integration installieren (manuell oder über HACS als benutzerdefiniertes Repository)
2. **Einstellungen → Integrationen → Integration hinzufügen → SolarEdge Hot Water Controller**
3. Site-ID, Geräte-ID und Browser-Cookie eingeben
4. Cookie bei Ablauf unter **Einstellungen → Integrationen → SolarEdge HWC → Konfigurieren** erneuern

### Gerät ausgetauscht

Site-ID und Geräte-ID lassen sich nachträglich im selben Dialog ändern, ebenso über **Neu
konfigurieren** im Drei-Punkte-Menü. Die Integration übernimmt das vorhandene Gerät auf die neue
ID, statt ein zweites anzulegen. Die Entitäten behalten dadurch ihre Entitäts-IDs, ihren Verlauf
und ihre Langzeitstatistiken, Dashboards und Automatisierungen laufen unverändert weiter.

> **Hinweis:** Dies ist eine **inoffizielle** Integration und steht in **keiner Verbindung zu SolarEdge Technologies**. Nutzung auf eigene Verantwortung.
