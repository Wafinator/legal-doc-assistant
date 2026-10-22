"""Request logging and request IDs.

Written as plain ASGI middleware rather than with @app.middleware("http").
The decorator version only sees the response *start*, so for a streamed
answer it would log a latency of a few milliseconds. Wrapping `send` lets
us log when the last byte of the body goes out, which is the real duration.
"""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_setup import request_id_var

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"
# Accept a caller's request ID only if it looks sane, so a client can't inject
# arbitrary text (newlines, huge strings) into our logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)  # every log line in this request gets it
        started = time.perf_counter()
        status_code = 500  # if the app crashes before responding, that's what the client gets

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((REQUEST_ID_HEADER.encode(), request_id.encode()))
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                log.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status_code,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    },
                )

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
