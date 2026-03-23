"""
test_validation_helpers.py
==========================
Unit tests for :mod:`validation_helpers`.

Covers:
- validate_type: single types, tuple of types, all built-in types
- validate_not_empty: strings, lists, dicts, sets, whitespace-only strings
- validate_range: integers, floats, boundary conditions, negative ranges
- Error message format: consistent pattern with context
- Edge cases: empty ranges, zero values, negative numbers
"""

import unittest

from validation_helpers import (
    validate_type,
    validate_not_empty,
    validate_range,
)


# ---------------------------------------------------------------------------
# validate_type tests
# ---------------------------------------------------------------------------

class TestValidateTypeSingleType(unittest.TestCase):
    """Tests for validate_type() with single type."""

    def test_validate_type_int_accepts_int(self):
        """validate_type(5, int, 'value') must not raise."""
        validate_type(5, int, 'value')  # Should not raise

    def test_validate_type_str_accepts_str(self):
        """validate_type('hello', str, 'name') must not raise."""
        validate_type('hello', str, 'name')  # Should not raise

    def test_validate_type_list_accepts_list(self):
        """validate_type([1, 2], list, 'items') must not raise."""
        validate_type([1, 2], list, 'items')  # Should not raise

    def test_validate_type_dict_accepts_dict(self):
        """validate_type({}, dict, 'config') must not raise."""
        validate_type({}, dict, 'config')  # Should not raise

    def test_validate_type_set_accepts_set(self):
        """validate_type({1, 2}, set, 'ids') must not raise."""
        validate_type({1, 2}, set, 'ids')  # Should not raise

    def test_validate_type_float_accepts_float(self):
        """validate_type(3.14, float, 'pi') must not raise."""
        validate_type(3.14, float, 'pi')  # Should not raise

    def test_validate_type_bool_accepts_bool(self):
        """validate_type(True, bool, 'flag') must not raise."""
        validate_type(True, bool, 'flag')  # Should not raise

    def test_validate_type_int_rejects_str(self):
        """validate_type('5', int, 'count') must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            validate_type('5', int, 'count')
        self.assertIn("'count'", str(cm.exception))
        self.assertIn("int", str(cm.exception))
        self.assertIn("'str'", str(cm.exception))

    def test_validate_type_str_rejects_int(self):
        """validate_type(5, str, 'name') must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            validate_type(5, str, 'name')
        self.assertIn("'name'", str(cm.exception))
        self.assertIn("str", str(cm.exception))
        self.assertIn("'int'", str(cm.exception))

    def test_validate_type_list_rejects_dict(self):
        """validate_type({}, list, 'items') must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            validate_type({}, list, 'items')
        self.assertIn("'items'", str(cm.exception))
        self.assertIn("list", str(cm.exception))
        self.assertIn("'dict'", str(cm.exception))

    def test_validate_type_error_message_format(self):
        """Error message must include param name, expected type, and actual type."""
        with self.assertRaises(TypeError) as cm:
            validate_type(42, str, 'my_param')
        error_msg = str(cm.exception)
        self.assertIn("'my_param'", error_msg)
        self.assertIn("str", error_msg)
        self.assertIn("'int'", error_msg)


class TestValidateTypeTupleOfTypes(unittest.TestCase):
    """Tests for validate_type() with tuple of types."""

    def test_validate_type_tuple_accepts_first_type(self):
        """validate_type(5, (int, str), 'value') must not raise."""
        validate_type(5, (int, str), 'value')  # Should not raise

    def test_validate_type_tuple_accepts_second_type(self):
        """validate_type('hello', (int, str), 'value') must not raise."""
        validate_type('hello', (int, str), 'value')  # Should not raise

    def test_validate_type_tuple_accepts_third_type(self):
        """validate_type(3.14, (int, str, float), 'value') must not raise."""
        validate_type(3.14, (int, str, float), 'value')  # Should not raise

    def test_validate_type_tuple_rejects_non_matching_type(self):
        """validate_type([], (int, str), 'value') must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            validate_type([], (int, str), 'value')
        error_msg = str(cm.exception)
        self.assertIn("'value'", error_msg)
        self.assertIn("(int, str)", error_msg)
        self.assertIn("'list'", error_msg)

    def test_validate_type_tuple_error_message_includes_all_types(self):
        """Error message must show all acceptable types."""
        with self.assertRaises(TypeError) as cm:
            validate_type({}, (int, str, float), 'param')
        error_msg = str(cm.exception)
        self.assertIn("(int, str, float)", error_msg)


# ---------------------------------------------------------------------------
# validate_not_empty tests
# ---------------------------------------------------------------------------

