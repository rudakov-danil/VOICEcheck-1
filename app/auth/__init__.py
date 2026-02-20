"""
Authentication and Authorization Module.
"""

# Models can be imported directly
from .models import User, Organization, Membership, Session, UserRole

# Lazy imports for service and dependencies (they require JWT)
__all__ = [
    "User",
    "Organization",
    "Membership",
    "Session",
    "UserRole",
]

def __getattr__(name):
    """Lazy import for modules that require JWT dependencies."""
    if name == "AuthService":
        from .service import AuthService
        return AuthService
    elif name == "OrganizationsService":
        from .organizations import OrganizationsService
        return OrganizationsService
    elif name == "get_optional_user":
        from .dependencies import get_optional_user
        return get_optional_user
    elif name == "require_auth":
        from .dependencies import require_auth
        return require_auth
    elif name == "get_current_user":
        from .dependencies import get_current_user
        return get_current_user
    elif name == "get_token_from_header":
        from .dependencies import get_token_from_header
        return get_token_from_header
    else:
        raise AttributeError(f"module {__name__} has no attribute {name}")

__all__.extend([
    "AuthService",
    "OrganizationsService",
    "get_optional_user",
    "require_auth",
    "get_current_user",
    "get_token_from_header",
])
