"""Module with varius string-related utilities
"""


def strip_suffixes(s, suffixes):
    """Strip suffixes from given string, in order

    Example:
        >>> strip_suffixes("chairs", "s")
        'chair'
        >>> strip_suffixes("https://github.com/abrt/abrt.git/", ["/", ".git"] )
        'https://github.com/abrt/abrt'

    Based on https://stackoverflow.com/a/15226443/46058

    :param s: string to process
    :type: str
    :param suffixes: suffix or list of suffixes to strip
    :type: str or list[str]
    :return: string with all suffixes stripped
    :rtype: str
    """
    # handle special case of a single suffix
    if type(suffixes) == str:
        suffixes = [suffixes]

    # process suffixes in order
    for suf in suffixes:
        if s.endswith(suf):
            s = s[:-len(suf)]

    return s
