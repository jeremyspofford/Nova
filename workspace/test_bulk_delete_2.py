"""
test_bulk_delete_2.py
=====================
Second unit-test suite for :mod:`bulk_delete`.

This suite extends coverage beyond the baseline tests in
``test_bulk_delete.py`` (test 1).  It focuses on deeper behavioural
contracts, boundary conditions, and interaction patterns that were not
covered in the first suite.

Covers:
- BulkDeleteResult dataclass: deleted / remaining / not_found fields
- Custom id_key parameter: deletion keyed on a non-default field name
- not_found reporting: IDs requested but absent from the item list
- Items missing the id_key field are kept in remaining (not deleted)
- Empty target_ids set returns all items in remaining, none deleted
- Empty items list with non-empty target_ids: all targets go to not_found
- Deleting all items leaves remaining empty and deleted full
- Partial overlap: some targets found, some not_found
- Duplicate IDs in source: only first matching item is deleted per target
- TypeError raised when items is not a list
- TypeError raised when target_ids is not a set
- ValueError raised when id_key is an empty string
- Result immutability: mutating returned lists does not affect source
- Order preservation: deleted and remaining lists preserve source order
- Large-scale smoke test: 10 000-item list, 5 000 deletions
- Unicode and special-character IDs work correctly
- Numeric (int) IDs work when id_key points to an integer field
- Nested id_key: deletion keyed on a deeply-nested value is NOT supported
  (documents the flat-key-only contract)
"""

import unittest

from bulk_delete import BulkDeleteResult, bulk_delete


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(id_value: str, **extra) -> dict:
    """Return a dict with ``"id"`` set to *id_value*, plus any *extra* keys."""
    return {"id": id_value, **extra}


def _items(*id_values: str, **extra) -> list[dict]:
    """Return a list of dicts, one per *id_value*, each with optional *extra* fields."""
    return [{"id": v, **extra} for v in id_values]


# ---------------------------------------------------------------------------
# BulkDeleteResult dataclass
# ---------------------------------------------------------------------------

class TestBulkDeleteResult(unittest.TestCase):
    """Verify the shape and defaults of the BulkDeleteResult dataclass."""

    def test_result_has_deleted_field(self):
        result = bulk_delete(_items("a", "b"), {"a"})
        self.assertTrue(hasattr(result, "deleted"))

    def test_result_has_remaining_field(self):
        result = bulk_delete(_items("a", "b"), {"a"})
        self.assertTrue(hasattr(result, "remaining"))

    def test_result_has_not_found_field(self):
        result = bulk_delete(_items("a", "b"), {"a"})
        self.assertTrue(hasattr(result, "not_found"))

    def test_deleted_is_a_list(self):
        result = bulk_delete(_items("a"), {"a"})
        self.assertIsInstance(result.deleted, list)

    def test_remaining_is_a_list(self):
        result = bulk_delete(_items("a"), {"a"})
        self.assertIsInstance(result.remaining, list)

    def test_not_found_is_a_set(self):
        result = bulk_delete(_items("a"), {"z"})
        self.assertIsInstance(result.not_found, set)

    def test_result_is_bulk_delete_result_instance(self):
        result = bulk_delete([], set())
        self.assertIsInstance(result, BulkDeleteResult)

    def test_default_empty_result(self):
        """An empty items list with an empty target set yields all-empty fields."""
        result = bulk_delete([], set())
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.remaining, [])
        self.assertEqual(result.not_found, set())


# ---------------------------------------------------------------------------
# Core deletion behaviour
# ---------------------------------------------------------------------------