class TestValidateNotEmptyStrings(unittest.TestCase):
    """Tests for validate_not_empty() with strings."""

    def test_validate_not_empty_accepts_non_empty_string(self):
        """validate_not_empty('hello', 'name') must not raise."""
        validate_not_empty('hello', 'name')  # Should not raise

    def test_validate_not_empty_accepts_single_char_string(self):
        """validate_not_empty('a', 'char') must not raise."""
        validate_not_empty('a', 'char')  # Should not raise

    def test_validate_not_empty_rejects_empty_string(self):
        """validate_not_empty('', 'name') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty('', 'name')
        error_msg = str(cm.exception)
        self.assertIn("'name'", error_msg)
        self.assertIn("empty", error_msg)

    def test_validate_not_empty_rejects_whitespace_only_string(self):
        """validate_not_empty('   ', 'name') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty('   ', 'name')
        error_msg = str(cm.exception)
        self.assertIn("'name'", error_msg)
        self.assertIn("empty", error_msg)
        self.assertIn("whitespace", error_msg)

    def test_validate_not_empty_rejects_tab_only_string(self):
        """validate_not_empty('\\t\\t', 'name') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty('\t\t', 'name')
        error_msg = str(cm.exception)
        self.assertIn("whitespace", error_msg)

    def test_validate_not_empty_rejects_newline_only_string(self):
        """validate_not_empty('\\n', 'name') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty('\n', 'name')
        error_msg = str(cm.exception)
        self.assertIn("whitespace", error_msg)

    def test_validate_not_empty_accepts_string_with_leading_space(self):
        """validate_not_empty(' hello', 'name') must not raise."""
        validate_not_empty(' hello', 'name')  # Should not raise

    def test_validate_not_empty_accepts_string_with_trailing_space(self):
        """validate_not_empty('hello ', 'name') must not raise."""
        validate_not_empty('hello ', 'name')  # Should not raise


class TestValidateNotEmptyCollections(unittest.TestCase):
    """Tests for validate_not_empty() with collections."""

    def test_validate_not_empty_accepts_non_empty_list(self):
        """validate_not_empty([1, 2, 3], 'items') must not raise."""
        validate_not_empty([1, 2, 3], 'items')  # Should not raise

    def test_validate_not_empty_accepts_single_item_list(self):
        """validate_not_empty([1], 'items') must not raise."""
        validate_not_empty([1], 'items')  # Should not raise

    def test_validate_not_empty_rejects_empty_list(self):
        """validate_not_empty([], 'items') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty([], 'items')
        error_msg = str(cm.exception)
        self.assertIn("'items'", error_msg)
        self.assertIn("empty", error_msg)

    def test_validate_not_empty_accepts_non_empty_dict(self):
        """validate_not_empty({'key': 'value'}, 'config') must not raise."""
        validate_not_empty({'key': 'value'}, 'config')  # Should not raise

    def test_validate_not_empty_rejects_empty_dict(self):
        """validate_not_empty({}, 'config') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty({}, 'config')
        error_msg = str(cm.exception)
        self.assertIn("'config'", error_msg)
        self.assertIn("empty", error_msg)

    def test_validate_not_empty_accepts_non_empty_set(self):
        """validate_not_empty({1, 2}, 'ids') must not raise."""
        validate_not_empty({1, 2}, 'ids')  # Should not raise

    def test_validate_not_empty_rejects_empty_set(self):
        """validate_not_empty(set(), 'ids') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty(set(), 'ids')
        error_msg = str(cm.exception)
        self.assertIn("'ids'", error_msg)
        self.assertIn("empty", error_msg)


# ---------------------------------------------------------------------------
# validate_range tests
# ---------------------------------------------------------------------------

class TestValidateRangeIntegers(unittest.TestCase):
    """Tests for validate_range() with integers."""

    def test_validate_range_accepts_value_in_range(self):
        """validate_range(50, 0, 100, 'percentage') must not raise."""
        validate_range(50, 0, 100, 'percentage')  # Should not raise

    def test_validate_range_accepts_min_boundary(self):
        """validate_range(0, 0, 100, 'percentage') must not raise."""
        validate_range(0, 0, 100, 'percentage')  # Should not raise

    def test_validate_range_accepts_max_boundary(self):
        """validate_range(100, 0, 100, 'percentage') must not raise."""
        validate_range(100, 0, 100, 'percentage')  # Should not raise

    def test_validate_range_rejects_value_below_min(self):
        """validate_range(-1, 0, 100, 'percentage') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(-1, 0, 100, 'percentage')
        error_msg = str(cm.exception)
        self.assertIn("'percentage'", error_msg)
        self.assertIn("[0, 100]", error_msg)
        self.assertIn("-1", error_msg)

    def test_validate_range_rejects_value_above_max(self):
        """validate_range(150, 0, 100, 'percentage') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(150, 0, 100, 'percentage')
        error_msg = str(cm.exception)
        self.assertIn("'percentage'", error_msg)
        self.assertIn("[0, 100]", error_msg)
        self.assertIn("150", error_msg)

    def test_validate_range_accepts_negative_range(self):
        """validate_range(-50, -100, 0, 'offset') must not raise."""
        validate_range(-50, -100, 0, 'offset')  # Should not raise

    def test_validate_range_rejects_negative_value_below_min(self):
        """validate_range(-150, -100, 0, 'offset') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(-150, -100, 0, 'offset')
        error_msg = str(cm.exception)
        self.assertIn("[-100, 0]", error_msg)
        self.assertIn("-150", error_msg)


