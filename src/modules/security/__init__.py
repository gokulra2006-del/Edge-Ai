"""Security hardening module for Sentinel-AI Edge."""
from src.modules.security.user_store import (
    UserManager,
    hash_password,
    verify_password,
    is_hash,
)
from src.modules.security.session_manager import (
    SessionManager,
    SESSION_MANAGER,
)
from src.modules.security.rate_limiter import (
    LoginRateLimiter,
    RATE_LIMITER,
)
from src.modules.security.permission_matrix import (
    ENDPOINT_PERMISSIONS,
    check_endpoint_permission,
)

__all__ = [
    "UserManager",
    "hash_password",
    "verify_password",
    "is_hash",
    "SessionManager",
    "SESSION_MANAGER",
    "LoginRateLimiter",
    "RATE_LIMITER",
    "ENDPOINT_PERMISSIONS",
    "check_endpoint_permission",
]
