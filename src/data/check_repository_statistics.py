#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <commit_file_path> <repositories_path> <output.json>

Retrieves number of commits and authors from repository

Example:
    python3 src/data/check_repository_statistics.py data/DevGPT/snapshot_20230831/20230831_063412_commit_sharings.json \\
        data/repositories data/repository_statistics.json
"""
import json
import subprocess
import sys
from pathlib import Path

from src.utils.functools import timed

# constants
ERROR_ARGS = 1


def load_sharings(sharings_path):
    with open(sharings_path) as sharings_file:
        sharings = json.load(sharings_file)
    return sharings


def check_repository_statistic(sharings, repositories_path):
    sharings_list = sharings['Sources']
    results = {}
    for sharing in sharings_list:
        repo_name = sharing['RepoName']
        repository_directory_name = repo_name.split('/')[1]
        repository_path = repositories_path / repository_directory_name
        if repo_name not in results:
            commit_number = int(check_commit_number(repository_path))
            author_number = len(check_authors(repository_path))
            results[repo_name] = {'author_number': author_number,
                                  'commit_number': commit_number}
    return results


def check_commit_number(repository_path):
    cmd = [
        'git', '-C', str(repository_path),
        'rev-list', '--count', 'HEAD'
    ]
    process = subprocess.run(cmd, capture_output=True, check=True)
    return process.stdout.decode('utf8')


def check_authors(repository_path):
    cmd = [
        'git', '-C', str(repository_path),
        'shortlog', '-s', '-n', '--all'
    ]
    process = subprocess.run(cmd, capture_output=True, check=True)
    return process.stdout.decode('utf8')


@timed
def main():
    # handle command line parameters
    # {script_name} <commit_file_path> <repositories_path> <output.json>
    if len(sys.argv) != 3 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    commit_file_path = Path(sys.argv[1])
    repositories_path = Path(sys.argv[2])
    output_file_path = Path(sys.argv[3])

    print(f"Reading data about commits from '{commit_file_path}'...", file=sys.stderr)

    commit_sharings = load_sharings(commit_file_path)

    data = check_repository_statistic(commit_sharings, repositories_path)

    print(f"Writing output data to '{output_file_path}'...", file=sys.stderr)
    with open(output_file_path, 'w') as output_file:
        json.dump(data, output_file, indent=2)


if __name__ == '__main__':
    main()