class TestValidateRangeFloats(unittest.TestCase):
    """Tests for validate_range() with floats."""

    def test_validate_range_accepts_float_in_range(self):
        """validate_range(3.14, 0.0, 10.0, 'pi') must not raise."""
        validate_range(3.14, 0.0, 10.0, 'pi')  # Should not raise

    def test_validate_range_accepts_float_at_min_boundary(self):
        """validate_range(0.0, 0.0, 10.0, 'value') must not raise."""
        validate_range(0.0, 0.0, 10.0, 'value')  # Should not raise

    def test_validate_range_accepts_float_at_max_boundary(self):
        """validate_range(10.0, 0.0, 10.0, 'value') must not raise."""
        validate_range(10.0, 0.0, 10.0, 'value')  # Should not raise

    def test_validate_range_rejects_float_below_min(self):
        """validate_range(-0.1, 0.0, 10.0, 'value') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(-0.1, 0.0, 10.0, 'value')
        error_msg = str(cm.exception)
        self.assertIn("[0.0, 10.0]", error_msg)
        self.assertIn("-0.1", error_msg)

    def test_validate_range_rejects_float_above_max(self):
        """validate_range(10.1, 0.0, 10.0, 'value') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(10.1, 0.0, 10.0, 'value')
        error_msg = str(cm.exception)
        self.assertIn("[0.0, 10.0]", error_msg)
        self.assertIn("10.1", error_msg)

    def test_validate_range_mixed_int_and_float(self):
        """validate_range(5, 0.0, 10.0, 'value') must not raise."""
        validate_range(5, 0.0, 10.0, 'value')  # Should not raise

    def test_validate_range_mixed_float_and_int(self):
        """validate_range(3.14, 0, 10, 'value') must not raise."""
        validate_range(3.14, 0, 10, 'value')  # Should not raise


class TestValidateRangeEdgeCases(unittest.TestCase):
    """Tests for validate_range() edge cases."""

    def test_validate_range_single_value_range(self):
        """validate_range(5, 5, 5, 'value') must not raise."""
        validate_range(5, 5, 5, 'value')  # Should not raise

    def test_validate_range_single_value_range_rejects_different_value(self):
        """validate_range(4, 5, 5, 'value') must raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            validate_range(4, 5, 5, 'value')
        error_msg = str(cm.exception)
        self.assertIn("[5, 5]", error_msg)

    def test_validate_range_zero_value_in_range(self):
        """validate_range(0, -10, 10, 'value') must not raise."""
        validate_range(0, -10, 10, 'value')  # Should not raise

    def test_validate_range_large_numbers(self):
        """validate_range(1000000, 0, 10000000, 'value') must not raise."""
        validate_range(1000000, 0, 10000000, 'value')  # Should not raise

    def test_validate_range_very_small_floats(self):
        """validate_range(0.00001, 0.0, 1.0, 'value') must not raise."""
        validate_range(0.00001, 0.0, 1.0, 'value')  # Should not raise


# ---------------------------------------------------------------------------
# Error message format consistency
# ---------------------------------------------------------------------------

class TestErrorMessageFormat(unittest.TestCase):
    """Tests for consistent error message formatting."""

    def test_validate_type_error_uses_param_name(self):
        """Error messages must include the parameter name."""
        with self.assertRaises(TypeError) as cm:
            validate_type(5, str, 'my_custom_param')
        self.assertIn("'my_custom_param'", str(cm.exception))

    def test_validate_not_empty_error_uses_param_name(self):
        """Error messages must include the parameter name."""
        with self.assertRaises(ValueError) as cm:
            validate_not_empty('', 'my_custom_param')
        self.assertIn("'my_custom_param'", str(cm.exception))

    def test_validate_range_error_uses_param_name(self):
        """Error messages must include the parameter name."""
        with self.assertRaises(ValueError) as cm:
            validate_range(150, 0, 100, 'my_custom_param')
        self.assertIn("'my_custom_param'", str(cm.exception))

    def test_validate_type_error_includes_actual_type(self):
        """Error messages must show the actual type received."""
        with self.assertRaises(TypeError) as cm:
            validate_type([1, 2, 3], str, 'param')
        self.assertIn("'list'", str(cm.exception))

    def test_validate_range_error_includes_actual_value(self):
        """Error messages must show the actual value received."""
        with self.assertRaises(ValueError) as cm:
            validate_range(999, 0, 100, 'param')
        self.assertIn("999", str(cm.exception))


if __name__ == '__main__':
    unittest.main()
