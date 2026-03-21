"""
add.py
======
Module for adding two numbers.

Provides functionality to add two numeric values and return their sum.
"""


def add(a: int | float, b: int | float) -> int | float:
    """
    Add two numbers and return their sum.
    
    Args:
        a: The first number (integer or float).
        b: The second number (integer or float).
        
    Returns:
        The sum of a and b.
    """
    return a + b


if __name__ == '__main__':
    result = add(5, 3)
    print(f"5 + 3 = {result}")
