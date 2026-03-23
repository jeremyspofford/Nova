"""
test_bulk_delete.py
===================
Unit tests for :mod:`bulk_delete`.

Covers:
- Basic deletion: single item, multiple items, all items deleted
- BulkDeleteResult fields: deleted, remaining, not_found
- not_found tracking: IDs requested but absent from items list
- Custom id_key: using a field other than the default "id"
- Empty inputs: empty items list, empty target_ids set
- Items missing the id_key field: treated as non-matching, kept in remaining
- Immutability: original items list is never mutated
- Duplicate IDs in items: all matching items are deleted
- Mixed-type id values: only exact matches are deleted
- Large inputs: correctness at scale
- TypeError: items not a list, target_ids not a set
- TypeError: id_key not a string
- ValueError: id_key is an empty string
"""

import unittest

from bulk_delete import BulkDeleteResult, bulk_delete


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(id_val: str, **extra) -> dict:
    """Return a dict with an 'id' field plus any extra keyword fields."""
    return {"id": id_val, **extra}


def _make_items(*id_vals: str) -> list[dict]:
    """Return a list of minimal dicts with sequential 'value' fields."""
    return [{"id": v, "value": i} for i, v in enumerate(id_vals)]


# ---------------------------------------------------------------------------
# Basic deletion
# ---------------------------------------------------------------------------

class TestBulkDeleteBasic(unittest.TestCase):

    def test_delete_single_item(self):
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, {"a"})
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.deleted[0]["id"], "a")

    def test_remaining_excludes_deleted_item(self):
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, {"a"})
        remaining_ids = [r["id"] for r in result.remaining]
        self.assertNotIn("a", remaining_ids)
        self.assertIn("b", remaining_ids)
        self.assertIn("c", remaining_ids)

    def test_delete_multiple_items(self):
        items = _make_items("x", "y", "z")
        result = bulk_delete(items, {"x", "z"})
        deleted_ids = {d["id"] for d in result.deleted}
        self.assertEqual(deleted_ids, {"x", "z"})
        self.assertEqual(len(result.remaining), 1)
        self.assertEqual(result.remaining[0]["id"], "y")

    def test_delete_all_items(self):
        items = _make_items("a", "b")
        result = bulk_delete(items, {"a", "b"})
        self.assertEqual(len(result.deleted), 2)
        self.assertEqual(result.remaining, [])

    def test_delete_none_when_no_match(self):
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, {"z"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), 3)

    def test_result_is_bulk_delete_result_instance(self):
        result = bulk_delete([], set())
        self.assertIsInstance(result, BulkDeleteResult)

    def test_deleted_items_are_original_dict_objects(self):
        """Deleted items should be the exact same dict objects, not copies."""
        item = {"id": "a", "value": 99}
        result = bulk_delete([item], {"a"})
        self.assertIs(result.deleted[0], item)

    def test_remaining_items_are_original_dict_objects(self):
        """Remaining items should be the exact same dict objects, not copies."""
        item = {"id": "b", "value": 42}
        result = bulk_delete([item], {"a"})
        self.assertIs(result.remaining[0], item)

    def test_order_of_deleted_preserved(self):
        items = [
            {"id": "c", "seq": 0},
            {"id": "a", "seq": 1},
            {"id": "b", "seq": 2},
        ]
        result = bulk_delete(items, {"c", "a", "b"})
        seqs = [d["seq"] for d in result.deleted]
        self.assertEqual(seqs, [0, 1, 2])

    def test_order_of_remaining_preserved(self):
        items = [
            {"id": "a", "seq": 0},
            {"id": "b", "seq": 1},
            {"id": "c", "seq": 2},
            {"id": "d", "seq": 3},
        ]
        result = bulk_delete(items, {"b"})
        seqs = [r["seq"] for r in result.remaining]
        self.assertEqual(seqs, [0, 2, 3])


# ---------------------------------------------------------------------------
# not_found tracking
# ---------------------------------------------------------------------------

class TestBulkDeleteNotFound(unittest.TestCase):

    def test_not_found_empty_when_all_targets_matched(self):
        items = _make_items("a", "b")
        result = bulk_delete(items, {"a", "b"})
        self.assertEqual(result.not_found, set())

    def test_not_found_contains_unmatched_ids(self):
        items = _make_items("a", "b")
        result = bulk_delete(items, {"a", "ghost"})
        self.assertEqual(result.not_found, {"ghost"})

    def test_not_found_all_when_no_items_match(self):
        items = _make_items("a", "b")
        result = bulk_delete(items, {"x", "y", "z"})
        self.assertEqual(result.not_found, {"x", "y", "z"})

    def test_not_found_empty_when_target_ids_empty(self):
        items = _make_items("a", "b")
        result = bulk_delete(items, set())
        self.assertEqual(result.not_found, set())

    def test_not_found_all_targets_when_items_empty(self):
        result = bulk_delete([], {"a", "b"})
        self.assertEqual(result.not_found, {"a", "b"})

    def test_not_found_is_a_set(self):
        result = bulk_delete([], {"missing"})
        self.assertIsInstance(result.not_found, set)

    def test_not_found_multiple_missing(self):
        items = [{"id": "only"}]
        result = bulk_delete(items, {"only", "gone1", "gone2", "gone3"})
        self.assertEqual(result.not_found, {"gone1", "gone2", "gone3"})


