"""
validation_helpers.py
=====================
Reusable validation helper functions for the Nova workspace.

Provides three core validation functions that enforce type safety and value
constraints with consistent, informative error messages. These helpers are
designed to be used at function entry points to fail fast with clear context.

Pattern
-------
All validation functions follow the error message pattern:
    '{param_name} must be {expected}, got {actual}'

This pattern provides clear context for debugging and is consistent across
the Nova codebase (see bulk_delete.py for reference implementation).

Usage
-----
    from validation_helpers import validate_type, validate_not_empty, validate_range

    def process_items(items: list, count: int) -> None:
        validate_type(items, list, 'items')
        validate_not_empty(items, 'items')
        validate_type(count, int, 'count')
        validate_range(count, 0, 100, 'count')
        # ... rest of function

Examples
--------
    >>> validate_type(5, int, 'value')  # OK
    >>> validate_type("5", int, 'value')  # Raises TypeError
    Traceback (most recent call last):
        ...
    TypeError: 'value' must be int, got 'str'

    >>> validate_not_empty([1, 2, 3], 'items')  # OK
    >>> validate_not_empty([], 'items')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'items' must not be empty

    >>> validate_range(50, 0, 100, 'percentage')  # OK
    >>> validate_range(150, 0, 100, 'percentage')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'percentage' must be in range [0, 100], got 150
"""

from __future__ import annotations

from typing import Any


def validate_type(
    value: Any,
    expected_type: type | tuple[type, ...],
    param_name: str,
) -> None:
    """Validate that a value is of the expected type.

    Raises TypeError immediately if the value is not an instance of the
    expected type. Designed to be called at function entry points to fail
    fast with clear context.

    Special handling: bool values are rejected even when (int, float) is
    expected, since bool is a subclass of int in Python. This ensures
    strict type checking and prevents accidental boolean-as-integer bugs.

    Parameters
    ----------
    value:
        The value to validate.
    expected_type:
        The expected type or tuple of acceptable types. Can be a single
        type (e.g., ``int``) or a tuple of types (e.g., ``(int, float)``).
    param_name:
        The name of the parameter being validated. Used in error messages
        for clarity (e.g., ``'items'``, ``'count'``).

    Raises
    ------
    TypeError
        If *value* is not an instance of *expected_type*. The error message
        follows the pattern: ``'{param_name}' must be {expected}, got {actual}``

    Examples
    --------
    >>> validate_type(5, int, 'count')  # OK
    >>> validate_type("hello", str, 'name')  # OK
    >>> validate_type(3.14, (int, float), 'value')  # OK
    >>> validate_type("5", int, 'count')  # Raises TypeError
    Traceback (most recent call last):
        ...
    TypeError: 'count' must be int, got 'str'

    >>> validate_type([], (int, str), 'item')  # Raises TypeError
    Traceback (most recent call last):
        ...
    TypeError: 'item' must be (int, str), got 'list'

    >>> validate_type(True, (int, float), 'value')  # Raises TypeError
    Traceback (most recent call last):
        ...
    TypeError: 'value' must be (int, float), got 'bool'
    """
    # Special handling: reject bool even though it's a subclass of int
    # This prevents accidental bool-as-int bugs and ensures strict type checking
    if isinstance(value, bool):
        if isinstance(expected_type, tuple):
            type_names = ", ".join(t.__name__ for t in expected_type)
            expected_str = f"({type_names})"
        else:
            expected_str = expected_type.__name__
        raise TypeError(
            f"'{param_name}' must be {expected_str}, got 'bool'"
        )

    if not isinstance(value, expected_type):
        # Format expected type(s) for error message
        if isinstance(expected_type, tuple):
            # Format tuple of types as "(type1, type2, ...)"
            type_names = ", ".join(t.__name__ for t in expected_type)
            expected_str = f"({type_names})"
        else:
            expected_str = expected_type.__name__

        actual_type = type(value).__name__
        raise TypeError(
            f"'{param_name}' must be {expected_str}, got {actual_type!r}"
        )


def validate_not_empty(
    value: str | list | dict | set,
    param_name: str,
) -> None:
    """Validate that a string or collection is not empty.

    Raises ValueError if the value is an empty string, empty list, empty
    dict, or empty set. For strings, also checks that the value is not
    whitespace-only.

    Parameters
    ----------
    value:
        The string or collection to validate. Must be one of: str, list,
        dict, or set.
    param_name:
        The name of the parameter being validated. Used in error messages
        for clarity (e.g., ``'items'``, ``'name'``).

    Raises
    ------
    ValueError
        If *value* is empty or (for strings) contains only whitespace.
        The error message follows the pattern:
        ``'{param_name}' must not be empty``

    Examples
    --------
    >>> validate_not_empty([1, 2, 3], 'items')  # OK
    >>> validate_not_empty("hello", 'name')  # OK
    >>> validate_not_empty({"key": "value"}, 'config')  # OK
    >>> validate_not_empty([], 'items')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'items' must not be empty

    >>> validate_not_empty("   ", 'name')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'name' must not be empty (whitespace-only string)
    """
    # Check for empty collections
    if not value:
        # For strings, provide additional context about whitespace-only strings
        if isinstance(value, str):
            raise ValueError(
                f"'{param_name}' must not be empty (whitespace-only string)"
            )
        else:
            raise ValueError(f"'{param_name}' must not be empty")

    # For strings, also check that it's not whitespace-only
    if isinstance(value, str) and not value.strip():
        raise ValueError(
            f"'{param_name}' must not be empty (whitespace-only string)"
        )


def validate_range(
    value: int | float,
    min_val: int | float,
    max_val: int | float,
    param_name: str,
) -> None:
    """Validate that a numeric value is within a specified range.

    Raises ValueError if the value is less than min_val or greater than
    max_val. The range is inclusive on both ends.

    Parameters
    ----------
    value:
        The numeric value to validate (int or float).
    min_val:
        The minimum acceptable value (inclusive).
    max_val:
        The maximum acceptable value (inclusive).
    param_name:
        The name of the parameter being validated. Used in error messages
        for clarity (e.g., ``'count'``, ``'percentage'``).

    Raises
    ------
    ValueError
        If *value* is less than *min_val* or greater than *max_val*.
        The error message follows the pattern:
        ``'{param_name}' must be in range [{min}, {max}], got {value}``

    Examples
    --------
    >>> validate_range(50, 0, 100, 'percentage')  # OK
    >>> validate_range(0, 0, 100, 'percentage')  # OK
    >>> validate_range(100, 0, 100, 'percentage')  # OK
    >>> validate_range(-1, 0, 100, 'percentage')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'percentage' must be in range [0, 100], got -1

    >>> validate_range(150, 0, 100, 'percentage')  # Raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: 'percentage' must be in range [0, 100], got 150
    """
    if value < min_val or value > max_val:
        raise ValueError(
            f"'{param_name}' must be in range [{min_val}, {max_val}], "
            f"got {value}"
        )
