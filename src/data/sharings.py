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
