"""API error types and factory helpers for consistent error responses."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import status
from pydantic import BaseModel


class ErrorCode:  # pylint: disable=too-few-public-methods
    """Namespace of stable error code string constants."""

    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    SERVER_ERROR = "SERVER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"


class ErrorResponse(BaseModel):
    """Serialized error payload returned to API clients."""

    code: str
    message: str
    details: Optional[Any] = None


class ApiError(Exception):
    """Exception carrying an HTTP status code and structured error fields."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Any] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def not_found(message: str = "Resource not found", details: Optional[Any] = None) -> ApiError:
    """Build a 404 Not Found ApiError."""
    return ApiError(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ErrorCode.NOT_FOUND,
        message=message,
        details=details,
    )


def conflict(message: str = "Conflict", details: Optional[Any] = None) -> ApiError:
    """Build a 409 Conflict ApiError."""
    return ApiError(
        status_code=status.HTTP_409_CONFLICT,
        code=ErrorCode.CONFLICT,
        message=message,
        details=details,
    )


def unauthorized(message: str = "Unauthorized", details: Optional[Any] = None) -> ApiError:
    """Build a 401 Unauthorized ApiError."""
    return ApiError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=ErrorCode.UNAUTHORIZED,
        message=message,
        details=details,
    )


def quota_exceeded(message: str = "Quota exceeded", details: Optional[Any] = None) -> ApiError:
    """Build a 429 ApiError for exceeded quotas."""
    return ApiError(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        code=ErrorCode.QUOTA_EXCEEDED,
        message=message,
        details=details,
    )


def server_error(message: str = "Server error", details: Optional[Any] = None) -> ApiError:
    """Build a 500 Internal Server Error ApiError."""
    return ApiError(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ErrorCode.SERVER_ERROR,
        message=message,
        details=details,
    )


def rate_limited(message: str = "Rate limit exceeded", details: Optional[Any] = None) -> ApiError:
    """Build a 429 ApiError for rate-limited requests."""
    return ApiError(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        code=ErrorCode.RATE_LIMITED,
        message=message,
        details=details,
    )
