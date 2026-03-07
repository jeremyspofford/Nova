"""Base class for platform adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import FastAPI


class PlatformAdapter(ABC):
    """
    Interface that each platform adapter implements.

    Lifecycle:
      1. __init__() — validate config (e.g. token present)
      2. setup(app) — register routes/start polling
      3. shutdown() — clean up connections
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Short identifier: 'telegram', 'slack', etc."""
        ...

    @abstractmethod
    async def setup(self, app: FastAPI) -> None:
        """Register webhook routes or start background polling."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources (stop polling, close connections)."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this adapter has the required config (e.g. bot token)."""
        ...
