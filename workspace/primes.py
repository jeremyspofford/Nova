"""
primes.py
=========
Module for generating and displaying prime numbers.

Provides functionality to identify and print the first N prime numbers,
with comprehensive input validation and error handling.

This module demonstrates error handling patterns from bulk_delete.py,
with type validation at function entry points and informative error
messages following the pattern: '{param} must be {expected}, got {actual}'

Usage
-----
    from primes import is_prime, get_first_n_primes

    is_prime(7)
    # True

    get_first_n_primes(5)
    # [2, 3, 5, 7, 11]
"""

from __future__ import annotations

from validation_helpers import validate_type, validate_range


def is_prime(n: int) -> bool:
    """
    Check if a number is prime.

    Performs type validation at function entry to ensure the parameter
    is an integer. Raises TypeError if n is not an int.

    Parameters
    ----------
    n:
        The integer to check for primality.

    Returns
    -------
    bool
        True if n is prime, False otherwise. By definition, numbers less
        than 2 are not prime.

    Raises
    ------
    TypeError
        If *n* is not an int.

    Examples
    --------
    >>> is_prime(2)
    True
    >>> is_prime(3)
    True
    >>> is_prime(4)
    False
    >>> is_prime(7)
    True
    >>> is_prime(15)
    False
    """
    # Type validation at function entry
    validate_type(n, int, 'n')

    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n**0.5) + 1, 2):
        if n % i == 0:
            return False
    return True


def get_first_n_primes(n: int) -> list[int]:
    """
    Get the first N prime numbers.

    Performs type and range validation at function entry to ensure n is
    a non-negative integer. Raises TypeError if n is not an int, or
    ValueError if n is negative.

    Parameters
    ----------
    n:
        The count of prime numbers to retrieve. Must be non-negative.

    Returns
    -------
    list[int]
        A list containing the first n prime numbers. Returns an empty list
        if n is 0.

    Raises
    ------
    TypeError
        If *n* is not an int.
    ValueError
        If *n* is negative.

    Examples
    --------
    >>> get_first_n_primes(0)
    []
    >>> get_first_n_primes(1)
    [2]
    >>> get_first_n_primes(5)
    [2, 3, 5, 7, 11]
    >>> get_first_n_primes(10)
    [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
    """
    # Type validation at function entry
    validate_type(n, int, 'n')

    # Range validation: n must be >= 0
    validate_range(n, 0, 2**31 - 1, 'n')

    primes = []
    candidate = 2
    while len(primes) < n:
        if is_prime(candidate):
            primes.append(candidate)
        candidate += 1
    return primes


def print_first_n_primes(n: int) -> None:
    """
    Print the first N prime numbers, one per line.

    Performs type and range validation at function entry to ensure n is
    a non-negative integer. Raises TypeError if n is not an int, or
    ValueError if n is negative.

    Parameters
    ----------
    n:
        The count of prime numbers to print. Must be non-negative.

    Raises
    ------
    TypeError
        If *n* is not an int.
    ValueError
        If *n* is negative.

    Examples
    --------
    >>> print_first_n_primes(5)
    2
    3
    5
    7
    11
    """
    # Type validation at function entry
    validate_type(n, int, 'n')

    # Range validation: n must be >= 0
    validate_range(n, 0, 2**31 - 1, 'n')

    primes = get_first_n_primes(n)
    for prime in primes:
        print(prime)


if __name__ == '__main__':
    print_first_n_primes(5)
