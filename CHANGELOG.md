# Changelog

## v2.0.0

Complete rework. **Requires Home Assistant 2026.10 or newer.**

### Breaking changes

- Minimum Home Assistant version is 2026.10.
- The *Activation mode* and *Device status* sensors report fixed keys (`auto`, `manual`, `active` …) that the UI translates. Automations comparing against the old texts need updating, or can use the `raw_mode` / `raw_status` attributes.
- Polling interval and timeout moved to the options; Site ID, Device ID and login are changed via **Reconfigure**.
- Existing entries are migrated automatically; entity IDs and history are kept.

### New

- Login with SolarEdge username and password (renewed automatically), the browser cookie remains as an alternative; reauthentication when the login expires.
- Automatic device discovery during setup.
- Control: water heater entity (operating mode, on/off, water temperature), operating mode select, *Manual heating* switch, *Boost* button with adjustable level and duration.
- Actions `solaredge_hwc.set_operation_mode` and `solaredge_hwc.boost`, targeting the water heater entity.
- Temperature limit: target temperature on the water heater entity, enforced as an upper limit in automatic/schedule mode with adjustable hysteresis; optional fallback temperature sensor from Home Assistant when the controller reports no temperature; repair notice if no temperature is available.
- New sensors: water temperature, reason heating is off, next scheduled start, manual heating until, rated power, schedule type, excess-solar and schedule binary sensors, *Temperature limit reached*.
- Energy counter for the Energy dashboard (integrated from the power), estimated power for controllers without a meter.
- Diagnostics download, German and English translations, icons.

### Fixed

- Entities of several controllers collided because of constant unique IDs.
- *Device online* showed offline for the status `ACTIVE`.
- An expired cookie did not lead to a reauthentication prompt.
- Wrong error message ("invalid cookie") for every non-200 answer during setup.
- Crash of *Heating active* when the power value was `null`.
- Double reload after changing the configuration.

### Technical

- Uses current Home Assistant APIs (OptionsFlowWithReload, scoped device registry lookups, Home Assistant HTTP sessions, `retry_after` on HTTP 429, platform entity actions, central abort strings).
- Tests (46) and CI with hassfest and HACS validation.
