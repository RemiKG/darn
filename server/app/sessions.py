"""Anonymous session cookie — the needle is keyed by it.

Pure ASGI middleware (no itsdangerous, no signing: the session is an anonymous
uuid, not an identity). The cookie is set on the first response and the id is
available to handlers via `session_id(request)`.
"""

from __future__ import annotations

import uuid
from http.cookies import SimpleCookie

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE_NAME = "darn_session"


class SessionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cookie_header = ""
        for key, value in scope.get("headers", []):
            if key == b"cookie":
                cookie_header = value.decode("latin-1")
                break

        sid = ""
        if cookie_header:
            jar = SimpleCookie()
            try:
                jar.load(cookie_header)
                morsel = jar.get(COOKIE_NAME)
                sid = morsel.value if morsel else ""
            except Exception:
                sid = ""

        fresh = not sid
        if fresh:
            sid = str(uuid.uuid4())

        state = scope.setdefault("state", {})
        state[COOKIE_NAME] = sid

        async def send_wrapper(message: Message) -> None:
            if fresh and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(
                    "set-cookie",
                    f"{COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Lax",
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


def session_id(request: Request) -> str:
    return request.scope["state"][COOKIE_NAME]
