"""
Application configuration and feature flags.

This module provides centralized configuration management for the VOICEcheck application,
including feature flags for backward compatibility and environment-based settings.

Feature Flags:
- FEATURE_FLAG_AUTH: Enable/disable the new authentication and organization system
  When False: System works in legacy mode without authentication (backward compatible)
  When True: Full auth system with users, organizations, and sessions is enabled

Usage:
    from app.config import settings, FEATURE_FLAG_AUTH

    if FEATURE_FLAG_AUTH:
        # Use new auth system
        pass
    else:
        # Legacy mode
        pass
"""

import os
from typing import Optional
from functools import lru_cache


class Settings:
    """
    Centralized application settings.

    Loads configuration from environment variables with sensible defaults.
    All settings are immutable after initialization.
    """

    # Feature Flags
    FEATURE_FLAG_AUTH: bool = os.getenv(
        "FEATURE_FLAG_AUTH",
        "false"
    ).lower() in ("true", "1", "yes", "on")

    # JWT Configuration
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY",
        "voicecheck-secret-key-change-in-production"
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30")
    )

    # Password Security
    PASSWORD_MIN_LENGTH: int = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
    PASSWORD_MAX_LENGTH: int = int(os.getenv("PASSWORD_MAX_LENGTH", "128"))

    # Session Configuration
    SESSION_EXPIRE_HOURS: int = int(os.getenv("SESSION_EXPIRE_HOURS", "24"))
    MAX_SESSIONS_PER_USER: int = int(os.getenv("MAX_SESSIONS_PER_USER", "10"))

    # Organization Settings
    MAX_ORGANIZATIONS_PER_USER: int = int(
        os.getenv("MAX_ORGANIZATIONS_PER_USER", "10")
    )
    MAX_MEMBERS_PER_ORGANIZATION: int = int(
        os.getenv("MAX_MEMBERS_PER_ORGANIZATION", "100")
    )

    # Default Admin User (created when auth is first enabled)
    DEFAULT_ADMIN_EMAIL: Optional[str] = os.getenv("DEFAULT_ADMIN_EMAIL")
    DEFAULT_ADMIN_PASSWORD: Optional[str] = os.getenv("DEFAULT_ADMIN_PASSWORD")
    DEFAULT_ADMIN_NAME: str = os.getenv("DEFAULT_ADMIN_NAME", "Admin")

    def __init__(self):
        """Validate configuration on initialization."""
        if self.FEATURE_FLAG_AUTH:
            if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY == "voicecheck-secret-key-change-in-production":
                import warnings
                warnings.warn(
                    "Using default JWT secret key! Change JWT_SECRET_KEY in production!"
                )

    @property
    def auth_enabled(self) -> bool:
        """Alias for FEATURE_FLAG_AUTH for cleaner code."""
        return self.FEATURE_FLAG_AUTH


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure only one Settings instance is created.
    Call this function to access settings throughout the application.

    Returns:
        Settings: Cached settings instance
    """
    return Settings()


# Global settings instance for direct import
settings = get_settings()

# Direct exports for commonly used values
FEATURE_FLAG_AUTH = settings.FEATURE_FLAG_AUTH
AUTH_ENABLED = settings.auth_enabled
