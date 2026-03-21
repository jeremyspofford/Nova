"""
test_primes.py
==============
Integration and unit tests for :mod:`primes`.

Verifies that the prime number generation and printing functions work correctly.
"""

import io
import unittest
from unittest.mock import patch

from primes import is_prime, get_first_n_primes, print_first_n_primes


class TestIsPrime(unittest.TestCase):
    """Tests for the is_prime() function."""

    def test_is_prime_returns_false_for_zero(self):
        """is_prime(0) must return False."""
        self.assertFalse(is_prime(0))

    def test_is_prime_returns_false_for_one(self):
        """is_prime(1) must return False."""
        self.assertFalse(is_prime(1))

    def test_is_prime_returns_true_for_two(self):
        """is_prime(2) must return True (smallest prime)."""
        self.assertTrue(is_prime(2))

    def test_is_prime_returns_true_for_three(self):
        """is_prime(3) must return True."""
        self.assertTrue(is_prime(3))

    def test_is_prime_returns_false_for_four(self):
        """is_prime(4) must return False (composite)."""
        self.assertFalse(is_prime(4))

    def test_is_prime_returns_true_for_five(self):
        """is_prime(5) must return True."""
        self.assertTrue(is_prime(5))

    def test_is_prime_returns_true_for_seven(self):
        """is_prime(7) must return True."""
        self.assertTrue(is_prime(7))

    def test_is_prime_returns_true_for_eleven(self):
        """is_prime(11) must return True."""
        self.assertTrue(is_prime(11))

    def test_is_prime_returns_false_for_composite(self):
        """is_prime(15) must return False (composite)."""
        self.assertFalse(is_prime(15))


class TestGetFirstNPrimes(unittest.TestCase):
    """Tests for the get_first_n_primes() function."""

    def test_get_first_n_primes_returns_empty_list_for_zero(self):
        """get_first_n_primes(0) must return an empty list."""
        result = get_first_n_primes(0)
        self.assertEqual(result, [])

    def test_get_first_n_primes_returns_first_prime(self):
        """get_first_n_primes(1) must return [2]."""
        result = get_first_n_primes(1)
        self.assertEqual(result, [2])

    def test_get_first_n_primes_returns_first_five_primes(self):
        """get_first_n_primes(5) must return [2, 3, 5, 7, 11]."""
        result = get_first_n_primes(5)
        self.assertEqual(result, [2, 3, 5, 7, 11],
                         f"Expected [2, 3, 5, 7, 11], got {result}")

    def test_get_first_n_primes_returns_correct_count(self):
        """get_first_n_primes(n) must return exactly n primes."""
        for n in [1, 3, 5, 10]:
            result = get_first_n_primes(n)
            self.assertEqual(len(result), n,
                             f"Expected {n} primes, got {len(result)}")

    def test_get_first_n_primes_returns_list_of_integers(self):
        """get_first_n_primes() must return a list of integers."""
        result = get_first_n_primes(5)
        self.assertIsInstance(result, list)
        for prime in result:
            self.assertIsInstance(prime, int)


class TestPrintFirstNPrimes(unittest.TestCase):
    """Tests for the print_first_n_primes() function."""

    def test_print_first_n_primes_outputs_five_primes(self):
        """print_first_n_primes(5) must print the first 5 primes, one per line."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            print_first_n_primes(5)
            output = mock_stdout.getvalue()
        expected_output = "2\n3\n5\n7\n11\n"
        self.assertEqual(output, expected_output,
                         f"Expected:\n{expected_output!r}\nGot:\n{output!r}")

    def test_print_first_n_primes_outputs_one_per_line(self):
        """print_first_n_primes() must output one prime per line."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            print_first_n_primes(5)
            output = mock_stdout.getvalue()
        lines = output.strip().split('\n')
        self.assertEqual(len(lines), 5,
                         f"Expected 5 lines, got {len(lines)}")

    def test_print_first_n_primes_outputs_correct_values(self):
        """print_first_n_primes(5) must output 2, 3, 5, 7, 11."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            print_first_n_primes(5)
            output = mock_stdout.getvalue()
        lines = output.strip().split('\n')
        primes = [int(line) for line in lines]
        self.assertEqual(primes, [2, 3, 5, 7, 11],
                         f"Expected [2, 3, 5, 7, 11], got {primes}")


if __name__ == '__main__':
    unittest.main()
