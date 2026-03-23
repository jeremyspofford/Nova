"""
add.py
======
Module for adding two numbers.

Provides functionality to add two numeric values and return their sum,
with comprehensive input validation and error handling.

This module demonstrates error handling patterns from bulk_delete.py,
with type validation at function entry points and informative error
messages following the pattern: '{param} must be {expected}, got {actual}'

Usage
-----
    from add import add

    result = add(5, 3)
    # result -> 8

    result = add(2.5, 3.7)
    # result -> 6.2
"""

from __future__ import annotations

from validation_helpers import validate_type


def add(a: int | float, b: int | float) -> int | float:
    """
    Add two numbers and return their sum.

    Performs type validation at function entry to ensure both parameters
    are numeric (int or float). Raises TypeError if either parameter is
    not a number.

    Parameters
    ----------
    a:
        The first number (integer or float).
    b:
        The second number (integer or float).

    Returns
    -------
    int | float
        The sum of a and b. Returns int if both inputs are int, otherwise
        returns float.

    Raises
    ------
    TypeError
        If *a* is not an int or float.
    TypeError
        If *b* is not an int or float.

    Examples
    --------
    >>> add(5, 3)
    8
    >>> add(2.5, 3.7)
    6.2
    >>> add(5, 2.5)
    7.5
    >>> add(-5, 3)
    -2
    """
    # Type validation at function entry
    validate_type(a, (int, float), 'a')
    validate_type(b, (int, float), 'b')

    return a + b


if __name__ == '__main__':
    result = add(5, 3)
    print(f"5 + 3 = {result}")
