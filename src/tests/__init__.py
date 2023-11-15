import os
import shutil
import sys
import unittest

import requests


def can_connect_to_url(url, timeout=0.1):
    """Checks if there is network connection to given `url`

    Can be used to skip networked tests, like in example below

        >>> @unittest.skipUnless(
        ...     can_connect_to_url('https://api.github.com', timeout=0.1),
        ...     'Skipping because of no access to https://api.github.com in 0.1 seconds'
        ... )

    :param str url: Endpoint URL to try to connect to
    :param float timeout: Timeout in seconds, optional
    :return: Whether one can connect to `url`
    :rtype: bool
    """
    try:
        # result intentionally ignored, used for side effects (thrown errors)
        requests.head(url, timeout=timeout)
    except requests.exceptions.ConnectionError:
        print(f"Connection error for {url}", file=sys.stderr)
        return False
    except requests.exceptions.ReadTimeout:
        print(f"Read timed out (timeout={timeout}) for {url}")
        return False

    return True


def rm_tree(dir_path):
    """Recursively delete directory tree

    Ignores permission errors on MS Windows because of its peculiarities
    (open file will block and prevent deleting containing directory).

    :param dir_path: directory to be deleted
    :type dir_path: str or PathLike[str] or Path
    :rtype: None
    """
    try:
        if dir_path and os.path.exists(dir_path):
            shutil.rmtree(dir_path)
    except PermissionError:
        if sys.platform == 'win32':
            # on MS Windows, another program accessing a file inside
            # the `dir_path` directory may prevent removing it
            pass
        else:
            raise


# https://stackoverflow.com/questions/1068246/python-unittest-how-to-run-only-part-of-a-test-file/54673427#54673427
def slow_test(func):
    """Decorator to mark tests as slow

    To skip slow tests run:
        $ SKIP_SLOW_TESTS=1 python -m unittest
    """
    return unittest.skipIf('SKIP_SLOW_TESTS' in os.environ, 'Skipping slow test')(func)
