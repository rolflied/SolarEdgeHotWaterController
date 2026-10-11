"""
Client for the (unofficial) SolarEdge monitoring portal API.

SolarEdge does not document an API for the Hot Water Controller. The
endpoints below are the ones the monitoring web app itself uses. Two ways
of authenticating are supported:

* ``OAuthAuth`` logs in with username and password through the same
  OAuth2 authorization code flow with PKCE the web app uses and renews the
  bearer token on its own.
* ``CookieAuth`` reuses a session cookie copied from the browser. It cannot
  renew itself; once it expires the user has to paste a fresh one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import base64
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
import hashlib
from html.parser import HTMLParser
import json as jsonlib
import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from yarl import URL

from .const import (
    BASE_URL,
    LOGIN_BASE_URL,
    OAUTH_CALLBACK_URL,
    OAUTH_CLIENT_ID,
    OAUTH_TOKEN_URL,
    PATH_ACTIVATION_STATE,
    PATH_DEVICE_INFO,
    PATH_DEVICE_STATE,
    PATH_DEVICES_LIST_INFO,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class SolarEdgeError(Exception):
    """Base class for all errors raised by this module."""


class SolarEdgeAuthError(SolarEdgeError):
    """The credentials or the cookie were rejected."""


class SolarEdgeConnectionError(SolarEdgeError):
    """The portal could not be reached or failed temporarily."""


class SolarEdgeRateLimitError(SolarEdgeConnectionError):
    """The portal asked to slow down (HTTP 429)."""

    def __init__(self, message: str, retry_after: float) -> None:
        """Store how long to wait before the next request."""
        super().__init__(message)
        self.retry_after = retry_after


class SolarEdgeResponseError(SolarEdgeError):
    """The portal answered with something unexpected."""


# Bounds for a Retry-After value sent by the portal, in seconds
_RETRY_AFTER_DEFAULT = 300.0
_RETRY_AFTER_MIN = 60.0
_RETRY_AFTER_MAX = 3600.0


def _retry_after(value: str | None) -> float:
    """Turn a Retry-After header (seconds) into a sane delay."""
    try:
        seconds = float(value) if value else _RETRY_AFTER_DEFAULT
    except ValueError:
        # HTTP dates are allowed too; they are rare enough to use the default
        seconds = _RETRY_AFTER_DEFAULT
    return min(max(seconds, _RETRY_AFTER_MIN), _RETRY_AFTER_MAX)


type LoginSessionFactory = Callable[[], AbstractAsyncContextManager[aiohttp.ClientSession]]


def default_login_session() -> AbstractAsyncContextManager[aiohttp.ClientSession]:
    """Create a short-lived session with a cookie jar for the login."""
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())


def _is_temporary(status: int) -> bool:
    """Return True for HTTP status codes that indicate a temporary problem."""
    return status == 429 or status >= 500


# ---------------------------------------------------------------------------
# Authentication strategies
# ---------------------------------------------------------------------------


class SolarEdgeAuth(ABC):
    """Supplies the authentication headers for API requests."""

    @abstractmethod
    async def async_headers(self) -> dict[str, str]:
        """Return the headers that authenticate a request."""

    async def async_renew(self, rejected_headers: dict[str, str]) -> bool:
        """
        Try to replace credentials the server just rejected.

        Returns True if new credentials are available and the request
        should be repeated.
        """
        return False


class CookieAuth(SolarEdgeAuth):
    """Authenticate with a session cookie copied from the browser."""

    def __init__(self, cookie: str) -> None:
        """Store the cookie string."""
        self._cookie = cookie.strip()
        if self._cookie.lower().startswith("cookie:"):
            self._cookie = self._cookie[len("cookie:") :].strip()
        self._csrf = _cookie_value(self._cookie, "CSRF-TOKEN")

    async def async_headers(self) -> dict[str, str]:
        """Return the cookie and, for write requests, the CSRF header."""
        headers = {"Cookie": self._cookie, "X-Requested-With": "XMLHttpRequest"}
        if self._csrf:
            # Spring Security only accepts PUT/POST with the token echoed back
            headers["X-CSRF-TOKEN"] = self._csrf
        return headers


def _cookie_value(cookie: str, name: str) -> str | None:
    """Return the value of one cookie from a ``Cookie:`` header string."""
    for part in cookie.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key == name:
            return value
    return None


class _FormParser(HTMLParser):
    """Collect the input fields of the first HTML form on a page."""

    def __init__(self) -> None:
        super().__init__()
        self.form_found = False
        self.inputs: dict[str, str] = {}
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "form" and not self.form_found:
            self.form_found = self._in_form = True
        elif tag == "input" and self._in_form:
            values = dict(attrs)
            if name := values.get("name"):
                self.inputs[name] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_form = False


def _pkce_pair() -> tuple[str, str]:
    """Return a PKCE code verifier and its S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class OAuthAuth(SolarEdgeAuth):
    """
    Log in with username and password and keep a bearer token alive.

    Tokens are kept in memory only; after a restart the integration logs in
    again. Parallel requests that hit an expired token share one renewal.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        timeout: int,
        login_session: LoginSessionFactory = default_login_session,
    ) -> None:
        """
        Store the credentials.

        ``session`` sends the token requests; ``login_session`` creates the
        short-lived session with a cookie jar the login form needs.
        """
        self._session = session
        self._login_session = login_session
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._lock = asyncio.Lock()

    async def async_headers(self) -> dict[str, str]:
        """Return the bearer token, logging in first if there is none."""
        if self._access_token is None:
            async with self._lock:
                if self._access_token is None:
                    await self._async_login()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def async_renew(self, rejected_headers: dict[str, str]) -> bool:
        """Refresh the token, or log in again if refreshing fails."""
        async with self._lock:
            current = f"Bearer {self._access_token}"
            if self._access_token and rejected_headers.get("Authorization") != current:
                # Another request renewed the token while this one waited
                return True
            if self._refresh_token and await self._async_refresh():
                return True
            await self._async_login()
            return True

    async def async_login(self) -> None:
        """Log in now; used by the config flow to check the credentials."""
        async with self._lock:
            await self._async_login()

    async def _async_refresh(self) -> bool:
        """Swap the refresh token for a new access token."""
        try:
            tokens = await self._async_token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                self._session,
            )
        except SolarEdgeError as err:
            _LOGGER.debug("Token refresh failed, logging in again: %s", err)
            self._refresh_token = None
            return False
        self._access_token = tokens["access_token"]
        # SolarEdge does not rotate the refresh token, but take a new one if sent
        self._refresh_token = tokens.get("refresh_token") or self._refresh_token
        _LOGGER.debug("SolarEdge access token refreshed")
        return True

    async def _async_login(self) -> None:
        """Run the OAuth2 authorization code flow with PKCE."""
        verifier, challenge = _pkce_pair()
        params = {
            "lang": "en",
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "scope": "email openid",
            "redirect_uri": OAUTH_CALLBACK_URL,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        login_url = f"{LOGIN_BASE_URL}/login?{urlencode(params)}"

        # A dedicated session with a real cookie jar: the login page sets
        # cookies that have to be sent back with the credentials.
        browser = {"User-Agent": USER_AGENT}
        try:
            async with self._login_session() as login_session:
                async with login_session.get(
                    login_url, headers=browser, timeout=self._timeout
                ) as resp:
                    if _is_temporary(resp.status):
                        raise SolarEdgeConnectionError(f"Login page returned HTTP {resp.status}")
                    page_url = str(resp.url)
                    parser = _FormParser()
                    parser.feed(await resp.text())

                if not page_url.startswith(LOGIN_BASE_URL) or not parser.form_found:
                    raise SolarEdgeResponseError("SolarEdge login page has an unexpected format")

                form = {
                    key: value
                    for key, value in parser.inputs.items()
                    if key not in ("username", "password", "email")
                }
                form["username"] = self._username
                form["password"] = self._password

                async with login_session.post(
                    login_url,
                    data=form,
                    headers={
                        **browser,
                        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                        "Accept": "*/*",
                        "Origin": LOGIN_BASE_URL,
                        "Referer": page_url,
                    },
                    timeout=self._timeout,
                ) as resp:
                    if _is_temporary(resp.status):
                        raise SolarEdgeConnectionError(f"Login returned HTTP {resp.status}")
                    visited = [str(step.url) for step in resp.history]
                    visited.append(str(resp.url))
                    location = resp.headers.get("Location")
                    if resp.status == 204 and location:
                        # SolarEdge answers the credential POST with 204 + Location
                        visited.append(str(resp.url.join(URL(location))))

                callback_url = next(
                    (url for url in visited if url.startswith(OAUTH_CALLBACK_URL)),
                    None,
                )
                if callback_url is None and visited[-1].startswith(LOGIN_BASE_URL):
                    # The Location of a 204 may point to another login step
                    async with login_session.get(
                        visited[-1], headers=browser, timeout=self._timeout
                    ) as resp:
                        if _is_temporary(resp.status):
                            raise SolarEdgeConnectionError(
                                f"Login redirect returned HTTP {resp.status}"
                            )
                        visited = [str(step.url) for step in resp.history]
                        visited.append(str(resp.url))
                    callback_url = next(
                        (url for url in visited if url.startswith(OAUTH_CALLBACK_URL)),
                        None,
                    )

                if callback_url is None:
                    if visited[-1].startswith(LOGIN_BASE_URL):
                        # The login page is served again: credentials rejected
                        raise SolarEdgeAuthError("Username or password rejected")
                    raise SolarEdgeResponseError(
                        f"Login ended on unexpected host {urlparse(visited[-1]).netloc}"
                    )

                code = (parse_qs(urlparse(callback_url).query).get("code") or [None])[0]
                if not code:
                    raise SolarEdgeResponseError("Login callback carries no code")

                tokens = await self._async_token_request(
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": OAUTH_CLIENT_ID,
                        "redirect_uri": OAUTH_CALLBACK_URL,
                        "code_verifier": verifier,
                    },
                    login_session,
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SolarEdgeConnectionError(f"Login failed: {err}") from err

        self._access_token = tokens["access_token"]
        self._refresh_token = tokens.get("refresh_token")
        _LOGGER.debug("Logged in to SolarEdge as %s", self._username)

    async def _async_token_request(
        self, data: dict[str, Any], session: aiohttp.ClientSession
    ) -> dict[str, Any]:
        """POST to the token endpoint and return the decoded answer."""
        try:
            async with session.post(
                OAUTH_TOKEN_URL,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "*/*",
                    "Origin": BASE_URL,
                    "Referer": f"{BASE_URL}/",
                    "User-Agent": USER_AGENT,
                },
                timeout=self._timeout,
            ) as resp:
                if _is_temporary(resp.status):
                    raise SolarEdgeConnectionError(f"Token endpoint returned HTTP {resp.status}")
                if resp.status != 200:
                    raise SolarEdgeAuthError(f"Token endpoint returned HTTP {resp.status}")
                tokens = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SolarEdgeConnectionError(f"Token request failed: {err}") from err
        except ValueError as err:
            raise SolarEdgeResponseError("Token endpoint returned no JSON") from err

        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            raise SolarEdgeResponseError("Token response carries no access token")
        return tokens


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


class SolarEdgeHWCClient:
    """Read and control load devices of one SolarEdge site."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: SolarEdgeAuth,
        site_id: str,
        timeout: int,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._auth = auth
        self.site_id = site_id
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def async_get_state(self, device_id: str) -> dict[str, Any]:
        """Return the live state of a device (mode, level, measurements)."""
        data = await self._async_request(
            "GET", PATH_DEVICE_STATE.format(site_id=self.site_id, device_id=device_id)
        )
        if not isinstance(data, dict) or not any(
            key in data
            for key in ("measurements", "percentageLevel", "activationMode", "deviceStatus")
        ):
            _LOGGER.debug("Unexpected state response: %s", data)
            raise SolarEdgeResponseError("State response lacks the expected fields")
        return data

    async def async_get_info(self, device_id: str) -> dict[str, Any]:
        """Return the static info of a device (model, rated power, schedules)."""
        data = await self._async_request(
            "GET", PATH_DEVICE_INFO.format(site_id=self.site_id, device_id=device_id)
        )
        if not isinstance(data, dict):
            raise SolarEdgeResponseError("Info response is not an object")
        return data

    async def async_get_load_devices(self) -> list[dict[str, Any]]:
        """Return all load devices (hot water controllers, switches) of the site."""
        data = await self._async_request("GET", PATH_DEVICES_LIST_INFO.format(site_id=self.site_id))
        if not isinstance(data, dict):
            raise SolarEdgeResponseError("Device list response is not an object")
        devices = (data.get("devicesByType") or {}).get("LOAD_DEVICE") or []
        return [
            device
            for device in devices
            if isinstance(device, dict)
            and (device.get("deviceInfo") or {}).get("deviceId") is not None
        ]

    async def async_set_activation_state(
        self,
        device_id: str,
        mode: str,
        level: int | None = None,
        duration: int | None = None,
    ) -> None:
        """
        Change the activation state of a device.

        ``mode`` is AUTO, MANUAL or SCHEDULE. For MANUAL, ``level`` is the
        heating level in percent (0 = off) and ``duration`` the time in
        seconds after which the device returns to its previous mode
        (``None`` = until changed again).
        """
        await self._async_request(
            "PUT",
            PATH_ACTIVATION_STATE.format(site_id=self.site_id, device_id=device_id),
            json={"mode": mode, "level": level, "duration": duration},
        )

    async def _async_request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        """Send a request, renewing the credentials once if they are rejected."""
        auth_headers = await self._auth.async_headers()
        status, data = await self._async_send(method, path, json, auth_headers)
        if status in (401, 403) and await self._auth.async_renew(auth_headers):
            auth_headers = await self._auth.async_headers()
            status, data = await self._async_send(method, path, json, auth_headers)
        if status in (401, 403):
            raise SolarEdgeAuthError(f"{method} {path} rejected with HTTP {status}")
        return data

    async def _async_send(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None,
        auth_headers: dict[str, str],
    ) -> tuple[int, Any]:
        """Send one request and return status and decoded body."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            **auth_headers,
        }
        try:
            async with self._session.request(
                method,
                f"{BASE_URL}{path}",
                headers=headers,
                json=json,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("%s %s -> HTTP %s", method, path, resp.status)
                if resp.status in (401, 403):
                    return resp.status, None
                if 300 <= resp.status < 400:
                    # An expired session gets redirected to the login page
                    return 401, None
                if resp.status == 429:
                    raise SolarEdgeRateLimitError(
                        f"{method} {path} was rate limited",
                        _retry_after(resp.headers.get("Retry-After")),
                    )
                if _is_temporary(resp.status):
                    raise SolarEdgeConnectionError(f"{method} {path} returned HTTP {resp.status}")
                if resp.status >= 400:
                    body = (await resp.text())[:200]
                    raise SolarEdgeResponseError(
                        f"{method} {path} returned HTTP {resp.status}: {body}"
                    )
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SolarEdgeConnectionError(f"{method} {path} failed: {err}") from err

        if not text.strip():
            return resp.status, None
        try:
            return resp.status, jsonlib.loads(text)
        except ValueError as err:
            # An HTML login page instead of JSON means the session is gone
            if text.lstrip().startswith("<"):
                return 401, None
            raise SolarEdgeResponseError(f"{method} {path} returned no JSON") from err
