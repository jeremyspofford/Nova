"""
test_add.py
===========
Integration and unit tests for :mod:`add`.

Verifies that the add() function correctly adds two numbers and handles
invalid inputs with appropriate error messages.

Covers:
- Basic addition: positive integers, negative integers, floats
- Type mixing: int + float combinations
- Return types: int when both inputs are int, float otherwise
- Type validation: TypeError for non-numeric inputs
- Error message format: consistent pattern with context
"""

import unittest

from add import add


class TestAdd(unittest.TestCase):
    """Tests for the add() function."""

    def test_add_two_positive_integers(self):
        """add(5, 3) must return 8."""
        result = add(5, 3)
        self.assertEqual(result, 8,
                         f"Expected 8, got {result}")

    def test_add_two_negative_integers(self):
        """add(-5, -3) must return -8."""
        result = add(-5, -3)
        self.assertEqual(result, -8,
                         f"Expected -8, got {result}")

    def test_add_positive_and_negative_integers(self):
        """add(10, -4) must return 6."""
        result = add(10, -4)
        self.assertEqual(result, 6,
                         f"Expected 6, got {result}")

    def test_add_zero_and_positive_integer(self):
        """add(0, 5) must return 5."""
        result = add(0, 5)
        self.assertEqual(result, 5,
                         f"Expected 5, got {result}")

    def test_add_two_zeros(self):
        """add(0, 0) must return 0."""
        result = add(0, 0)
        self.assertEqual(result, 0,
                         f"Expected 0, got {result}")

    def test_add_two_positive_floats(self):
        """add(2.5, 3.7) must return 6.2."""
        result = add(2.5, 3.7)
        self.assertAlmostEqual(result, 6.2, places=5,
                               msg=f"Expected 6.2, got {result}")

    def test_add_integer_and_float(self):
        """add(5, 2.5) must return 7.5."""
        result = add(5, 2.5)
        self.assertAlmostEqual(result, 7.5, places=5,
                               msg=f"Expected 7.5, got {result}")

    def test_add_returns_correct_type_for_integers(self):
        """add(5, 3) must return an integer."""
        result = add(5, 3)
        self.assertIsInstance(result, int,
                              f"Expected int, got {type(result)}")

    def test_add_returns_correct_type_for_floats(self):
        """add(2.5, 3.5) must return a float."""
        result = add(2.5, 3.5)
        self.assertIsInstance(result, float,
                              f"Expected float, got {type(result)}")

    def test_add_returns_float_when_mixing_types(self):
        """add(5, 2.5) must return a float."""
        result = add(5, 2.5)
        self.assertIsInstance(result, float,
                              f"Expected float, got {type(result)}")


# ---------------------------------------------------------------------------
# Type validation tests
# ---------------------------------------------------------------------------

class TestAddTypeErrors(unittest.TestCase):
    """Tests for type validation in add() function."""

    def test_add_rejects_string_as_first_argument(self):
        """add('5', 3) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add('5', 3)
        error_msg = str(cm.exception)
        self.assertIn("'a'", error_msg)
        self.assertIn("(int, float)", error_msg)
        self.assertIn("'str'", error_msg)

    def test_add_rejects_string_as_second_argument(self):
        """add(5, '3') must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add(5, '3')
        error_msg = str(cm.exception)
        self.assertIn("'b'", error_msg)
        self.assertIn("(int, float)", error_msg)
        self.assertIn("'str'", error_msg)

    def test_add_rejects_list_as_first_argument(self):
        """add([5], 3) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add([5], 3)
        error_msg = str(cm.exception)
        self.assertIn("'a'", error_msg)
        self.assertIn("'list'", error_msg)

    def test_add_rejects_list_as_second_argument(self):
        """add(5, [3]) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add(5, [3])
        error_msg = str(cm.exception)
        self.assertIn("'b'", error_msg)
        self.assertIn("'list'", error_msg)

    def test_add_rejects_dict_as_first_argument(self):
        """add({}, 3) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add({}, 3)
        error_msg = str(cm.exception)
        self.assertIn("'a'", error_msg)
        self.assertIn("'dict'", error_msg)

    def test_add_rejects_dict_as_second_argument(self):
        """add(5, {}) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add(5, {})
        error_msg = str(cm.exception)
        self.assertIn("'b'", error_msg)
        self.assertIn("'dict'", error_msg)

    def test_add_rejects_none_as_first_argument(self):
        """add(None, 3) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add(None, 3)
        error_msg = str(cm.exception)
        self.assertIn("'a'", error_msg)
        self.assertIn("'NoneType'", error_msg)

    def test_add_rejects_none_as_second_argument(self):
        """add(5, None) must raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            add(5, None)
        error_msg = str(cm.exception)
        self.assertIn("'b'", error_msg)
        self.assertIn("'NoneType'", error_msg)

    def test_add_rejects_bool_as_first_argument(self):
        """add(True, 3) must raise TypeError (bool is not accepted)."""
        with self.assertRaises(TypeError) as cm:
            add(True, 3)
        error_msg = str(cm.exception)
        self.assertIn("'a'", error_msg)

    def test_add_rejects_bool_as_second_argument(self):
        """add(5, False) must raise TypeError (bool is not accepted)."""
        with self.assertRaises(TypeError) as cm:
            add(5, False)
        error_msg = str(cm.exception)
        self.assertIn("'b'", error_msg)

    def test_add_error_message_format_first_argument(self):
        """Error message for first argument must include param name and types."""
        with self.assertRaises(TypeError) as cm:
            add("not_a_number", 5)
        error_msg = str(cm.exception)
        # Must include parameter name
        self.assertIn("'a'", error_msg)
        # Must include expected types
        self.assertIn("(int, float)", error_msg)
        # Must include actual type
        self.assertIn("'str'", error_msg)

    def test_add_error_message_format_second_argument(self):
        """Error message for second argument must include param name and types."""
        with self.assertRaises(TypeError) as cm:
            add(5, "not_a_number")
        error_msg = str(cm.exception)
        # Must include parameter name
        self.assertIn("'b'", error_msg)
        # Must include expected types
        self.assertIn("(int, float)", error_msg)
        # Must include actual type
        self.assertIn("'str'", error_msg)


if __name__ == '__main__':
    unittest.main()