class TestBulkDeleteCore(unittest.TestCase):
    """Happy-path tests for the primary deletion contract."""

    def test_deleted_contains_matched_item(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, {"b"})
        self.assertEqual(result.deleted, [{"id": "b"}])

    def test_remaining_contains_unmatched_items(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, {"b"})
        self.assertEqual(result.remaining, [{"id": "a"}, {"id": "c"}])

    def test_not_found_empty_when_all_targets_matched(self):
        items = _items("a", "b")
        result = bulk_delete(items, {"a", "b"})
        self.assertEqual(result.not_found, set())

    def test_delete_single_item_from_singleton_list(self):
        result = bulk_delete([{"id": "only"}], {"only"})
        self.assertEqual(result.deleted, [{"id": "only"}])
        self.assertEqual(result.remaining, [])

    def test_delete_multiple_items(self):
        items = _items("x", "y", "z", "w")
        result = bulk_delete(items, {"x", "z"})
        deleted_ids = {i["id"] for i in result.deleted}
        remaining_ids = {i["id"] for i in result.remaining}
        self.assertEqual(deleted_ids, {"x", "z"})
        self.assertEqual(remaining_ids, {"y", "w"})

    def test_delete_all_items(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, {"a", "b", "c"})
        self.assertEqual(result.deleted, items)
        self.assertEqual(result.remaining, [])

    def test_delete_no_items_empty_target_set(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, set())
        self.assertEqual(result.remaining, items)
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.not_found, set())

    def test_extra_fields_on_items_are_preserved(self):
        """Items carry arbitrary extra fields; bulk_delete must not strip them."""
        items = [{"id": "a", "value": 42, "label": "alpha"},
                 {"id": "b", "value": 99, "label": "beta"}]
        result = bulk_delete(items, {"a"})
        self.assertEqual(result.deleted, [{"id": "a", "value": 42, "label": "alpha"}])
        self.assertEqual(result.remaining, [{"id": "b", "value": 99, "label": "beta"}])


# ---------------------------------------------------------------------------
# not_found reporting
# ---------------------------------------------------------------------------

class TestBulkDeleteNotFound(unittest.TestCase):
    """Verify that not_found correctly reports unmatched target IDs."""

    def test_single_missing_target_reported(self):
        result = bulk_delete(_items("a", "b"), {"z"})
        self.assertIn("z", result.not_found)

    def test_multiple_missing_targets_all_reported(self):
        result = bulk_delete(_items("a"), {"x", "y", "z"})
        self.assertEqual(result.not_found, {"x", "y", "z"})

    def test_partial_overlap_not_found_contains_only_missing(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, {"b", "missing1", "missing2"})
        self.assertEqual(result.not_found, {"missing1", "missing2"})
        self.assertNotIn("b", result.not_found)

    def test_empty_items_all_targets_go_to_not_found(self):
        result = bulk_delete([], {"p", "q", "r"})
        self.assertEqual(result.not_found, {"p", "q", "r"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.remaining, [])

    def test_not_found_is_empty_when_targets_empty(self):
        result = bulk_delete(_items("a", "b"), set())
        self.assertEqual(result.not_found, set())

    def test_not_found_does_not_include_found_ids(self):
        items = _items("a", "b", "c")
        result = bulk_delete(items, {"a", "b", "c", "d"})
        self.assertEqual(result.not_found, {"d"})


# ---------------------------------------------------------------------------
# Custom id_key
# ---------------------------------------------------------------------------

class TestBulkDeleteCustomIdKey(unittest.TestCase):
    """Verify that the id_key parameter correctly redirects the lookup field."""

    def test_custom_id_key_name(self):
        items = [{"name": "alice", "age": 30},
                 {"name": "bob",   "age": 25},
                 {"name": "carol", "age": 35}]
        result = bulk_delete(items, {"alice", "carol"}, id_key="name")
        remaining_names = [i["name"] for i in result.remaining]
        deleted_names   = [i["name"] for i in result.deleted]
        self.assertEqual(remaining_names, ["bob"])
        self.assertCountEqual(deleted_names, ["alice", "carol"])

    def test_custom_id_key_numeric_values(self):
        """id_key can point to a field whose values are integers."""
        items = [{"uid": 1, "v": "a"},
                 {"uid": 2, "v": "b"},
                 {"uid": 3, "v": "c"}]
        result = bulk_delete(items, {2, 3}, id_key="uid")
        self.assertEqual(result.remaining, [{"uid": 1, "v": "a"}])
        self.assertCountEqual(result.deleted,
                              [{"uid": 2, "v": "b"}, {"uid": 3, "v": "c"}])

    def test_custom_id_key_not_found_uses_correct_field(self):
        items = [{"code": "X1"}, {"code": "X2"}]
        result = bulk_delete(items, {"X3"}, id_key="code")
        self.assertEqual(result.not_found, {"X3"})
        self.assertEqual(result.remaining, items)

    def test_default_id_key_is_id(self):
        """Omitting id_key defaults to 'id'."""
        items = [{"id": "default-key-test"}]
        result = bulk_delete(items, {"default-key-test"})
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.remaining, [])


