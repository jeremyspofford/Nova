"""Built-in envelope-encryption credential provider.

Encryption layout (all values concatenated as raw bytes)::

    data_key_nonce (12 bytes)
    || encrypted_data_key (48 bytes = 32-byte key + 16-byte GCM tag)
    || plaintext_nonce (12 bytes)
    || encrypted_plaintext (variable + 16-byte GCM tag)
"""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


class BuiltinCredentialProvider:
    """Sync-only envelope encryption using AES-256-GCM + HKDF tenant subkeys.

    Args:
        master_key_hex: 64-character hex string (32 bytes).
    """

    def __init__(self, master_key_hex: str) -> None:
        if len(master_key_hex) != 64:
            raise ValueError("master_key_hex must be exactly 64 hex characters (32 bytes)")
        self._master_key = bytes.fromhex(master_key_hex)

    def _derive_tenant_key(self, tenant_id: str) -> bytes:
        """Derive a 32-byte tenant subkey via HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=tenant_id.encode(),
        )
        return hkdf.derive(self._master_key)

    def encrypt(self, tenant_id: str, plaintext: str) -> bytes:
        """Envelope-encrypt *plaintext* under a tenant-specific subkey.

        Returns concatenated ciphertext bytes (see module docstring for layout).
        """
        tenant_key = self._derive_tenant_key(tenant_id)

        # Generate a random 256-bit data key
        data_key = os.urandom(32)

        # Encrypt the data key with the tenant subkey (AES-256-GCM)
        dk_nonce = os.urandom(12)
        dk_aesgcm = AESGCM(tenant_key)
        encrypted_data_key = dk_aesgcm.encrypt(dk_nonce, data_key, None)  # 32 + 16 = 48 bytes

        # Encrypt the plaintext with the data key (AES-256-GCM)
        pt_nonce = os.urandom(12)
        pt_aesgcm = AESGCM(data_key)
        encrypted_plaintext = pt_aesgcm.encrypt(pt_nonce, plaintext.encode(), None)

        return dk_nonce + encrypted_data_key + pt_nonce + encrypted_plaintext

    def decrypt(self, tenant_id: str, ciphertext: bytes) -> str:
        """Decrypt envelope-encrypted *ciphertext* for the given tenant.

        Raises ``cryptography.exceptions.InvalidTag`` on tamper or wrong tenant.
        """
        tenant_key = self._derive_tenant_key(tenant_id)

        # Parse layout
        dk_nonce = ciphertext[:12]
        encrypted_data_key = ciphertext[12:60]  # 48 bytes
        pt_nonce = ciphertext[60:72]
        encrypted_plaintext = ciphertext[72:]

        # Decrypt the data key
        dk_aesgcm = AESGCM(tenant_key)
        data_key = dk_aesgcm.decrypt(dk_nonce, encrypted_data_key, None)

        # Decrypt the plaintext
        pt_aesgcm = AESGCM(data_key)
        plaintext = pt_aesgcm.decrypt(pt_nonce, encrypted_plaintext, None)

        return plaintext.decode()
