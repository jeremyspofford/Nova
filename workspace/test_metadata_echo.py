"""
test_metadata_echo.py
=====================
Unit tests for :mod:`metadata_echo`.

Covers:
- Metadata construction and dict serialisation
- Encoding pipeline (JSON → UTF-8 → base64)
- Decoding pipeline (base64 → UTF-8 → JSON → Metadata)
- Round-trip / echo fidelity for multiple payloads
- Encoding stability (idempotent re-encode)
- Edge cases: empty tags/extra, unicode strings, nested extra values
- Error handling: bad base64, bad JSON, missing required fields
"""

import base64
import json
import unittest

from metadata_echo import Metadata, decode, echo, encode, run_echo_test


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meta(**kwargs) -> Metadata:
    """Return a Metadata with sensible defaults, overridden by *kwargs*."""
    defaults = dict(
        name="test-agent",
        version="0.1.0",
        timestamp="2024-06-01T12:00:00+00:00",
        tags=["unit", "test"],
        extra={"env": "ci"},
    )
    defaults.update(kwargs)
    return Metadata(**defaults)


# ---------------------------------------------------------------------------
# Metadata dataclass tests
# ---------------------------------------------------------------------------

class TestMetadataDataclass(unittest.TestCase):

    def test_basic_construction(self):
        m = _make_meta()
        self.assertEqual(m.name, "test-agent")
        self.assertEqual(m.version, "0.1.0")
        self.assertEqual(m.tags, ["unit", "test"])
        self.assertEqual(m.extra, {"env": "ci"})

    def test_default_timestamp_is_set(self):
        m = Metadata(name="x", version="1")
        self.assertIsInstance(m.timestamp, str)
        self.assertTrue(len(m.timestamp) > 0)

    def test_default_tags_and_extra_are_empty(self):
        m = Metadata(name="x", version="1", timestamp="t")
        self.assertEqual(m.tags, [])
        self.assertEqual(m.extra, {})

    def test_default_mutable_fields_are_independent(self):
        """Each instance must get its own list/dict, not a shared one."""
        a = Metadata(name="a", version="1", timestamp="t")
        b = Metadata(name="b", version="1", timestamp="t")
        a.tags.append("hello")
        self.assertEqual(b.tags, [], "Mutable defaults must not be shared")

    def test_to_dict_round_trip(self):
        m = _make_meta()
        d = m.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["name"], m.name)
        self.assertEqual(d["version"], m.version)
        self.assertEqual(d["tags"], m.tags)
        self.assertEqual(d["extra"], m.extra)

    def test_from_dict_reconstructs_correctly(self):
        m = _make_meta()
        m2 = Metadata.from_dict(m.to_dict())
        self.assertEqual(m, m2)

    def test_equality_same_fields(self):
        m1 = _make_meta()
        m2 = _make_meta()
        self.assertEqual(m1, m2)

    def test_inequality_different_name(self):
        m1 = _make_meta(name="alpha")
        m2 = _make_meta(name="beta")
        self.assertNotEqual(m1, m2)

    def test_inequality_different_version(self):
        m1 = _make_meta(version="1.0.0")
        m2 = _make_meta(version="2.0.0")
        self.assertNotEqual(m1, m2)

    def test_equality_not_implemented_for_non_metadata(self):
        m = _make_meta()
        result = m.__eq__("not a metadata")
        self.assertIs(result, NotImplemented)


# ---------------------------------------------------------------------------
# Encoding tests
# ---------------------------------------------------------------------------