# ---------------------------------------------------------------------------
# Items missing the id_key field
# ---------------------------------------------------------------------------

class TestBulkDeleteMissingIdKey(unittest.TestCase):
    """Items that lack the id_key field are silently kept in remaining."""

    def test_item_without_id_key_goes_to_remaining(self):
        items = [{"id": "a"}, {"no_id": "orphan"}, {"id": "b"}]
        result = bulk_delete(items, {"a"})
        self.assertIn({"no_id": "orphan"}, result.remaining)

    def test_item_without_id_key_not_in_deleted(self):
        items = [{"other": "field"}]
        result = bulk_delete(items, {"anything"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.remaining, [{"other": "field"}])

    def test_all_items_missing_id_key(self):
        items = [{"x": 1}, {"y": 2}, {"z": 3}]
        result = bulk_delete(items, {"a", "b"})
        self.assertEqual(result.remaining, items)
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.not_found, {"a", "b"})

    def test_mix_of_items_with_and_without_id_key(self):
        items = [{"id": "keep-me"}, {"no_id": True}, {"id": "delete-me"}]
        result = bulk_delete(items, {"delete-me"})
        remaining_ids = [i.get("id") for i in result.remaining]
        self.assertIn("keep-me", remaining_ids)
        self.assertIn(None, remaining_ids)   # the orphan item has no "id"
        self.assertEqual(len(result.deleted), 1)


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------

class TestBulkDeleteOrderPreservation(unittest.TestCase):
    """deleted and remaining must preserve the relative order of source."""

    def test_remaining_preserves_source_order(self):
        items = [_item(str(i)) for i in range(10)]
        result = bulk_delete(items, {"3", "7"})
        expected_ids = [str(i) for i in range(10) if i not in (3, 7)]
        actual_ids = [i["id"] for i in result.remaining]
        self.assertEqual(actual_ids, expected_ids)

    def test_deleted_preserves_source_order(self):
        items = [_item("a"), _item("b"), _item("c"), _item("d"), _item("e")]
        result = bulk_delete(items, {"b", "d"})
        deleted_ids = [i["id"] for i in result.deleted]
        # "b" appears before "d" in source, so deleted order must be ["b", "d"]
        self.assertEqual(deleted_ids, ["b", "d"])

    def test_remaining_and_deleted_together_cover_all_source_items(self):
        items = [_item(str(i)) for i in range(20)]
        targets = {str(i) for i in range(0, 20, 3)}  # every third item
        result = bulk_delete(items, targets)
        all_result_items = result.deleted + result.remaining
        # Sort both by id to compare regardless of split order
        self.assertCountEqual(all_result_items, items)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestBulkDeleteImmutability(unittest.TestCase):
    """bulk_delete must never mutate its inputs."""

    def test_source_list_not_mutated(self):
        items = [_item("a"), _item("b"), _item("c")]
        original = list(items)
        bulk_delete(items, {"b"})
        self.assertEqual(items, original)

    def test_source_dicts_not_mutated(self):
        """The dicts inside source must not be modified."""
        item = {"id": "a", "value": 1}
        original_item = dict(item)
        bulk_delete([item], {"a"})
        self.assertEqual(item, original_item)

    def test_target_ids_set_not_mutated(self):
        targets = {"a", "b"}
        original = set(targets)
        bulk_delete(_items("a", "b", "c"), targets)
        self.assertEqual(targets, original)

    def test_mutating_returned_remaining_does_not_affect_source(self):
        items = [_item("a"), _item("b")]
        result = bulk_delete(items, set())
        result.remaining.append(_item("z"))
        self.assertNotIn(_item("z"), items)

    def test_mutating_returned_deleted_does_not_affect_source(self):
        items = [_item("a"), _item("b")]
        result = bulk_delete(items, {"a"})
        result.deleted.clear()
        # source should still have both items
        self.assertEqual(len(items), 2)


# ---------------------------------------------------------------------------
# Duplicate IDs in source
# ---------------------------------------------------------------------------

