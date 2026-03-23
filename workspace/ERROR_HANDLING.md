# Error Handling Patterns & Best Practices

**Date:** 2024  
**Status:** Active  
**Scope:** Nova workspace error handling standards

---

## Executive Summary

This document outlines the error handling patterns adopted across the Nova workspace, based on the proven excellence of `bulk_delete.py`. The patterns ensure consistent, informative error messages that help developers quickly diagnose and fix issues.

**Key Pattern:** `'{param_name}' must be {expected}, got {actual}'`

---

## Part 1: Core Error Handling Principles

### 1. Type Validation at Function Entry

All functions should validate input types **before** processing data. This follows the "fail fast" principle and prevents cryptic errors deep in the call stack.

#### ✓ Good Pattern (bulk_delete.py)
```python
def bulk_delete(
    items: list[dict[str, Any]],
    target_ids: set[str],
    *,
    id_key: str = "id",
) -> BulkDeleteResult:
    """Remove all items whose ``id_key`` value appears in *target_ids*."""
    # Type validation at function entry
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
    # ... rest of function
```

#### ✗ Poor Pattern (Avoid)
```python
def bulk_delete(items, target_ids, id_key="id"):
    """Remove all items..."""
    # No type validation - error occurs deep in processing
    for item in items:  # TypeError: 'str' object is not iterable
        # ...
```

### 2. Consistent Error Message Format

All error messages follow the pattern:
```
'{param_name}' must be {expected}, got {actual}
```

This pattern provides:
- **Parameter name** - which input caused the problem
- **Expected type/value** - what was required
- **Actual type/value** - what was received

#### Examples

```python
# Type error
TypeError: 'items' must be a list, got 'str'

# Value error
ValueError: 'id_key' must be a non-empty string

# Range error
ValueError: 'n' must be in range [0, 100], got 150
```

### 3. Element-Level Validation with Index Reporting

When validating collections, report the index of problematic elements:

```python
# Good: Reports which element failed
for idx, item in enumerate(items):
    if not isinstance(item, dict):
        raise TypeError(
            f"'items[{idx}]' must be a dict, got {type(item).__name__!r}"
        )

# Poor: Generic error without index
for item in items:
    if not isinstance(item, dict):
        raise TypeError("All items must be dicts")
```

### 4. Value Validation (Empty Strings/Collections)

Check for empty values after type validation:

```python
# Good: Clear distinction between empty and whitespace-only
if not id_key:
    raise ValueError("'id_key' must be a non-empty string")
if not id_key.strip():
    raise ValueError("'id_key' must not be a whitespace-only string")

# Good: Clear message for empty collections
if not items:
    raise ValueError("'items' must not be empty")
```

---

## Part 2: Validation Helpers Module

The `validation_helpers.py` module provides three reusable validation functions that implement the patterns above.

### validate_type(value, expected_type, param_name)

Validates that a value is of the expected type.

```python
from validation_helpers import validate_type

def add(a: int | float, b: int | float) -> int | float:
    """Add two numbers."""
    validate_type(a, (int, float), 'a')
    validate_type(b, (int, float), 'b')
    return a + b

# Usage
add(5, 3)           # OK: returns 8
add(5, 2.5)         # OK: returns 7.5
add("5", 3)         # TypeError: 'a' must be (int, float), got 'str'
```

**Features:**
- Accepts single type or tuple of types
- Provides clear error messages with parameter name and actual type
- Designed for function entry point validation

### validate_not_empty(value, param_name)

Validates that a string or collection is not empty.

```python
from validation_helpers import validate_not_empty

def process_items(items: list) -> None:
    """Process a list of items."""
    validate_not_empty(items, 'items')
    # ... process items

# Usage
process_items([1, 2, 3])    # OK
process_items([])           # ValueError: 'items' must not be empty
process_items("")           # ValueError: 'items' must not be empty (whitespace-only string)
process_items("   ")        # ValueError: 'items' must not be empty (whitespace-only string)
```

**Features:**
- Works with strings, lists, dicts, and sets
- Distinguishes between empty and whitespace-only strings
- Clear error messages

### validate_range(value, min_val, max_val, param_name)

Validates that a numeric value is within a specified range.

```python
from validation_helpers import validate_range

def get_first_n_primes(n: int) -> list[int]:
    """Get the first n prime numbers."""
    validate_type(n, int, 'n')
    validate_range(n, 0, 2**31 - 1, 'n')
    # ... generate primes

# Usage
get_first_n_primes(5)       # OK: returns [2, 3, 5, 7, 11]
get_first_n_primes(0)       # OK: returns []
get_first_n_primes(-1)      # ValueError: 'n' must be in range [0, 2147483647], got -1
```

