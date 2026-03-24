# SolarEdge Hot Water Controller – Home Assistant Integration

Custom Integration für Home Assistant, um einen SolarEdge Warmwasser-Controller (HWC) über das SolarEdge Monitoring-Portal auszulesen.

## Voraussetzungen

- Home Assistant (empfohlen: 2024.12+)
- Ein SolarEdge-Konto mit Zugriff auf den Warmwasser-Controller
- Site-ID und Geräte-ID aus dem SolarEdge Monitoring-Portal
- Browser-Cookie-String (siehe unten)

## Installation

### Manuell

1. Den Ordner `custom_components/solaredge_hwc/` in den `custom_components/`-Ordner deines Home Assistant kopieren.
2. Home Assistant neu starten.
3. In der HA-Oberfläche: **Einstellungen → Integrationen → Integration hinzufügen → SolarEdge Hot Water Controller**

### HACS (manuell als benutzerdefiniertes Repository)

1. HACS öffnen → Drei-Punkte-Menü → **Benutzerdefinierte Repositories**
2. URL dieses Repositories eintragen, Kategorie: **Integration**
3. Integration installieren und HA neu starten

## Konfiguration

Bei der Einrichtung werden folgende Felder abgefragt:

| Feld | Beschreibung |
|------|-------------|
| **Site-ID** | Numerische ID deiner Anlage (aus der URL im SolarEdge-Portal) |
| **Geräte-ID** | Numerische ID des HWC-Geräts |
| **Cookie** | Vollständiger Browser-Cookie-String (siehe unten) |
| **Abfrageintervall** | Sekunden zwischen API-Abfragen (Standard: 60, Min: 30, Max: 600) |
| **Timeout** | Sekunden bis Verbindungs-Timeout (Standard: 30) |

### Cookie ermitteln

Da SolarEdge keine offizielle API mit Key-Authentifizierung anbietet, wird der Browser-Session-Cookie benötigt:

1. Im Browser auf [monitoring.solaredge.com](https://monitoring.solaredge.com) einloggen
2. Zur Seite deines Geräts navigieren: **Smart Energy → Hot Water**
3. Entwicklertools öffnen (F12) → **Netzwerk**-Tab
4. Seite neu laden, einen Request zu `monitoring.solaredge.com` auswählen
5. Im Request-Header den kompletten Wert des `Cookie:`-Headers kopieren

> **Hinweis:** Der Cookie läuft nach einiger Zeit ab. Bei Authentifizierungsfehlern zeigt HA automatisch ein Banner an. Den Cookie kannst du dann unter **Einstellungen → Integrationen → SolarEdge HWC → Konfigurieren** aktualisieren.

## Bereitgestellte Entitäten

### Sensoren

| Name | Beschreibung | Einheit |
|------|-------------|---------|
| SolarEdge HWC Leistung | Aktuelle Heizleistung | W |
| SolarEdge HWC Heizstufe | Aktueller Füllstand / Heizstufe | % |
| SolarEdge HWC Aktivierungsmodus | MANUAL / AUTO / SMART_ENERGY / SCHEDULE | – |
| SolarEdge HWC Gerätestatus | ONLINE / OFFLINE / ERROR | – |
| SolarEdge HWC Gesamtenergie | Gesamte verbrauchte Energie | kWh |

### Binärsensoren

| Name | Beschreibung |
|------|-------------|
| SolarEdge HWC Heizung aktiv | `true` wenn Leistung > 10 W |
| SolarEdge HWC Gerät online | `true` wenn Gerätestatus ONLINE |

## Cookie aktualisieren

Unter **Einstellungen → Integrationen → SolarEdge HWC → Konfigurieren** kann ein neues Cookie eingegeben werden. Das Cookie-Feld leer lassen, um das bestehende Cookie beizubehalten.

## Hinweise

- Die Integration nutzt die inoffizielle SolarEdge Monitoring API – Änderungen seitens SolarEdge können die Funktion beeinträchtigen.
- Abfrageintervall nicht zu kurz wählen, um eine Sperrung durch SolarEdge zu vermeiden (Empfehlung: ≥ 60 Sekunden).
