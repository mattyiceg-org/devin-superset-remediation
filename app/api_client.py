from __future__ import annotations

from typing import Any, Optional

import requests


class ApiClient:
    """Bearer-token-authenticated JSON API client. Subclasses set base_url
    and any extra default headers (e.g. an API version header) in __init__;
    callers get plain get/post/put/delete that raise requests.RequestException
    on non-2xx (via raise_for_status) instead of each call site building its
    own requests boilerplate."""

    default_timeout = 30

    def __init__(self, base_url: str, token: str, extra_headers: Optional[dict] = None):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            self._session.headers.update(extra_headers)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        # TODO: retry with backoff on 5xx/timeout. For now, callers treat any
        # RequestException as "skip this item this cycle, try again next
        # tick" rather than crashing the background loop.
        kwargs.setdefault("timeout", self.default_timeout)
        resp = self._session.request(method, f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def get(self, path: str, **kwargs) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self._request("DELETE", path, **kwargs)
