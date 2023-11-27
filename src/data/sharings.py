"""Common code related to DevGPT sharings for scripts in src/data/ directory"""
import json
import sys
from os import PathLike
from pathlib import Path
from typing import NamedTuple

from src.data.common import ERROR_OTHER


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


def find_most_recent_commit_sharings(dataset_directory_path, verbose=True):
    """Find commit sharings from most recent snapshot in DevGPT dataset

    :param Path dataset_directory_path: path to directory with DevGPT dataset
    :param bool verbose: whether to print debugging-like information,
        `true` by default
    :return: path to most recent commits sharings file
    :rtype: Path
    """
    return find_most_recent_sharings_files(dataset_directory_path, verbose)['commit']


def find_most_recent_pr_sharings(dataset_directory_path, verbose=True):
    """Find pr sharings from most recent snapshot in DevGPT dataset

    :param Path dataset_directory_path: path to directory with DevGPT dataset
    :param bool verbose: whether to print debugging-like information,
        `true` by default
    :return: path to most recent pr sharings file
    :rtype: Path
    """
    return find_most_recent_sharings_files(dataset_directory_path, verbose)['pr']


def sharings_repo_list(sharings_path):
    """List all different 'RepoName' that can be found in DevGPT sharings

    :param PathLike sharings_path: path to sharings file from DevGPT dataset,
        for example 'data/DevGPT/snapshot_20230831/20230831_063412_commit_sharings.json'
    :return: list of unique repositories ('RepoName'), for example
        ['sqlalchemy/sqlalchemy',...]
    :rtype: list[str]
    """
    with open(sharings_path) as sharings_file:
        sharings = json.load(sharings_file)

    if 'Sources' not in sharings:
        print(f"ERROR: unexpected format/structure of '{sharings_path}'")
        sys.exit(ERROR_OTHER)

    sharings_data = sharings['Sources']
    return list(set([source['RepoName']
                    for source in sharings_data]))


def recent_sharings_paths_and_repos(dataset_path, verbose=True):
    """Find repos mentioned in sharings from most recent DevGPT snapshot

    This function considers only commit, pr, and issue sharings.
    The result is mapping from sharings type to data about most recent
    sharing of that type (sharing of that type from most recent snapshot
    from DevGPT dataset).

    The data about sharings consist of the following fields:

    - 'path': path to sharings file,
    - 'repos': list of unique 'RepoName's in sharings file.

    :param Path dataset_path: path to directory with DevGPT dataset
    :param bool verbose: whether to print debugging-like information,
        `true` by default
    :return: data about most recent sharings of selected types
    :rtype: dict
    """
    recent_sharings = find_most_recent_sharings_files(dataset_path, verbose)

    result = {}
    for sharings_type, sharings_path in recent_sharings.items():
        if sharings_type in {'commit', 'pr', 'issue'}:
            sharings_repos = sharings_repo_list(sharings_path)
            result[sharings_type] = {
                'path': sharings_path,
                'repos': sharings_repos,
            }

    return result