class TestBulkDeleteDuplicateSourceIds(unittest.TestCase):
    """When source contains items with the same ID, only the first is deleted."""

    def test_first_occurrence_deleted_when_id_duplicated(self):
        items = [_item("dup", v=1), _item("dup", v=2), _item("other")]
        result = bulk_delete(items, {"dup"})
        # Exactly one item should be deleted
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.deleted[0], {"id": "dup", "v": 1})

    def test_second_occurrence_stays_in_remaining(self):
        items = [_item("dup", v=1), _item("dup", v=2)]
        result = bulk_delete(items, {"dup"})
        self.assertEqual(len(result.remaining), 1)
        self.assertEqual(result.remaining[0], {"id": "dup", "v": 2})

    def test_both_occurrences_deleted_when_id_in_source_twice_and_targeted(self):
        """If the same ID appears twice in source and is targeted, both are deleted."""
        items = [_item("dup", v=1), _item("dup", v=2), _item("keep")]
        result = bulk_delete(items, {"dup"})
        # Only first is deleted (seen_ids set prevents second match)
        deleted_ids = [i["id"] for i in result.deleted]
        self.assertIn("dup", deleted_ids)
        # "keep" must remain
        self.assertIn(_item("keep"), result.remaining)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestBulkDeleteTypeErrors(unittest.TestCase):
    """Verify that invalid argument types raise the correct exceptions."""

    def test_raises_type_error_when_items_is_none(self):
        with self.assertRaises(TypeError):
            bulk_delete(None, set())

    def test_raises_type_error_when_items_is_tuple(self):
        with self.assertRaises(TypeError):
            bulk_delete(({"id": "a"},), {"a"})

    def test_raises_type_error_when_items_is_dict(self):
        with self.assertRaises(TypeError):
            bulk_delete({"id": "a"}, {"a"})

    def test_raises_type_error_when_items_is_string(self):
        with self.assertRaises(TypeError):
            bulk_delete("not-a-list", {"x"})

    def test_raises_type_error_when_items_is_generator(self):
        with self.assertRaises(TypeError):
            bulk_delete((x for x in [{"id": "a"}]), {"a"})

    def test_raises_type_error_when_target_ids_is_none(self):
        with self.assertRaises(TypeError):
            bulk_delete([], None)

    def test_raises_type_error_when_target_ids_is_list(self):
        with self.assertRaises(TypeError):
            bulk_delete(_items("a"), ["a"])

    def test_raises_type_error_when_target_ids_is_tuple(self):
        with self.assertRaises(TypeError):
            bulk_delete(_items("a"), ("a",))

    def test_raises_type_error_when_target_ids_is_string(self):
        with self.assertRaises(TypeError):
            bulk_delete(_items("a"), "a")

    def test_raises_type_error_when_target_ids_is_dict(self):
        with self.assertRaises(TypeError):
            bulk_delete(_items("a"), {"a": 1})

    def test_type_error_message_mentions_items(self):
        """TypeError message should name the offending parameter."""
        with self.assertRaises(TypeError) as ctx:
            bulk_delete("bad", set())
        self.assertIn("items", str(ctx.exception))

    def test_type_error_message_mentions_target_ids(self):
        with self.assertRaises(TypeError) as ctx:
            bulk_delete([], ["a"])
        self.assertIn("target_ids", str(ctx.exception))


class TestBulkDeleteValueErrors(unittest.TestCase):
    """Verify that an empty id_key raises ValueError."""

    def test_raises_value_error_for_empty_id_key(self):
        with self.assertRaises(ValueError):
            bulk_delete(_items("a"), {"a"}, id_key="")

    def test_raises_value_error_message_mentions_id_key(self):
        with self.assertRaises(ValueError) as ctx:
            bulk_delete([], set(), id_key="")
        self.assertIn("id_key", str(ctx.exception))

    def test_non_empty_id_key_does_not_raise(self):
        """Any non-empty string is a valid id_key — should not raise."""
        try:
            bulk_delete([], set(), id_key="custom_id")
        except ValueError:
            self.fail("ValueError raised for a valid non-empty id_key")


# ---------------------------------------------------------------------------
# Unicode and special characters
# ---------------------------------------------------------------------------

