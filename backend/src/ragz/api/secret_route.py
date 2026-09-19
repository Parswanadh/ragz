"""Validation responses for write-only secret settings must not echo submitted input."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class SecretSafeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=422,
                    media_type="application/problem+json",
                    content={
                        "type": "about:blank",
                        "title": "Invalid settings",
                        "status": 422,
                        "detail": "; ".join(error["msg"] for error in exc.errors()),
                    },
                )

        return guarded
