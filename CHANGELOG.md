# Changelog

## v2.1.0-beta.1

### New

- **evcc connection** (beta, off by default): the controller follows the mode of an evcc loadpoint, read from a select entity of the ha-evcc integration. Off → off, Smart (`pv` / `minpv` before evcc 0.315) → automatic, so SolarEdge keeps regulating the excess itself, Now → on at 100 %. evcc does not change the power.
  - Commands only on a change of the evcc mode, at most one per minute; a mode chosen by hand is kept until the next change in evcc.
  - *Now* runs for 15 minutes and is renewed every 10 minutes while evcc reports it, so the controller falls back on its own if evcc or Home Assistant goes away.
  - Entities for the Home Assistant charger of evcc with fixed entity IDs: `sensor.solaredge_hwc_evcc_status` (`connected` / `charging`) and the placeholders `switch.solaredge_hwc_evcc_enable` and `number.solaredge_hwc_evcc_current` (hidden, no effect).
  - The options show the evcc configuration with the actual entity IDs; it is also part of the diagnostics.
  - Repair notices when the evcc mode is unavailable for more than 10 minutes and when excess solar heating is off in the SolarEdge app.

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