class TestEncode(unittest.TestCase):

    def test_returns_string(self):
        m = _make_meta()
        self.assertIsInstance(encode(m), str)

    def test_output_is_valid_base64(self):
        m = _make_meta()
        encoded = encode(m)
        # Should not raise
        raw = base64.b64decode(encoded.encode("ascii"))
        self.assertIsInstance(raw, bytes)

    def test_decoded_bytes_are_valid_json(self):
        m = _make_meta()
        encoded = encode(m)
        raw = base64.b64decode(encoded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        self.assertIsInstance(data, dict)

    def test_json_contains_all_fields(self):
        m = _make_meta()
        encoded = encode(m)
        raw = base64.b64decode(encoded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        for key in ("name", "version", "timestamp", "tags", "extra"):
            self.assertIn(key, data)

    def test_json_keys_are_sorted(self):
        """encode() must use sort_keys=True for stable output."""
        m = _make_meta()
        encoded = encode(m)
        raw = base64.b64decode(encoded.encode("ascii"))
        json_str = raw.decode("utf-8")
        keys = [k for k in json.loads(json_str)]
        self.assertEqual(keys, sorted(keys))

    def test_deterministic_for_same_input(self):
        m = _make_meta()
        self.assertEqual(encode(m), encode(m))

    def test_different_metadata_produces_different_encoding(self):
        m1 = _make_meta(name="alpha")
        m2 = _make_meta(name="beta")
        self.assertNotEqual(encode(m1), encode(m2))


# ---------------------------------------------------------------------------
# Decoding tests
# ---------------------------------------------------------------------------

class TestDecode(unittest.TestCase):

    def test_decode_inverts_encode(self):
        m = _make_meta()
        self.assertEqual(decode(encode(m)), m)

    def test_raises_value_error_on_bad_base64(self):
        with self.assertRaises(ValueError):
            decode("!!!not-base64!!!")

    def test_raises_value_error_on_non_json_payload(self):
        # Valid base64 but not JSON
        bad = base64.b64encode(b"this is not json").decode("ascii")
        with self.assertRaises(ValueError):
            decode(bad)

    def test_raises_key_error_on_missing_name(self):
        payload = {"version": "1.0", "timestamp": "t", "tags": [], "extra": {}}
        encoded = base64.b64encode(
            json.dumps(payload).encode("utf-8")
        ).decode("ascii")
        with self.assertRaises(KeyError):
            decode(encoded)

    def test_raises_key_error_on_missing_version(self):
        payload = {"name": "x", "timestamp": "t", "tags": [], "extra": {}}
        encoded = base64.b64encode(
            json.dumps(payload).encode("utf-8")
        ).decode("ascii")
        with self.assertRaises(KeyError):
            decode(encoded)


# ---------------------------------------------------------------------------
# Round-trip / echo tests
# ---------------------------------------------------------------------------

class TestEcho(unittest.TestCase):

    def _assert_round_trip(self, metadata: Metadata):
        result = echo(metadata)
        self.assertEqual(metadata, result,
                         f"Round-trip failed for: {metadata.to_dict()}")

    def test_echo_standard_payload(self):
        self._assert_round_trip(_make_meta())

    def test_echo_empty_tags_and_extra(self):
        self._assert_round_trip(
            Metadata(name="bare", version="0.0.1", timestamp="2024-01-01T00:00:00+00:00")
        )

    def test_echo_unicode_name(self):
        self._assert_round_trip(
            _make_meta(name="ünïcödé-ägënt-名前")
        )

    def test_echo_unicode_in_extra(self):
        self._assert_round_trip(
            _make_meta(extra={"greeting": "こんにちは", "emoji": "🚀"})
        )

    def test_echo_many_tags(self):
        self._assert_round_trip(
            _make_meta(tags=[f"tag-{i}" for i in range(50)])
        )

    def test_echo_nested_extra(self):
        self._assert_round_trip(
            _make_meta(extra={"nested": {"a": {"b": {"c": 42}}}, "list": [1, 2, 3]})
        )

    def test_echo_numeric_version(self):
        self._assert_round_trip(_make_meta(version="3.14.159"))

    def test_echo_preserves_timestamp_exactly(self):
        ts = "2099-12-31T23:59:59.999999+00:00"
        m = _make_meta(timestamp=ts)
        self.assertEqual(echo(m).timestamp, ts)

    def test_echo_preserves_tags_order(self):
        tags = ["z", "a", "m", "b"]
        m = _make_meta(tags=tags)
        self.assertEqual(echo(m).tags, tags)

    def test_encoding_stability(self):
        """Re-encoding the decoded object must produce the same base64 string."""
        m = _make_meta()
        encoded_first = encode(m)
        decoded = decode(encoded_first)
        encoded_second = encode(decoded)
        self.assertEqual(encoded_first, encoded_second)


# ---------------------------------------------------------------------------
# run_echo_test() integration test
# ---------------------------------------------------------------------------

class TestRunEchoTest(unittest.TestCase):

    def test_run_echo_test_default_payload_passes(self):
        """run_echo_test() must complete without raising."""
        try:
            run_echo_test()
        except AssertionError as exc:
            self.fail(f"run_echo_test() raised AssertionError: {exc}")

    def test_run_echo_test_custom_payload_passes(self):
        custom = _make_meta(
            name="custom-check",
            version="9.9.9",
            tags=["custom"],
            extra={"key": "value"},
        )
        try:
            run_echo_test(custom)
        except AssertionError as exc:
            self.fail(f"run_echo_test(custom) raised AssertionError: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
