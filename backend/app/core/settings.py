"""Re-export application settings for backward compatibility and convenience."""

from app.core.config import Settings, settings

__all__ = ["Settings", "settings"]
