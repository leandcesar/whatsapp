#!/usr/bin/env python

import json
import logging
import sys
from typing import Any, Dict, Optional, Sequence, Union
from urllib.parse import quote as _uriquote

import requests

from . import __version__
from .errors import (
    BadRequest,
    Forbidden,
    HTTPException,
    NotFound,
    Unauthorized,
    WhatsappServerError,
)

__all__ = (
    "Route",
    "HTTPClient",
)

_log = logging.getLogger(__name__)

API_VERSION: int = 15


class Route:
    """Represents an HTTP route to the WhatsApp Business Cloud API."""

    def __init__(self, method: str, path: str, **parameters: Any) -> None:
        self.path: str = path
        self.method: str = method
        url = self.base + self.path
        if parameters:
            url = url.format_map(
                {
                    k: _uriquote(v) if isinstance(v, str) else v
                    for k, v in parameters.items()
                }
            )
        self.url: str = url

    @property
    def base(self) -> str:
        return f"https://graph.facebook.com/v{API_VERSION}.0"


class HTTPClient:
    """Represents an HTTP client sending HTTP requests to the WhatsApp Business Cloud API."""

    def __init__(
        self,
        *,
        proxy: Optional[str] = None,
        proxy_auth: Optional[requests.auth.HTTPProxyAuth] = None,
    ) -> None:
        self.__session: requests.Session = None  # filled in start
        self.phone_id: Optional[str] = None
        self.token: Optional[str] = None
        self.proxy: Optional[str] = proxy
        self.proxy_auth: Optional[requests.auth.HTTPProxyAuth] = proxy_auth
        user_agent = (
            "WhatsappBot (https://github.com/leandcesar/whatsapp., {0}) Python/{1[0]}.{1[1]} requests/{2}"
        )
        self.user_agent: str = user_agent.format(
            __version__, sys.version_info, requests.__version__
        )

    def start(self, phone_id: str, token: str) -> Dict[str, Any]:
        self.__session = requests.Session()
        last_phone_id, self.phone_id = self.phone_id, phone_id
        last_token, self.token = self.token, token
        try:
            data = self.get_business_profile(phone_id)
        except HTTPException as e:
            self.phone_id = last_phone_id
            self.token = last_token
            raise HTTPException("Improper phone_id and/or token has been passed.") from e
        return data

    def restart(self) -> None:
        self.__session = requests.Session()

    def close(self) -> None:
        if self.__session:
            self.__session.close()

    def request(
        self,
        route: Route,
        *,
        files: Optional[Sequence[Dict[str, str]]] = None,  
        **kwargs: Any,
    ) -> Any:
        method = route.method
        url = route.url
        headers: dict[str, str] = {"User-Agent": self.user_agent}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
            data = kwargs.pop("json")
            kwargs["data"] = (
                data
                if isinstance(data, dict)
                else json.dumps(data, separators=(",", ":"), ensure_ascii=True)
            )
        kwargs["headers"] = headers

        if self.proxy is not None:
            kwargs["proxy"] = self.proxy
        if self.proxy_auth is not None:
            kwargs["proxy_auth"] = self.proxy_auth

        response: Optional[requests.Response] = None
        data: Optional[Union[Dict[str, Any], str]] = None

        if files:
            for f in files:
                kwargs["files"] = [("file", (f["filename"], open(f["file"], "rb"), f["mime_type"]))]

        try:
            with self.__session.request(method, url, **kwargs) as response:
                try:
                    data = response.json()
                except requests.exceptions.JSONDecodeError:
                    data = response.text
                _log.debug(f"{method} {url} with {data!r} has returned {response.status_code}")
                if 200 <= response.status_code < 300:
                    return data
                elif response.status == 400:
                    raise BadRequest(response, data)
                elif response.status == 401:
                    raise Unauthorized(response, data)
                elif response.status == 403:
                    raise Forbidden(response, data)
                elif response.status == 404:
                    raise NotFound(response, data)
                elif response.status_code == 429:
                    raise HTTPException(response, data)
                elif response.status >= 500:
                    raise WhatsappServerError(response, data)
                else:
                    raise HTTPException(response, data)
        except OSError as e:
            raise e

        if response is not None:
            if response.status >= 500:
                raise WhatsappServerError(response, data)
            raise HTTPException(response, data)
        raise RuntimeError("Unreachable code in HTTP handling")

    def fetch_business_profile(self) -> Dict[str, Any]:
        route = Route("GET", "/{phone_id}/whatsapp_business_profile", phone_id=self.phone_id)
        return self.request(route)

    def send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        route = Route("POST", "/{phone_id}/messages", phone_id=self.phone_id)
        return self.request(route, json=payload)

    def read_message(self, message_id: str) -> Dict[str, Any]:
        route = Route("POST", "/{phone_id}/messages", phone_id=self.phone_id)
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        return self.request(route, json=payload)

    def upload_media(self, file: str, filename: str, mime_type: str) -> Dict[str, Any]:
        route = Route("POST", "/{phone_id}/media", phone_id=self.phone_id)
        payload = {"messaging_product": "whatsapp"}
        files = [{"filename": filename, "file": file, "mime_type": mime_type}]
        return self.request(route, json=payload, files=files)

    def fetch_media_url(self, media_id: str) -> Dict[str, Any]:
        route = Route("GET", "/{media_id}", media_id=media_id)
        return self.request(route)

    def delete_media(self, media_id: str) -> Dict[str, Any]:
        route = Route("DELETE", "/{media_id}", media_id=media_id)
        return self.request(route)

    def download_media(self, media_url: str) -> Dict[str, Any]:
        headers: dict[str, str] = {"User-Agent": self.user_agent}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        with self.__session.get(media_url, headers=headers) as response:
            _log.debug(f"GET {media_url} has returned {response.status_code}")
            if response.status_code == 200:
                return response.content
            elif response.status_code == 404:
                raise NotFound(response, "asset not found")
            elif response.status_code == 403:
                raise Forbidden(response, "cannot retrieve asset")
            else:
                raise HTTPException(response, "failed to get asset")
