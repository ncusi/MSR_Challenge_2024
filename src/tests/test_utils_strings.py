import unittest

from src.utils.strings import strip_suffixes


class StringsTestCase(unittest.TestCase):
    """Test `utils.strings` module"""
    def test_strip_suffixes(self):
        """Test examples from `utils.strings.strip_suffixes` docstring"""
        actual = strip_suffixes("chairs", "s")
        expected = 'chair'
        self.assertEqual(expected, actual, "with single suffix to strip")

        actual = strip_suffixes("https://github.com/abrt/abrt.git/", ["/", ".git"] )
        expected = 'https://github.com/abrt/abrt'
        self.assertEqual(expected, actual, "with list of suffixes to strip")


if __name__ == '__main__':
    unittest.main()