**Features:**
- Inclusive range on both ends
- Works with integers and floats
- Clear error messages showing valid range and actual value

---

## Part 3: Before & After Comparisons

### Example 1: add.py

#### Before (No Validation)
```python
def add(a: int | float, b: int | float) -> int | float:
    """Add two numbers and return their sum."""
    return a + b

# Problem: No type checking
add("5", 3)  # TypeError: unsupported operand type(s) for +: 'str' and 'int'
             # Error is cryptic and doesn't mention parameter names
```

#### After (With Validation)
```python
from validation_helpers import validate_type

def add(a: int | float, b: int | float) -> int | float:
    """Add two numbers and return their sum.
    
    Raises
    ------
    TypeError
        If *a* is not an int or float.
    TypeError
        If *b* is not an int or float.
    """
    validate_type(a, (int, float), 'a')
    validate_type(b, (int, float), 'b')
    return a + b

# Result: Clear error messages
add("5", 3)  # TypeError: 'a' must be (int, float), got 'str'
             # Developer immediately knows: parameter 'a', expected types, actual type
```

### Example 2: primes.py

#### Before (No Validation)
```python
def get_first_n_primes(n: int) -> list[int]:
    """Get the first N prime numbers."""
    primes = []
    candidate = 2
    while len(primes) < n:  # Problem: No validation of n
        if is_prime(candidate):
            primes.append(candidate)
        candidate += 1
    return primes

# Problem: Negative n causes infinite loop
get_first_n_primes(-5)  # Hangs forever - no error message
```

#### After (With Validation)
```python
from validation_helpers import validate_type, validate_range

def get_first_n_primes(n: int) -> list[int]:
    """Get the first N prime numbers.
    
    Raises
    ------
    TypeError
        If *n* is not an int.
    ValueError
        If *n* is negative.
    """
    validate_type(n, int, 'n')
    validate_range(n, 0, 2**31 - 1, 'n')
    
    primes = []
    candidate = 2
    while len(primes) < n:
        if is_prime(candidate):
            primes.append(candidate)
        candidate += 1
    return primes

# Result: Clear error messages
get_first_n_primes(-5)  # ValueError: 'n' must be in range [0, 2147483647], got -5
                        # Developer immediately knows the problem and valid range
```

### Example 3: bulk_delete.py (Reference Implementation)

```python
def bulk_delete(
    items: list[dict[str, Any]],
    target_ids: set[str],
    *,
    id_key: str = "id",
) -> BulkDeleteResult:
    """Remove all items whose ``id_key`` value appears in *target_ids*.
    
    Raises
    ------
    TypeError
        If *items* is not a list, any element of *items* is not a dict,
        *target_ids* is not a set, or *id_key* is not a string.
    ValueError
        If *id_key* is an empty string or a whitespace-only string.
    """
    # Parameter-level type validation
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
    
    # Value validation
    if not id_key:
        raise ValueError("'id_key' must be a non-empty string")
    if not id_key.strip():
        raise ValueError("'id_key' must not be a whitespace-only string")
    
    # Element-level validation with index reporting
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(
                f"'items[{idx}]' must be a dict, got {type(item).__name__!r}"
            )
    
    # ... rest of function
```

---

## Part 4: Docstring Standards

All functions with error handling must document exceptions in the docstring using NumPy style:

```python
def my_function(param1: str, param2: int) -> str:
    """Short description.
    
    Longer description if needed.
    
    Parameters
    ----------
    param1:
        Description of param1.
    param2:
        Description of param2.
    
    Returns
    -------
    str
        Description of return value.
    
    Raises
    ------
    TypeError
        If *param1* is not a string.
    TypeError
        If *param2* is not an int.
    ValueError
        If *param2* is negative.
    
    Examples
    --------
    >>> my_function("hello", 5)
    'hello_5'
    >>> my_function(123, 5)
    Traceback (most recent call last):
        ...
    TypeError: 'param1' must be str, got 'int'
    """
```

**Key Points:**
- Document each exception type separately
- Specify the condition that triggers the exception
- Use parameter names in backticks: `*param_name*`
- Include examples showing both success and error cases

---

## Part 5: Testing Error Handling

### Test Structure

Use `assertRaises()` context manager to test both exception type and message:

