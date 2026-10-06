"""Convenience alias for src.modules.security."""
from src.modules.security import (
    UserManager,
    SessionManager,
    SESSION_MANAGER,
    LoginRateLimiter,
    RATE_LIMITER,
    check_endpoint_permission,
)

__all__ = [
    "UserManager",
    "SessionManager",
    "SESSION_MANAGER",
    "LoginRateLimiter",
    "RATE_LIMITER",
    "check_endpoint_permission",
]
