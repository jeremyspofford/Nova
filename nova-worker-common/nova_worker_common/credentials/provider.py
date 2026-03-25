"""Abstract credential provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CredentialHealth:
    valid: bool
    message: str | None = None
    scopes: list[str] | None = field(default=None)


class CredentialProvider(ABC):
    """Interface for credential storage backends."""

    @abstractmethod
    async def store(
        self,
        tenant_id: str,
        credential_data: str,
        label: str,
        scopes: dict | None = None,
    ) -> str:
        """Encrypt and store credential. Returns credential_id."""

    @abstractmethod
    async def retrieve(self, tenant_id: str, credential_id: str) -> str:
        """Retrieve and decrypt credential. Returns plaintext."""

    @abstractmethod
    async def rotate(
        self, tenant_id: str, credential_id: str, new_credential_data: str
    ) -> str:
        """Replace credential with new value. Returns credential_id."""

    @abstractmethod
    async def delete(self, tenant_id: str, credential_id: str) -> None:
        """Delete credential."""

    @abstractmethod
    async def validate(self, tenant_id: str, credential_id: str) -> CredentialHealth:
        """Check if credential is still valid."""
