"""ASGI middleware: request IDs, access logging, security headers, body size limit."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx

logger = logging.getLogger("oryn.access")

SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
    b"cross-origin-opener-policy": b"same-origin",
    # The API serves JSON/SSE only, so a locked-down CSP is safe.
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware:
    """Assigns a request ID, logs timing, and attaches security headers."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")[:64]
        rid = incoming if incoming.replace("-", "").isalnum() and incoming else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                hdrs = list(message.get("headers") or [])
                hdrs.append((b"x-request-id", rid.encode()))

                existing = {k.lower() for k, _ in hdrs}

                # Swagger/ReDoc HTML pages need their own CSP handling.
                docs_paths = {
                    "/docs",
                    "/redoc",
                    "/docs/oauth2-redirect",
                }
                is_docs_route = scope.get("path", "") in docs_paths

                for k, v in SECURITY_HEADERS.items():
                    if k in existing:
                        continue

                    # Keep the strict CSP on API responses, but do not
                    # apply the API-only CSP to documentation pages.
                    if k == b"content-security-policy" and is_docs_route:
                        continue

                    hdrs.append((k, v))

                if self.hsts:
                    hdrs.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_holder["status"],
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            request_id_ctx.reset(token)


class BodySizeLimitMiddleware:
    """Rejects requests whose body exceeds `max_bytes`, without buffering them in memory."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        too_big = False

        async def limited_receive() -> Message:
            nonlocal received, too_big
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        responded = False

        async def guarded_send(message: Message) -> None:
            nonlocal responded
            if too_big and not responded:
                responded = True
                await self._reject(send)
                return
            if not responded:
                await send(message)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"error":{"code":"payload_too_large","message":"Request body is too large.","request_id":"-"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