# ---------------------------------------------------------------------------
# Custom id_key
# ---------------------------------------------------------------------------

class TestBulkDeleteCustomIdKey(unittest.TestCase):

    def _make_keyed_items(self, key: str, *vals) -> list[dict]:
        return [{key: v, "extra": i} for i, v in enumerate(vals)]

    def test_custom_id_key_basic(self):
        items = [
            {"name": "alice", "score": 10},
            {"name": "bob", "score": 20},
            {"name": "carol", "score": 30},
        ]
        result = bulk_delete(items, {"alice", "carol"}, id_key="name")
        deleted_names = {d["name"] for d in result.deleted}
        self.assertEqual(deleted_names, {"alice", "carol"})
        self.assertEqual(len(result.remaining), 1)
        self.assertEqual(result.remaining[0]["name"], "bob")

    def test_custom_id_key_not_found(self):
        items = [{"uid": "u1"}, {"uid": "u2"}]
        result = bulk_delete(items, {"u1", "u99"}, id_key="uid")
        self.assertEqual(result.not_found, {"u99"})

    def test_custom_id_key_all_remaining_when_no_match(self):
        items = [{"code": "A"}, {"code": "B"}]
        result = bulk_delete(items, {"Z"}, id_key="code")
        self.assertEqual(len(result.remaining), 2)
        self.assertEqual(result.deleted, [])

    def test_default_id_key_is_id(self):
        """Calling without id_key should use 'id' by default."""
        items = [{"id": "default-key-test"}]
        result = bulk_delete(items, {"default-key-test"})
        self.assertEqual(len(result.deleted), 1)


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------

class TestBulkDeleteEmptyInputs(unittest.TestCase):

    def test_empty_items_empty_targets(self):
        result = bulk_delete([], set())
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.remaining, [])
        self.assertEqual(result.not_found, set())

    def test_empty_items_with_targets(self):
        result = bulk_delete([], {"a", "b"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.remaining, [])
        self.assertEqual(result.not_found, {"a", "b"})

    def test_non_empty_items_empty_targets(self):
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, set())
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), 3)
        self.assertEqual(result.not_found, set())

    def test_empty_targets_remaining_equals_input(self):
        items = _make_items("x", "y")
        result = bulk_delete(items, set())
        self.assertEqual(result.remaining, items)


# ---------------------------------------------------------------------------
# Items missing the id_key field
# ---------------------------------------------------------------------------

class TestBulkDeleteMissingIdKey(unittest.TestCase):

    def test_item_without_id_key_kept_in_remaining(self):
        items = [
            {"id": "a", "value": 1},
            {"no_id_here": True},          # missing "id"
            {"id": "b", "value": 3},
        ]
        result = bulk_delete(items, {"a"})
        remaining_items = result.remaining
        # The item without "id" must survive
        self.assertTrue(
            any("no_id_here" in r for r in remaining_items),
            "Item missing id_key should be kept in remaining"
        )

    def test_item_without_id_key_not_deleted(self):
        items = [{"no_id": "x"}, {"no_id": "y"}]
        result = bulk_delete(items, {"x", "y"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), 2)

    def test_item_without_custom_id_key_kept(self):
        items = [
            {"uid": "u1"},
            {"other_field": "no uid here"},
        ]
        result = bulk_delete(items, {"u1"}, id_key="uid")
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(len(result.remaining), 1)
        self.assertIn("other_field", result.remaining[0])

    def test_all_items_missing_id_key(self):
        items = [{"x": 1}, {"x": 2}, {"x": 3}]
        result = bulk_delete(items, {"1", "2", "3"})
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), 3)
        self.assertEqual(result.not_found, {"1", "2", "3"})


# ---------------------------------------------------------------------------
# Duplicate IDs in items (multiple items share the same id value)
# ---------------------------------------------------------------------------

