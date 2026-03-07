"""
test_hello.py
=============
Integration test for :mod:`hello`.

Verifies that the hello() function prints the expected greeting to stdout.
"""

import io
import unittest
from unittest.mock import patch

from hello import hello


class TestHello(unittest.TestCase):

    def test_hello_prints_hello_world(self):
        """hello() must print 'Hello, World!' to stdout."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            hello()
            output = mock_stdout.getvalue()
        self.assertIn('Hello', output,
                      f"Expected 'Hello' in output, got: {output!r}")
        self.assertEqual(output.strip(), 'Hello, World!',
                         f"Expected 'Hello, World!', got: {output.strip()!r}")

    def test_hello_output_ends_with_newline(self):
        """print() must append a trailing newline."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            hello()
            output = mock_stdout.getvalue()
        self.assertTrue(output.endswith('\n'),
                        "Output should end with a newline character")


if __name__ == '__main__':
    unittest.main()
