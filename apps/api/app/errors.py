from __future__ import annotations

from typing import Any, Optional

from fastapi import status
from pydantic import BaseModel


class ErrorCode:
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str, details: Optional[Any] = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def not_found(message: str = "Resource not found", details: Optional[Any] = None) -> ApiError:
    return ApiError(status_code=status.HTTP_404_NOT_FOUND, code=ErrorCode.NOT_FOUND, message=message, details=details)


def conflict(message: str = "Conflict", details: Optional[Any] = None) -> ApiError:
    return ApiError(status_code=status.HTTP_409_CONFLICT, code=ErrorCode.CONFLICT, message=message, details=details)


def server_error(message: str = "Server error", details: Optional[Any] = None) -> ApiError:
    return ApiError(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, code=ErrorCode.SERVER_ERROR, message=message, details=details)


def rate_limited(message: str = "Rate limit exceeded", details: Optional[Any] = None) -> ApiError:
    return ApiError(status_code=status.HTTP_429_TOO_MANY_REQUESTS, code=ErrorCode.RATE_LIMITED, message=message, details=details)
