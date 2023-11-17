#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <repositories.json> <output_dir>

Extract information about commits from DevGPT's *_commit_sharings.json
in the <dataset_path>, aggregating data about ChatGPT conversations.
Aggregate information about projects (group by project).

Example:
    python src/data/commit_sharings_to_agg.py \\
        data/external/DevGPT/ data/repositories_download_status.json \\
        data/interim/
"""
import json
import sys
from os import PathLike
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.data.common import load_repositories_json
from src.data.sharings import find_most_recent_sharings_files
from src.utils.functools import timed

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_commit_sharings(commit_sharings_path, repo_clone_data):
    """

    :param PathLike commit_sharings_path:
    :param dict repo_clone_data:
    :return:
    :rtype: (pd.DataFrame, pd.DataFrame)
    """
    with open(commit_sharings_path) as commit_sharings_file:
        commit_sharings = json.load(commit_sharings_file)

    if 'Sources' not in commit_sharings:
        print(f"ERROR: unexpected format of '{commit_sharings_path}'")
        sys.exit(ERROR_OTHER)

    commit_sharings = commit_sharings['Sources']
    chatgpt_sharings = {}
    for source in tqdm(commit_sharings, desc='source'):
        chatgpt_sharings_list = source['ChatgptSharing']
        chatgpt_sharings[source['Sha']] = chatgpt_sharings_list
        del source['ChatgptSharing']

        source['NumberOfChatgptSharings'] = len(chatgpt_sharings_list)
        source['TotalNumberOfPrompts'] = 0
        source['TotalTokensOfPrompts'] = 0
        source['TotalTokensOfAnswers'] = 0
        source['NumberOfConversations'] = 0
        source['ModelGPT4'] = 0
        source['ModelGPT3.5'] = 0
        source['ModelOther'] = 0
        source['Status404'] = 0
        for chatgpt_sharing in chatgpt_sharings_list:
            # just in case value is null, or key is missing
            source['TotalNumberOfPrompts'] += chatgpt_sharing.get('NumberOfPrompts') or 0
            source['TotalTokensOfPrompts'] += chatgpt_sharing.get('TokensOfPrompts') or 0
            source['TotalTokensOfAnswers'] += chatgpt_sharing.get('TokensOfAnswers') or 0

            if 'Status' in chatgpt_sharing and chatgpt_sharing['Status'] == 404:
                source['Status404'] += 1

            if 'Model' in chatgpt_sharing:
                if chatgpt_sharing['Model'] == 'GPT-4':
                    source['ModelGPT4'] += 1
                elif chatgpt_sharing['Model'] == 'Default (GPT-3.5)':
                    source['ModelGPT3.5'] += 1
                else:
                    source['ModelOther'] += 1

            if 'Conversations' in chatgpt_sharing and chatgpt_sharing['Conversations'] is not None:
                conversations = chatgpt_sharing['Conversations']
                source['NumberOfConversations'] += len(conversations)

            # ...

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

    df_repo.loc[:, 'is_cloned'] = df_repo.index.map(
        lambda repo: repo.split('/')[-1] in repo_clone_data,
        na_action='ignore'
    )

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
    commit_sharings_path = find_most_recent_sharings_files(dataset_directory_path)['commit']
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