```python
import unittest

class TestMyFunctionErrors(unittest.TestCase):
    """Tests for error handling in my_function()."""
    
    def test_rejects_non_string_param1(self):
        """my_function(123, 5) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            my_function(123, 5)
        error_msg = str(cm.exception)
        # Verify error message contains key information
        self.assertIn("'param1'", error_msg)
        self.assertIn("str", error_msg)
        self.assertIn("'int'", error_msg)
    
    def test_rejects_negative_param2(self):
        """my_function('hello', -1) must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            my_function('hello', -1)
        error_msg = str(cm.exception)
        # Verify error message contains key information
        self.assertIn("'param2'", error_msg)
        self.assertIn("range", error_msg)
        self.assertIn("-1", error_msg)
```

### Error Message Verification

Always verify that error messages contain:
1. **Parameter name** - `self.assertIn("'param_name'", error_msg)`
2. **Expected type/value** - `self.assertIn("expected", error_msg)`
3. **Actual type/value** - `self.assertIn("actual", error_msg)`

---

## Part 6: Best Practices & Conventions

### ✓ Do's

1. **Validate at function entry** - Check types before processing
2. **Use consistent error messages** - Follow the `'{param}' must be {expected}, got {actual}'` pattern
3. **Report indices in collections** - Help developers locate problematic elements
4. **Document all exceptions** - Include Raises section in docstrings
5. **Test error paths** - Add test cases for all error conditions
6. **Use validation helpers** - Leverage `validation_helpers.py` for consistency
7. **Fail fast** - Raise exceptions immediately when validation fails

### ✗ Don'ts

1. **Don't validate deep in the call stack** - Check at function entry
2. **Don't use generic error messages** - Always include context (parameter name, types)
3. **Don't ignore type hints** - Validate that inputs match type hints
4. **Don't mix validation and processing** - Separate concerns
5. **Don't forget edge cases** - Test empty strings, negative numbers, None values
6. **Don't skip documentation** - Document all exceptions
7. **Don't catch and suppress errors** - Let them propagate with context

### Pattern Adoption Checklist

- [ ] All function parameters validated at entry
- [ ] Type validation uses `isinstance()` checks
- [ ] Error messages follow `'{param}' must be {expected}, got {actual}'` pattern
- [ ] Element-level validation includes index: `'param[idx]'`
- [ ] Empty string/collection validation checks both empty and whitespace-only
- [ ] All exceptions documented in docstring Raises section
- [ ] 5+ error test cases per function
- [ ] Error messages verified in tests (not just exception type)

---

## Part 7: Migration Guide

### Step 1: Add validation_helpers import
```python
from validation_helpers import validate_type, validate_not_empty, validate_range
```

### Step 2: Add validation at function entry
```python
def my_function(items: list, count: int) -> None:
    # Type validation
    validate_type(items, list, 'items')
    validate_type(count, int, 'count')
    
    # Value validation
    validate_not_empty(items, 'items')
    
    # Range validation
    validate_range(count, 0, 100, 'count')
    
    # ... rest of function
```

### Step 3: Update docstring
```python
def my_function(items: list, count: int) -> None:
    """Do something with items.
    
    Parameters
    ----------
    items:
        A list of items to process.
    count:
        The number of items to process (0-100).
    
    Raises
    ------
    TypeError
        If *items* is not a list.
    TypeError
        If *count* is not an int.
    ValueError
        If *items* is empty.
    ValueError
        If *count* is not in range [0, 100].
    """
```

### Step 4: Add error test cases
```python
class TestMyFunctionErrors(unittest.TestCase):
    def test_rejects_non_list_items(self):
        with self.assertRaises(TypeError) as cm:
            my_function("not_a_list", 5)
        self.assertIn("'items'", str(cm.exception))
    
    # ... more error test cases
```

---

## Summary

The error handling patterns in this document ensure:

✓ **Consistency** - All error messages follow the same pattern  
✓ **Clarity** - Developers know exactly what went wrong  
✓ **Debuggability** - Error messages include parameter names and actual values  
✓ **Reliability** - Validation at function entry prevents cryptic errors  
✓ **Testability** - Error paths are thoroughly tested  

By adopting these patterns across the Nova workspace, we improve response quality, enable better error diagnostics, and establish a foundation for more sophisticated error handling in the future.

---

## References

- **bulk_delete.py** (lines 94-125) - Reference implementation
- **test_bulk_delete.py** - TestBulkDeleteTypeErrors class shows error testing patterns
- **validation_helpers.py** - Reusable validation functions
- **add.py, primes.py** - Refactored modules using validation patterns