class TestBulkDeleteDuplicateIds(unittest.TestCase):

    def test_all_items_with_duplicate_id_are_deleted(self):
        items = [
            {"id": "dup", "seq": 0},
            {"id": "dup", "seq": 1},
            {"id": "keep", "seq": 2},
        ]
        result = bulk_delete(items, {"dup"})
        deleted_seqs = [d["seq"] for d in result.deleted]
        self.assertIn(0, deleted_seqs)
        self.assertIn(1, deleted_seqs)
        self.assertEqual(len(result.deleted), 2)

    def test_remaining_unaffected_by_duplicate_deletion(self):
        items = [
            {"id": "dup", "seq": 0},
            {"id": "dup", "seq": 1},
            {"id": "keep", "seq": 2},
        ]
        result = bulk_delete(items, {"dup"})
        self.assertEqual(len(result.remaining), 1)
        self.assertEqual(result.remaining[0]["id"], "keep")

    def test_not_found_empty_when_duplicate_id_matched(self):
        items = [{"id": "dup"}, {"id": "dup"}]
        result = bulk_delete(items, {"dup"})
        self.assertEqual(result.not_found, set())

    def test_all_items_same_id_all_deleted(self):
        items = [{"id": "same"} for _ in range(5)]
        result = bulk_delete(items, {"same"})
        self.assertEqual(len(result.deleted), 5)
        self.assertEqual(result.remaining, [])


# ---------------------------------------------------------------------------
# Immutability: original list must not be mutated
# ---------------------------------------------------------------------------

class TestBulkDeleteImmutability(unittest.TestCase):

    def test_original_items_list_not_mutated(self):
        items = _make_items("a", "b", "c")
        original_length = len(items)
        original_ids = [i["id"] for i in items]
        bulk_delete(items, {"a", "b"})
        self.assertEqual(len(items), original_length)
        self.assertEqual([i["id"] for i in items], original_ids)

    def test_original_items_list_not_mutated_empty_targets(self):
        items = _make_items("x", "y")
        snapshot = list(items)
        bulk_delete(items, set())
        self.assertEqual(items, snapshot)

    def test_original_items_list_not_mutated_no_match(self):
        items = _make_items("a", "b")
        snapshot = list(items)
        bulk_delete(items, {"z"})
        self.assertEqual(items, snapshot)

    def test_original_target_ids_not_mutated(self):
        items = _make_items("a", "b")
        targets = {"a", "b"}
        targets_snapshot = set(targets)
        bulk_delete(items, targets)
        self.assertEqual(targets, targets_snapshot)

    def test_result_deleted_and_remaining_are_independent_lists(self):
        """Modifying result lists must not affect each other or the source."""
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, {"a"})
        result.deleted.clear()
        result.remaining.clear()
        # Original items list must still be intact
        self.assertEqual(len(items), 3)


# ---------------------------------------------------------------------------
# Mixed-type id values
# ---------------------------------------------------------------------------

class TestBulkDeleteMixedTypes(unittest.TestCase):

    def test_integer_id_value_not_matched_by_string_target(self):
        """Integer id 1 should NOT match string target '1'."""
        items = [{"id": 1, "label": "int-id"}]
        result = bulk_delete(items, {"1"})
        # "1" (str) != 1 (int), so item should remain
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), 1)

    def test_string_id_matched_correctly(self):
        items = [{"id": "1", "label": "str-id"}]
        result = bulk_delete(items, {"1"})
        self.assertEqual(len(result.deleted), 1)

    def test_none_id_value_not_matched(self):
        """An item whose id value is None should never be deleted."""
        items = [{"id": None, "label": "null-id"}, {"id": "real"}]
        result = bulk_delete(items, {"real"})
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.deleted[0]["id"], "real")
        self.assertEqual(len(result.remaining), 1)
        self.assertIsNone(result.remaining[0]["id"])

    def test_items_with_various_value_types_in_other_fields(self):
        """Non-id fields of any type should not affect deletion logic."""
        items = [
            {"id": "a", "data": [1, 2, 3]},
            {"id": "b", "data": {"nested": True}},
            {"id": "c", "data": None},
        ]
        result = bulk_delete(items, {"b"})
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.deleted[0]["id"], "b")
        self.assertEqual(len(result.remaining), 2)


# ---------------------------------------------------------------------------
# Large inputs
# ---------------------------------------------------------------------------

class TestBulkDeleteLargeInputs(unittest.TestCase):

    def _make_large_items(self, n: int) -> list[dict]:
        return [{"id": f"item-{i}", "value": i} for i in range(n)]

    def test_large_list_delete_half(self):
        n = 1000
        items = self._make_large_items(n)
        targets = {f"item-{i}" for i in range(0, n, 2)}  # even indices
        result = bulk_delete(items, targets)
        self.assertEqual(len(result.deleted), n // 2)
        self.assertEqual(len(result.remaining), n // 2)
        self.assertEqual(result.not_found, set())

    def test_large_list_delete_none(self):
        n = 500
        items = self._make_large_items(n)
        result = bulk_delete(items, set())
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.remaining), n)

    def test_large_list_delete_all(self):
        n = 500
        items = self._make_large_items(n)
        targets = {f"item-{i}" for i in range(n)}
        result = bulk_delete(items, targets)
        self.assertEqual(len(result.deleted), n)
        self.assertEqual(result.remaining, [])
        self.assertEqual(result.not_found, set())

    def test_large_list_not_found_accuracy(self):
        n = 200
        items = self._make_large_items(n)
        # Request items 0–149 (all exist) + 200–249 (none exist)
        targets = {f"item-{i}" for i in range(250)}
        result = bulk_delete(items, targets)
        self.assertEqual(len(result.deleted), n)
        expected_not_found = {f"item-{i}" for i in range(n, 250)}
        self.assertEqual(result.not_found, expected_not_found)


