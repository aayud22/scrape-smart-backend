"""Shared error helpers: log the real error, return a safe message to the client."""

import logging

from fastapi import HTTPException

logger = logging.getLogger("scrapesmart")


def internal_error(message: str) -> HTTPException:
    """Call inside an `except` block. Logs the traceback; returns a generic 500."""
    logger.exception(message)
    return HTTPException(status_code=500, detail=message)
