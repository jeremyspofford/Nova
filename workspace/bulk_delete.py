"""
bulk_delete.py
==============
Bulk-deletion utility for the Nova workspace.

Provides :func:`bulk_delete`, which removes all items in a given list
whose keys appear in a set of target IDs, and returns a
:class:`BulkDeleteResult` summarising what was deleted and what survived.

This module uses the Python standard library only — no third-party
dependencies are required.

Encoding pipeline (for context)
--------------------------------
This module is intentionally framework-free and operates purely on plain
Python dicts, making it easy to slot into any storage or serialisation
layer.

Usage
-----
    from bulk_delete import bulk_delete

    items = [
        {"id": "a", "value": 1},
        {"id": "b", "value": 2},
        {"id": "c", "value": 3},
    ]
    result = bulk_delete(items, {"a", "c"})
    # result.deleted   -> [{"id": "a", "value": 1}, {"id": "c", "value": 3}]
    # result.remaining -> [{"id": "b", "value": 2}]
    # result.not_found -> set()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BulkDeleteResult:
    """Outcome of a :func:`bulk_delete` operation.

    Attributes
    ----------
    deleted:
        Items that were removed (their key matched a target ID).
    remaining:
        Items that were kept (their key did not match any target ID).
    not_found:
        Target IDs that were requested but not present in the input list.
    """

    deleted: list[dict[str, Any]] = field(default_factory=list)
    remaining: list[dict[str, Any]] = field(default_factory=list)
    not_found: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def bulk_delete(
    items: list[dict[str, Any]],
    target_ids: set[str],
    *,
    id_key: str = "id",
) -> BulkDeleteResult:
    """Remove all items whose ``id_key`` value appears in *target_ids*.

    When the source list contains duplicate IDs, all occurrences of those
    IDs are deleted. This is the standard behavior for bulk delete operations
    and matches the expectations of most users.

    Parameters
    ----------
    items:
        A list of dicts, each expected to contain the field named by
        *id_key*.  Items that lack the key are treated as non-matching
        and are kept in ``remaining``.  Every element of *items* must be
        a dict; passing non-dict elements raises ``TypeError``.
    target_ids:
        A set of string IDs to delete.  An empty set is valid and
        results in no deletions.
    id_key:
        The dict key used to identify each item (default: ``"id"``).
        Must be a non-empty, non-whitespace-only string.

    Returns
    -------
    BulkDeleteResult
        A dataclass with three fields:

        * ``deleted``   - items that were removed.
        * ``remaining`` - items that were kept.
        * ``not_found`` - IDs in *target_ids* that matched no item.

    Raises
    ------
    TypeError
        If *items* is not a list, any element of *items* is not a dict,
        *target_ids* is not a set, or *id_key* is not a string.
    ValueError
        If *id_key* is an empty string or a whitespace-only string.

    Examples
    --------
    >>> items = [{"id": "x", "v": 1}, {"id": "y", "v": 2}]
    >>> result = bulk_delete(items, {"x"})
    >>> result.deleted
    [{'id': 'x', 'v': 1}]
    >>> result.remaining
    [{'id': 'y', 'v': 2}]
    >>> result.not_found
    set()

    >>> items = [{"id": "a"}, {"id": "a"}, {"id": "b"}]
    >>> result = bulk_delete(items, {"a"})
    >>> len(result.deleted)
    2
    >>> result.deleted[0]["id"]
    'a'
    >>> result.deleted[1]["id"]
    'a'
    """
    if not isinstance(items, list):
        raise TypeError(f"'items' must be a list, got {type(items).__name__!r}")
    if not isinstance(target_ids, set):
        raise TypeError(
            f"'target_ids' must be a set, got {type(target_ids).__name__!r}"
        )
    if not isinstance(id_key, str):
        raise TypeError(
            f"'id_key' must be a str, got {type(id_key).__name__!r}"
        )
    if not id_key:
        raise ValueError("'id_key' must be a non-empty string")
    if not id_key.strip():
        raise ValueError("'id_key' must not be a whitespace-only string")

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(
                f"'items[{idx}]' must be a dict, got {type(item).__name__!r}"
            )

    deleted: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    found_ids: set[str] = set()

    for item in items:
        item_id = item.get(id_key)
        if item_id is not None and item_id in target_ids:
            deleted.append(item)
            found_ids.add(item_id)
        else:
            remaining.append(item)

    not_found = target_ids - found_ids

    return BulkDeleteResult(
        deleted=deleted,
        remaining=remaining,
        not_found=not_found,
    )
