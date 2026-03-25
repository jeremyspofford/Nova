"""Tests for envelope encryption credential provider."""
import os

import pytest
from cryptography.exceptions import InvalidTag

from nova_worker_common.credentials.builtin import BuiltinCredentialProvider

# Stable test key — 32 random bytes as hex
TEST_MASTER_KEY = "a" * 64


@pytest.fixture
def provider():
    return BuiltinCredentialProvider(TEST_MASTER_KEY)


class TestEncryptDecryptRoundtrip:
    def test_basic_roundtrip(self, provider):
        plaintext = "sk-secret-api-key-12345"
        ciphertext = provider.encrypt("tenant-1", plaintext)
        assert provider.decrypt("tenant-1", ciphertext) == plaintext

    def test_unicode_roundtrip(self, provider):
        plaintext = "password-with-unicode-\u00e9\u00e0\u00fc"
        ciphertext = provider.encrypt("tenant-1", plaintext)
        assert provider.decrypt("tenant-1", ciphertext) == plaintext


class TestTenantIsolation:
    def test_different_tenants_different_ciphertext(self, provider):
        plaintext = "same-secret"
        ct1 = provider.encrypt("tenant-1", plaintext)
        ct2 = provider.encrypt("tenant-2", plaintext)
        # Ciphertext must differ (different tenant keys + random nonces)
        assert ct1 != ct2

    def test_wrong_tenant_fails(self, provider):
        ciphertext = provider.encrypt("tenant-1", "secret")
        with pytest.raises(InvalidTag):
            provider.decrypt("tenant-2", ciphertext)


class TestTamperDetection:
    def test_flipped_bit_fails(self, provider):
        ciphertext = provider.encrypt("tenant-1", "secret")
        # Flip a byte in the encrypted plaintext region
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0xFF
        with pytest.raises(InvalidTag):
            provider.decrypt("tenant-1", bytes(tampered))

    def test_truncated_ciphertext_fails(self, provider):
        ciphertext = provider.encrypt("tenant-1", "secret")
        with pytest.raises(Exception):
            provider.decrypt("tenant-1", ciphertext[:50])


class TestEdgeCases:
    def test_empty_plaintext(self, provider):
        ciphertext = provider.encrypt("tenant-1", "")
        assert provider.decrypt("tenant-1", ciphertext) == ""

    def test_long_plaintext(self, provider):
        plaintext = "x" * 100_000
        ciphertext = provider.encrypt("tenant-1", plaintext)
        assert provider.decrypt("tenant-1", ciphertext) == plaintext

    def test_invalid_master_key_length(self):
        with pytest.raises(ValueError, match="64 hex"):
            BuiltinCredentialProvider("tooshort")

    def test_random_master_key(self):
        key = os.urandom(32).hex()
        p = BuiltinCredentialProvider(key)
        ct = p.encrypt("t", "data")
        assert p.decrypt("t", ct) == "data"
