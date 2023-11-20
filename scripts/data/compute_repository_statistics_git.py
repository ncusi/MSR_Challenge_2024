#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <commit_file_path> <repositories_path> <output.json>

Retrieves number of commits and authors from repository

Example:
    python scripts/data/compute_repository_statistics_git.py \\
        data/DevGPT/snapshot_20230831/20230831_063412_commit_sharings.json \\
        data/repositories data/repository_statistics.json
"""
import json
import sys
from pathlib import Path

from tqdm import tqdm

from src.utils.functools import timed
from src.utils.git import GitRepo

# constants
ERROR_ARGS = 1


def load_sharings(sharings_path):
    with open(sharings_path) as sharings_file:
        sharings = json.load(sharings_file)
    return sharings


def check_repository_statistic(sharings, repositories_path):
    sharings_list = sharings['Sources']
    results = {}
    for sharing in tqdm(sharings_list, desc='sharing'):
        repo_name = sharing['RepoName']
        repository_directory_name = repo_name.split('/')[1]
        repository_path = repositories_path / repository_directory_name
        if repo_name not in results:
            repo = GitRepo(repository_path)

            commit_number = repo.count_commits()
            commit_number_first_parent = repo.count_commits(first_parent=True)
            author_number = len(repo.list_authors_shortlog())
            files_number = len(repo.list_files())
            root_commits = repo.find_roots()
            HEAD_commit_timestamp = repo.get_commit_metadata('HEAD')['committer']['timestamp']
            root_commit_timestamp = min([
                repo.get_commit_metadata(commit)['committer']['timestamp']
                for commit in root_commits
            ])

            results[repo_name] = {
                'author_number': author_number,
                'commit_number': commit_number,
                'commit_number_first_parent': commit_number_first_parent,
                'files_number': files_number,
                'root_commit_number': len(root_commits),
                'HEAD_commit_timestamp': HEAD_commit_timestamp,
                'root_commit_timestamp': root_commit_timestamp,
            }

    return results


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
