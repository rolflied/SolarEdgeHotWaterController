"""Data update coordinator for SolarEdge Hot Water Controller."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    API_BASE_URL,
    API_HWC_ENDPOINT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SolarEdgeHWCCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SolarEdge Hot Water Controller data."""

    def __init__(
        self,
        hass: HomeAssistant,
        site_id: str,
        device_id: str,
        cookie: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the coordinator."""
        self.site_id = site_id
        self.device_id = device_id
        self.cookie = cookie
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def _get_headers(self) -> dict[str, str]:
        """Return the required HTTP headers for the SolarEdge API."""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": (
                f"https://monitoring.solaredge.com/v/s/"
                f"{self.site_id}/smart-energy/hot-water"
            ),
            "Cookie": self.cookie,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the SolarEdge HWC API."""
        url = (
            f"{API_BASE_URL}"
            f"{API_HWC_ENDPOINT.format(site_id=self.site_id, device_id=self.device_id)}"
        )

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        try:
            async with self._session.get(
                url,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                _LOGGER.debug(
                    "SolarEdge HWC API response status: %s", response.status
                )

                if response.status in (401, 403):
                    raise ConfigEntryAuthFailed(
                        "Cookie is expired or invalid. Please update the cookie "
                        "via Settings → Integrations → SolarEdge HWC → Configure."
                    )

                if response.status != 200:
                    raise UpdateFailed(
                        f"SolarEdge API returned HTTP {response.status}. "
                        "Check Site ID and Device ID."
                    )

                try:
                    data = await response.json(content_type=None)
                except Exception as err:
                    raise UpdateFailed(f"Failed to parse API response as JSON: {err}")

                _LOGGER.debug("SolarEdge HWC data: %s", data)
                return data

        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientConnectorError as err:
            raise UpdateFailed(f"Cannot connect to SolarEdge API: {err}")
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"HTTP client error: {err}")
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching HWC data: {err}")

    async def async_shutdown(self) -> None:
        """Close the aiohttp client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
