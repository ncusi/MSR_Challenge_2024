#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <repositories.json> <output_dir>

Extract information about commits from DevGPT's *_commit_sharings.json
in the <dataset_path>, aggregating data about ChatGPT conversations.
Aggregate information about projects (group by project).

Example:
    python scripts/data/commit_sharings_to_agg.py \\
        data/external/DevGPT/ data/repositories_download_status.json \\
        data/interim/
"""
import json
import sys
from os import PathLike
from pathlib import Path

import pandas as pd

from src.data.common import (load_repositories_json,
                             compute_chatgpt_sharings_stats, add_is_cloned_column)
from src.data.sharings import find_most_recent_commit_sharings
from src.utils.functools import timed

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_commit_sharings(commit_sharings_path, repo_clone_data):
    """Read commit sharings, convert to dataframe, and aggregate over repos

    In DevGPT GitHub Commit sharings, the only field that is not scalar valued
    is 'ChaptgptSharing' field.  To convert commit sharing to dataframe,
    values contained in this field needs to be summarized into a few scalars
    (see docstring for :func:`compute_chatgpt_sharings_stats`).

    Additionally, an aggregate over repositories is computed, and also
    returned.  This aggregate dataframe included basic informations about
    the repository, and the summary of the summary of 'ChatgptSharing' field.

    :param PathLike commit_sharings_path: path to commit sharings JSON file
        from DevGPT dataset; the format of this JSON file is described in
        https://github.com/NAIST-SE/DevGPT/blob/main/README.md#github-commit
    :param dict repo_clone_data: information extracted from <repositories.json>,
        used to add 'is_cloned' column to one of resulting dataframes
    :return: sharings aggregated over commit (first dataframe), an over
        repos (second dataframe in the tuple)
    :rtype: (pd.DataFrame, pd.DataFrame)
    """
    with open(commit_sharings_path) as commit_sharings_file:
        commit_sharings = json.load(commit_sharings_file)

    if 'Sources' not in commit_sharings:
        print(f"ERROR: unexpected format of '{commit_sharings_path}'")
        sys.exit(ERROR_OTHER)

    commit_sharings = commit_sharings['Sources']
    compute_chatgpt_sharings_stats(commit_sharings)

    df_commit = pd.DataFrame.from_records(commit_sharings)

    grouped = df_commit.groupby(by=['RepoName'], dropna=False)
    df_repo = grouped.agg({
        'RepoLanguage': 'first',
        'Sha': 'count',
        **{
            col: 'sum'
            for col in [
                'NumberOfChatgptSharings', 'Status404',
                'ModelGPT4', 'ModelGPT3.5', 'ModelOther',
                'TotalNumberOfPrompts', 'TotalTokensOfPrompts', 'TotalTokensOfAnswers',
                'NumberOfConversations',
            ]
        }
    })

    add_is_cloned_column(df_repo, repo_clone_data)

    return df_commit, df_repo


@timed
def main():
    # handle command line parameters
    # {script_name} <dataset_path> <repositories.json> <output_dir>
    if len(sys.argv) != 3 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    dataset_directory_path = Path(sys.argv[1])
    repositories_info_path = Path(sys.argv[2])
    output_dir_path = Path(sys.argv[3])

    # sanity check values of command line parameters
    if not dataset_directory_path.exists():
        print(f"ERROR: <dataset_path> '{dataset_directory_path}' does not exist")
        sys.exit(ERROR_ARGS)
    if not dataset_directory_path.is_dir():
        print(f"ERROR: <dataset_path> '{dataset_directory_path}' is not a directory")
        sys.exit(ERROR_ARGS)
    if not repositories_info_path.exists():
        print(f"ERROR: <repositories.json> '{repositories_info_path}' does not exist")
        sys.exit(ERROR_ARGS)
    if not repositories_info_path.is_file():
        print(f"ERROR: <repositories.json> '{repositories_info_path}' is not a file")
        sys.exit(ERROR_ARGS)
    if output_dir_path.exists() and not output_dir_path.is_dir():
        print(f"ERROR: <output_dir> '{output_dir_path}' exists and is not a directory")
        sys.exit(ERROR_ARGS)

    # ensure that <output_dir> exists
    if not output_dir_path.exists():
        output_dir_path.mkdir(parents=True, exist_ok=True)

    # .......................................................................
    # PROCESSING
    repo_clone_data = load_repositories_json(repositories_info_path)

    print(f"Finding sharings from DevGPT dataset at '{dataset_directory_path}'...",
          file=sys.stderr)
    commit_sharings_path = find_most_recent_commit_sharings(dataset_directory_path)
    print(f"Sharings for commit at '{commit_sharings_path}'", file=sys.stderr)

    commit_df, repo_df = process_commit_sharings(commit_sharings_path, repo_clone_data)
    # write per-commit data
    commit_sharings_path = output_dir_path.joinpath('commit_sharings_df.csv')
    print(f"Writing {commit_df.shape} of per-commit sharings data "
          f"to '{commit_sharings_path}'", file=sys.stderr)
    commit_df.to_csv(commit_sharings_path, index=False)
    # write per-repo data
    repo_sharings_path = output_dir_path.joinpath('commit_sharings_groupby_repo_df.csv')
    print(f"Writing {repo_df.shape} of repo-aggregated commit sharings data "
          f"to '{repo_sharings_path}'", file=sys.stderr)
    repo_df.to_csv(repo_sharings_path, index=True)


if __name__ == '__main__':
    main()
