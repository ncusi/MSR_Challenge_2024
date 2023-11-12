"""Common code related to DevGPT sharings for scripts in src/data/ directory"""
import sys
from os import PathLike
from pathlib import Path
from typing import NamedTuple


class SharingsPaths(NamedTuple):
    """Lists of different DevGPT sharings files"""
    commit_sharings_path: list[PathLike]
    issue_sharings_path: list[PathLike]
    pr_sharings_paths: list[PathLike]


def find_sharings_files(dataset_path):
    """Finds all files with issue, commit, and pr sharings in DevGPT dataset

    :param Path dataset_path: path to directory with DevGPT dataset
    :return: tuple of lists of file paths with sharings
    :rtype: SharingsPaths
    """
    snapshot_paths = []
    for path in list(dataset_path.iterdir()):
        if 'snapshot' in str(path) and path.is_dir():
            snapshot_paths.append(path)
    commit_sharings_paths = []
    issue_sharings_paths = []
    pr_sharings_paths = []
    for snapshot_path in snapshot_paths:
        snapshot_content_paths = list(snapshot_path.iterdir())
        for snapshot_content_path in snapshot_content_paths:
            if 'issue_sharings.json' in str(snapshot_content_path):
                issue_sharings_paths.append(snapshot_content_path)
            if 'commit_sharings.json' in str(snapshot_content_path):
                commit_sharings_paths.append(snapshot_content_path)
            if 'pr_sharings.json' in str(snapshot_content_path):
                pr_sharings_paths.append(snapshot_content_path)

    return SharingsPaths(commit_sharings_paths, issue_sharings_paths, pr_sharings_paths)


def find_most_recent_sharings_files(dataset_path, verbose=True):
    """Find all sharings from most recent snapshot in DevGPT dataset

    :param Path dataset_path: path to directory with DevGPT dataset
    :param bool verbose: whether to print debugging-like information,
        `true` by default
    :return: mapping from sharings type to sharings file, for example
        {'commit': Path('20231012_230826_commit_sharings.json')}
    :rtype: dict[str, PathLike]
    """
    snapshot_paths = list(dataset_path.glob('snapshot_*'))
    latest_snapshot_path = sorted(snapshot_paths, reverse=True)[0]
    if verbose:
        print(f"Latest snapshot is '{latest_snapshot_path}'", file=sys.stderr)

    sharings_files = {}
    for sharings_file_path in latest_snapshot_path.glob('*_sharings.json'):
        # file name pattern: <YMD>_<HMS>_<type>_sharings.json
        # for example '20231012_230826_commit_sharings.json'
        sharings_type = str(sharings_file_path).split('_')[-2]
        sharings_files[sharings_type] = sharings_file_path

    link_sharings_path = latest_snapshot_path.joinpath('ChatGPT_Link_Sharing.csv')
    if link_sharings_path.exists():
        sharings_files['link'] = link_sharings_path

    if verbose:
        print(f"Found sharings for {sorted(sharings_files.keys())}", file=sys.stderr)

    return sharings_files
