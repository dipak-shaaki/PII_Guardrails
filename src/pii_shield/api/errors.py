import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pii_shield.exceptions import (
    AllProvidersFailedError,
    DetectionError,
    InvalidSessionIdError,
    PIIShieldError,
    ProviderRequestError,
    SessionBusyError,
    SessionNotFoundError,
    SessionStoreError,
)

logger = logging.getLogger(__name__)


def _register(
    app: FastAPI,
    exc_type: type[Exception],
    status: int,
    message: str,
    log_level: int = logging.WARNING,
) -> None:
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        # Log the type only: exception text could contain user data.
        logger.log(log_level, "%s -> HTTP %d", type(exc).__name__, status)
        return JSONResponse(status_code=status, content={"error": message})

    app.add_exception_handler(exc_type, handler)


def register_error_handlers(app: FastAPI) -> None:
    # Starlette picks the most specific class in the MRO, so order doesn't matter.
    E = logging.ERROR
    _register(app, InvalidSessionIdError, 422, "Invalid session id.")
    _register(app, SessionNotFoundError, 404, "Session not found or expired.")
    _register(app, SessionBusyError, 409, "This session is busy. Try again shortly.")
    _register(app, SessionStoreError, 503, "Session storage is unavailable.", E)
    _register(
        app, DetectionError, 503,
        "The safety check is unavailable, so your message was not processed.", E,
    )
    _register(app, AllProvidersFailedError, 503, "The language model is temporarily unavailable.", E)
    _register(app, ProviderRequestError, 502, "The language model request was rejected.", E)
    _register(app, PIIShieldError, 500, "Internal error.", E)