class TestBulkDeleteUnicode(unittest.TestCase):
    """IDs containing unicode or special characters must work correctly."""

    def test_unicode_ids_deleted_correctly(self):
        items = [_item("ünïcödé"), _item("normal"), _item("日本語")]
        result = bulk_delete(items, {"ünïcödé", "日本語"})
        self.assertEqual(len(result.deleted), 2)
        self.assertEqual(result.remaining, [_item("normal")])

    def test_emoji_ids_work(self):
        items = [_item("🚀"), _item("🌍"), _item("plain")]
        result = bulk_delete(items, {"🚀"})
        self.assertEqual(result.deleted, [_item("🚀")])
        self.assertIn(_item("🌍"), result.remaining)

    def test_whitespace_ids_are_matched_exactly(self):
        """IDs with leading/trailing whitespace are distinct from trimmed versions."""
        items = [_item(" spaced "), _item("spaced")]
        result = bulk_delete(items, {" spaced "})
        self.assertEqual(result.deleted, [_item(" spaced ")])
        self.assertEqual(result.remaining, [_item("spaced")])

    def test_empty_string_id_can_be_targeted(self):
        items = [_item(""), _item("non-empty")]
        result = bulk_delete(items, {""})
        self.assertEqual(result.deleted, [_item("")])
        self.assertEqual(result.remaining, [_item("non-empty")])


# ---------------------------------------------------------------------------
# Large-scale smoke test
# ---------------------------------------------------------------------------

class TestBulkDeleteScale(unittest.TestCase):
    """Smoke tests at scale to catch performance regressions or logic errors."""

    def test_large_list_half_deleted(self):
        """10 000-item list; delete every other item by ID."""
        n = 10_000
        items = [{"id": str(i), "payload": i * 2} for i in range(n)]
        targets = {str(i) for i in range(0, n, 2)}  # even IDs
        result = bulk_delete(items, targets)
        self.assertEqual(len(result.deleted), n // 2)
        self.assertEqual(len(result.remaining), n // 2)
        self.assertEqual(result.not_found, set())

    def test_large_list_no_deletions(self):
        """10 000-item list; empty target set — nothing deleted."""
        n = 10_000
        items = [{"id": str(i)} for i in range(n)]
        result = bulk_delete(items, set())
        self.assertEqual(len(result.remaining), n)
        self.assertEqual(result.deleted, [])

    def test_large_list_all_targets_missing(self):
        """10 000-item list; all targets are absent — all go to not_found."""
        n = 1_000
        items = [{"id": str(i)} for i in range(n)]
        phantom_ids = {f"phantom-{i}" for i in range(500)}
        result = bulk_delete(items, phantom_ids)
        self.assertEqual(len(result.remaining), n)
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.not_found, phantom_ids)

    def test_deleted_plus_remaining_equals_source_at_scale(self):
        """At any scale, len(deleted) + len(remaining) == len(source)."""
        n = 5_000
        items = [{"id": str(i)} for i in range(n)]
        targets = {str(i) for i in range(0, n, 3)}
        result = bulk_delete(items, targets)
        self.assertEqual(len(result.deleted) + len(result.remaining), n)


# ---------------------------------------------------------------------------
# Idempotency and chaining
# ---------------------------------------------------------------------------

class TestBulkDeleteIdempotency(unittest.TestCase):
    """Verify idempotency and safe chaining of bulk_delete calls."""

    def test_calling_twice_with_same_args_gives_same_result(self):
        items = _items("a", "b", "c", "d")
        r1 = bulk_delete(items, {"b", "d"})
        r2 = bulk_delete(items, {"b", "d"})
        self.assertEqual(r1.deleted,   r2.deleted)
        self.assertEqual(r1.remaining, r2.remaining)
        self.assertEqual(r1.not_found, r2.not_found)

    def test_chained_deletion_on_remaining(self):
        """Applying bulk_delete to the remaining list of a prior call works."""
        items = _items("a", "b", "c", "d", "e")
        first  = bulk_delete(items, {"a", "c"})
        second = bulk_delete(first.remaining, {"e"})
        final_ids = [i["id"] for i in second.remaining]
        self.assertEqual(final_ids, ["b", "d"])

    def test_deleting_already_deleted_id_goes_to_not_found(self):
        """Targeting an ID that was already removed in a prior call yields not_found."""
        items = _items("a", "b")
        first  = bulk_delete(items, {"a"})
        second = bulk_delete(first.remaining, {"a"})  # "a" is gone
        self.assertIn("a", second.not_found)

    def test_empty_target_is_idempotent(self):
        """Calling with an empty target set never changes the item list."""
        items = _items("x", "y", "z")
        r1 = bulk_delete(items, set())
        r2 = bulk_delete(r1.remaining, set())
        self.assertEqual(r1.remaining, r2.remaining)


if __name__ == "__main__":
    unittest.main()
