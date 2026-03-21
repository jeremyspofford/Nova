"""
primes.py
=========
Module for generating and displaying prime numbers.

Provides functionality to identify and print the first N prime numbers.
"""


def is_prime(n: int) -> bool:
    """
    Check if a number is prime.
    
    Args:
        n: The integer to check for primality.
        
    Returns:
        True if n is prime, False otherwise.
    """
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
    
    Args:
        n: The count of prime numbers to retrieve.
        
    Returns:
        A list containing the first n prime numbers.
    """
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
    
    Args:
        n: The count of prime numbers to print.
    """
    primes = get_first_n_primes(n)
    for prime in primes:
        print(prime)


if __name__ == '__main__':
    print_first_n_primes(5)
