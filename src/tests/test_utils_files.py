import codecs
import io
import unittest

from src.utils.files import detect_utf16, load_properties_lite


class UtilsFilesTestCase(unittest.TestCase):
    """Tests for functions in the `utils.files` module

    Currently limited to tests that run in-memory using `io.StringIO`
    and `io.BytesIO`.
    """
    def test_detect_utf16(self):
        """In-memory tests for `utils.files.detect_utf16`"""
        example_str = 'Zażółć gęsią jaźń\nπ ∈ ℝ'
        file_utf8 = io.BytesIO(example_str.encode('utf8'))
        file_utf16le = io.BytesIO(example_str.encode('UTF-16LE'))
        file_utf16be = io.BytesIO(example_str.encode('UTF-16BE'))
        file_utf16_bom = io.BytesIO(codecs.BOM_UTF16 + example_str.encode('UTF-16'))

        self.assertTrue(detect_utf16(file_utf16le), "detect UTF-16LE")
        self.assertTrue(detect_utf16(file_utf16be), "detect UTF-16BE")
        self.assertTrue(detect_utf16(file_utf16_bom), "detect UTF-16 with BOM")
        self.assertFalse(detect_utf16(file_utf8), "not detect UTF-8")

    def test_load_properties_lite(self):
        """In-memory tests for `utils.files.load_properties_lite`"""
        expected = {'key': 'value'}
        for text in ('key=value', 'key =value', 'key= value', 'key = value'):
            actual = load_properties_lite(io.StringIO(text))
            self.assertEqual(expected, actual, f"parsing '{text}'")

        expected = {'key': 'value with a single trailing space '}
        text = ' key = "value with a single trailing space "   '
        actual = load_properties_lite(io.StringIO(text), strip_quotes=True)
        self.assertEqual(expected, actual, 'load_properties_lite with strip_quotes=True')


if __name__ == '__main__':
    unittest.main()