# ---------------------------------------------------------------------------
# TypeError and ValueError
# ---------------------------------------------------------------------------

class TestBulkDeleteTypeErrors(unittest.TestCase):

    def test_raises_type_error_when_items_is_not_a_list(self):
        for bad in (None, "string", 42, ("a",), {"a": 1}):
            with self.subTest(items=bad):
                with self.assertRaises(TypeError):
                    bulk_delete(bad, set())

    def test_raises_type_error_when_target_ids_is_not_a_set(self):
        items = _make_items("a")
        for bad in (None, "string", 42, ["a"], ("a",)):
            with self.subTest(target_ids=bad):
                with self.assertRaises(TypeError):
                    bulk_delete(items, bad)

    def test_raises_type_error_when_id_key_is_not_a_string(self):
        items = _make_items("a")
        for bad in (None, 123, ["id"], ("id",)):
            with self.subTest(id_key=bad):
                with self.assertRaises(TypeError):
                    bulk_delete(items, set(), id_key=bad)

    def test_raises_value_error_when_id_key_is_empty_string(self):
        items = _make_items("a")
        with self.assertRaises(ValueError):
            bulk_delete(items, set(), id_key="")

    def test_type_error_message_mentions_items(self):
        try:
            bulk_delete("not-a-list", set())
        except TypeError as exc:
            self.assertIn("items", str(exc))

    def test_type_error_message_mentions_target_ids(self):
        try:
            bulk_delete([], ["not-a-set"])
        except TypeError as exc:
            self.assertIn("target_ids", str(exc))

    def test_type_error_message_mentions_id_key(self):
        try:
            bulk_delete([], set(), id_key=99)
        except TypeError as exc:
            self.assertIn("id_key", str(exc))

    def test_value_error_message_mentions_id_key(self):
        try:
            bulk_delete([], set(), id_key="")
        except ValueError as exc:
            self.assertIn("id_key", str(exc))

    def test_dict_items_raises_type_error(self):
        """A dict (not a list) passed as items must raise TypeError."""
        with self.assertRaises(TypeError):
            bulk_delete({"id": "a"}, {"a"})

    def test_tuple_target_ids_raises_type_error(self):
        """A tuple (not a set) passed as target_ids must raise TypeError."""
        with self.assertRaises(TypeError):
            bulk_delete([], ("a", "b"))


# ---------------------------------------------------------------------------
# BulkDeleteResult dataclass
# ---------------------------------------------------------------------------

class TestBulkDeleteResult(unittest.TestCase):

    def test_result_has_deleted_field(self):
        result = bulk_delete([], set())
        self.assertTrue(hasattr(result, "deleted"))

    def test_result_has_remaining_field(self):
        result = bulk_delete([], set())
        self.assertTrue(hasattr(result, "remaining"))

    def test_result_has_not_found_field(self):
        result = bulk_delete([], set())
        self.assertTrue(hasattr(result, "not_found"))

    def test_deleted_is_a_list(self):
        result = bulk_delete(_make_items("a"), {"a"})
        self.assertIsInstance(result.deleted, list)

    def test_remaining_is_a_list(self):
        result = bulk_delete(_make_items("a"), set())
        self.assertIsInstance(result.remaining, list)

    def test_not_found_is_a_set(self):
        result = bulk_delete([], {"missing"})
        self.assertIsInstance(result.not_found, set)

    def test_deleted_plus_remaining_equals_total_items(self):
        items = _make_items("a", "b", "c", "d", "e")
        result = bulk_delete(items, {"b", "d"})
        self.assertEqual(
            len(result.deleted) + len(result.remaining),
            len(items),
        )

    def test_deleted_and_remaining_are_disjoint(self):
        items = _make_items("a", "b", "c")
        result = bulk_delete(items, {"a", "c"})
        deleted_ids = {d["id"] for d in result.deleted}
        remaining_ids = {r["id"] for r in result.remaining}
        self.assertTrue(
            deleted_ids.isdisjoint(remaining_ids),
            "deleted and remaining must share no ids"
        )


if __name__ == "__main__":
    unittest.main()
