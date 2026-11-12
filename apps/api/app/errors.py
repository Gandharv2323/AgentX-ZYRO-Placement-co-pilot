"""One error shape for every non-2xx response."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = "", details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "hint": self.hint,
                          "details": self.details}}


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(exc.body(), status_code=exc.status)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a traceback shape, and keep CORS headers so the browser can read it."""
    origin = request.headers.get("origin", "")
    headers = {}
    if origin.startswith(("http://127.0.0.1", "http://localhost")):
        headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                   "Access-Control-Allow-Credentials": "true"}
    return JSONResponse(
        {"error": {"code": "internal", "message": "Something failed on the server.",
                   "hint": "The API log has the details.",
                   "details": {"type": type(exc).__name__}}},
        status_code=500, headers=headers,
    )
