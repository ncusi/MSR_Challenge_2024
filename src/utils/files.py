"""Module with various file-related utilities
"""
import json
import sys
from pathlib import Path
from typing import IO, TextIO, BinaryIO, AnyStr


def make_opened(file_or_path, mode='r'):
    """Make `file_or_path` opened, suitable for file operations

    Examples:
        >>> import io
        >>> with make_opened(io.BytesIO(b'test'), 'rb') as fp:
        ...     print(fp.read(2))
        b'te'

        >>> with make_opened('README.md') as fp:
        ...     lines = fp.readlines()

    :param file_or_path: Path or path to a file, or a file-like object like io.StringIO
    :type file_or_path: pathlib.Path or str or bytes or os.PathLike or IO[AnyStr]
    :param str mode: an optional string that specifies the mode in which the file is opened;
        it defaults to 'r' which means open for reading in text mode.
    :return: opened file-like object
    :rtype: IO[AnyStr]
    """
    try:
        # file_or_path is pathlib.Path like object
        return file_or_path.open(mode)
    except AttributeError:
        # there is no .open() method
        # file_or_path is str, bytes or os.PathLike object
        try:
            return open(file_or_path, mode=mode)
        except TypeError:
            # file_or_path is io.StringIO or io.BytesIO
            # or other object behaving like file opened for reading
            # NOTE: might want to check if file_or_path.closed is true
            # NOTE: no checking that mode matches the object!
            return file_or_path


def detect_utf16(filepath):
    """Try to detect if `filepath` text file is likely to be using UTF-16 encoding

    This is useful if one wants to read text file in UTF-16 encoding as a string;
    this unfortunately happens for some of 'requirements.txt' files for a bug
    embedded in BugsInPy repository.

    It detects BOM at the beginning of the file, and NUL characters in the file,
    which is characteristic of UTF-16 encoded text file in English.

    :param filepath: Path to a file, or opened file
    :type filepath: pathlib.Path or str or bytes or os.PathLike or BinaryIO(IO[bytes])
    :return: Whether `filepath` is likely to be in UTF-16 encoding
    :rtype: bool
    """
    # try to detect Byte Order Mark (BOM), i.e. the character code U+FEFF at the beginning of file,
    # which is used to determine whether encoding is utf-16-le or utf-16-be
    with make_opened(filepath, mode='rb') as f:
        byte_2 = f.read(2)
        if byte_2:
            if byte_2 == b'\xff\xfe' or byte_2 == b'\xfe\xff':
                return True

        # detect if there were any NUL characters ('\0'), which should not happen
        # in a text file in utf-8 encoding, or in one of legacy 8bit encodings like latin1,
        # while with utf-16 if the text is known to be English with the occasional non-ASCII character,
        # like for 'requirements.txt', then for most of the file every other byte will be zero
        f.seek(0)  # rewind to start
        while True:
            byte_1 = f.read(1)
            if not byte_1:
                break
            if byte_1 == b'\x00':
                return True

    # otherwise assume it is not utf-16
    return False


def load_properties_lite(filepath, sep='=', quotes='"', strip_quotes=True):
    """Read data from ini-like / properties-like key=value text file

    Assumes simplified format, with no empty lines, no comments, and only
    key=value format supported.

    Extract data into dict, optionally stripping quotes from values.

    :param filepath: Path to the text file to deserialize (or opened file)
    :type filepath: pathlib.Path or str or bytes or os.PathLike or TextIO(IO[str])
    :param str sep: Delimiter separating variable name from value (used for split)
    :param str quotes: Set of characters to be removed from value (to strip)
    :param bool strip_quotes: Whether to strip 'quotes' from values
    :return: Deserialized data
    :rtype: dict
    """
    props = {}

    with make_opened(filepath, mode='r') as fp:
        for line in fp:
            # split key=value into key and value
            (key, value) = line.strip().split(sep, maxsplit=2)
            # handle spaces around '=' and at the end of line
            key = key.strip()
            value = value.strip()
            # strip quotes from value, if requested
            if strip_quotes:
                value = value.strip(quotes)

            props[key] = value

    return props


def load_json_with_checks(filepath, file_descr, data_descr, err_code, expected_type=list):
    """Load JSON file, checking for errors, and exiting with `err_code` on errors

    Checks if given path is a directory, if a file exists, and if file is a valid
    JSON file (note that JSON Lines / Newline Delimited JSON is not yet supported).
    The values of `file_descr` and `data_descr` are used to describe errors.

    NOTE: by default assumes and checks that to object of the JSON given by `filepath`
    is a **list** (like it is the case for 'data/projects.json' file); use
    `expected_type` parameter to change it to expect dict instead.

    :param Path filepath: JSON file to read
    :param str file_descr: description of JSON file, for example "<projects.json> file"
    :param str data_descr: description of data in JSON file, for example "projects data"
    :param int err_code: what error code to use in `sys.exit()` on error
    :param type expected_type: what type is required for top object in JSON
    :return: data from JSON file
    :rtype: list[dict] or dict
    """
    if filepath.is_dir():
        print(f"ERROR: {file_descr} parameter '{filepath}' is a directory, file expected")
        sys.exit(err_code)

    try:
        print(f"Loading {data_descr} from '{filepath}'...", file=sys.stderr)
        with filepath.open() as fp:
            result = json.load(fp)
    except FileNotFoundError as err:
        print(f"ERROR: {file_descr} parameter '{filepath}' does not exists")
        print(f"...... {err}")
        sys.exit(err_code)
    except json.decoder.JSONDecodeError:
        print(f"ERROR: file '{filepath}' is not a valid JSON file")
        sys.exit(err_code)

    # TODO: make this check configurable
    if type(result) is not expected_type:
        print(f"ERROR: unexpected contents in '{filepath}' JSON file"
              f" - top object is not {expected_type} but {type(result)}")
        sys.exit(err_code)

    return result
