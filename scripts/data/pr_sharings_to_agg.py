#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <repositories.json> <output_dir>

Extract information about prs from DevGPT's *_pr_sharings.json
in the <dataset_path>, aggregating data about ChatGPT conversations.
Aggregate information about projects (group by project).

From https://github.com/NAIST-SE/DevGPT/blob/main/README.md#github-pull-request
- 'Type': Source type (always "pull request")
- 'URL': URL to the mentioned source
  (https://github.com/{{owner}}/{{repo}}/pulls/{{pull_number}})
- 'Author': Author who introduced this mention (GitHub author, e.g. "tisztamo")
- 'RepoName': Name of the repository that contains this pull request
  (full repo name: {{owner}}/{{repo}}, e.g. "dotCMS/core")
- 'RepoLanguage': Primary programming language of the repository that contains
  this pull request. NOTE: it can be null when this repository does not contain
  any code (e.g. "C++", "Python", "HTML",...)
- 'Number': Pull request number of this mention (that is, {{pull_number}} in URL)
- 'Title': Title of this pull request (e.g. "Add URLPattern logo")
- 'Body': Description of this pull request (might be empty, i.e. "")
- 'CreatedAt': When the author created this pull request
  (e.g. "2023-09-16T06:02:27Z")
- 'ClosedAt': When this pull request was closed
  NOTE: it can be null when this issue is not closed
- 'MergedAt': When this pull request was merged
  NOTE: it can be null when this issue is not merged
- 'UpdatedAt': When the latest update occurred
- 'State': The state of this pull request (i.e., OPEN, CLOSED, MERGED)
- 'Additions': Number of lines added in this pull request
- 'Deletions': Number of lines deleted in this pull request
- 'ChangedFiles': Number of files changed in this pull request
- 'CommitsTotalCount': Number of commits included in this pull request
- 'CommitSha': A *list* of commit Shas that are included in this pull request
- 'ChatgptSharing':	A *list* of ChatGPT link mentions.

Example:
    python scripts/data/pr_sharings_to_agg.py \\
        data/external/DevGPT/ data/repositories_download_status.json \\
        data/interim/
"""
import json
import sys
from os import PathLike
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.data.common import (load_repositories_json,
                             compute_chatgpt_sharings_stats, add_is_cloned_column)
from src.data.sharings import find_most_recent_pr_sharings
from src.utils.functools import timed
from src.utils.github import get_Github, get_github_repo_cached, get_github_pull_request

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_pr_sharings(pr_sharings_path, repo_clone_data):
    """Read pr sharings, convert to dataframe, and aggregate over repos

    In DevGPT GitHub PR sharings, there are a few fields that are not scalar
    valued. One of them is 'ChaptgptSharing' field.  To convert ChatGPT sharing
    to dataframe, values contained in this field needs to be summarized into
    a few scalars (see docstring for :func:`compute_chatgpt_sharings_stats`).

    Another is 'CommitSha', which contains a list of commit Shas that are
    included in given pull request.  We can extract first and last commit
    from this list (the number of commits is already included as a
    'CommitsTotalCount' field), and ask GitHub API for merge commit,
    if pull request was merged in.

    Additionally, an aggregate over repositories is computed, and also
    returned.  This aggregate dataframe included basic information about
    the repository, and the summary of the summary of non-scalar fields.

    :param PathLike pr_sharings_path: path to pr sharings JSON file
        from DevGPT dataset; the format of this JSON file is described in
        https://github.com/NAIST-SE/DevGPT/blob/main/README.md#github-pull-request
    :param dict repo_clone_data: information extracted from <repositories.json>,
        used to add 'is_cloned' column to one of resulting dataframes
    :return: sharings aggregated over pull request (first dataframe),
        and over repos (second dataframe in the tuple),
        and sharings aggregated over pull request split into
        individual commits (third dataframe)
    :rtype: (pd.DataFrame, pd.DataFrame, pd.DataFrame)
    """
    with open(pr_sharings_path) as pr_sharings_file:
        pr_sharings = json.load(pr_sharings_file)

    if 'Sources' not in pr_sharings:
        print(f"ERROR: unexpected format of '{pr_sharings_path}'")
        sys.exit(ERROR_OTHER)

    pr_sharings = pr_sharings['Sources']
    commitsha_dict = compute_commitsha_stats(pr_sharings)
    retrieve_merge_commit_sha_for_pr(pr_sharings)
    compute_pr_state_stats(pr_sharings)
    compute_chatgpt_sharings_stats(pr_sharings,
                                   mentioned_property_values=['title', 'body', 'comments.body', 'reviews.body'])

    df_pr = pd.DataFrame.from_records(pr_sharings)

    df_commitshas = pd.DataFrame.from_records(
        [(url, *idx_and_sha)
         for url, shas in commitsha_dict.items()
         for idx_and_sha in shas],
        columns=['URL', 'CommitIdx', 'Sha'],
        index='URL',
    )
    df_pr_split = (
        df_pr
        # drop column df_commitshas would add
        .drop(columns=['Sha'], errors='ignore')
        # drop columns with large data (can later be 'join'-ed)
        .drop(columns=['Title', 'Body'])
        # merge 'Sha' for every individual commit in 'CommitSha' in PR
        .join(df_commitshas, on='URL')
    )

    grouped = df_pr.groupby(by=['RepoName'], dropna=False)
    df_repo = grouped.agg({
        'RepoLanguage': 'first',
        'Number': 'count',  # counts PR per repo
        'Sha': 'count',  # generated by retrieve_merge_commit_sha_for_pr()
        **{
            col: 'sum'
            for col in [
                # directly from DevGPT pr sharings file
                'Additions', 'Deletions',
                'ChangedFiles',
                'CommitsTotalCount',
                # from data added by compute_pr_state_stats()
                'StateOpen', 'StateClosed', 'StateMerged',
                # from data added by compute_chatgpt_sharings_stats()
                'NumberOfChatgptSharings', 'Status404',
                'ModelGPT4', 'ModelGPT3.5', 'ModelOther',
                'TotalNumberOfPrompts', 'TotalTokensOfPrompts', 'TotalTokensOfAnswers',
                'NumberOfConversations',
            ]
        }
    })

    add_is_cloned_column(df_repo, repo_clone_data)

    return df_pr, df_repo, df_pr_split


def compute_commitsha_stats(the_sharings):
    commitsha_dict = {}
    for source in tqdm(the_sharings, desc="source ('CommitSha')"):
        commitsha_list = source['CommitSha']
        del source['CommitSha']

        source['FirstCommitSha'] = commitsha_list[0]
        source['LastCommitSha'] = commitsha_list[-1]

        commitsha_dict[source['URL']] = list(enumerate(commitsha_list))  # un-lazy

    return commitsha_dict


def retrieve_merge_commit_sha_for_pr(pr_sharings):
    g = get_Github()
    github_repo_cache = {}

    print("Adding merge_commit_sha...", file=sys.stderr)
    for source in tqdm(pr_sharings, desc="source"):
        repo_name = source['RepoName']

        repo = get_github_repo_cached(g, repo_name,
                                      repo_name, github_repo_cache)
        if repo is None:
            tqdm.write(f"WARNING: couldn't access repo on GitHub: {repo_name}")
            continue

        pull_request = get_github_pull_request(repo, source['Number'])
        if pull_request is None:
            tqdm.write(f"WARNING: couldn't access #{source['Number']} pull request in {repo_name} repo")
            continue

        # accessing attribute is faster than running pull_request.is_merged()
        if pull_request.merged:
            sha = pull_request.merge_commit_sha
        else:
            # there is trial (?) merge sha for unmerged pull request, but
            # "This commit does not belong to any branch on this repository,
            #  and may belong to a fork outside of the repository."
            sha = None

        if 'Sha' in source:
            source['MergeSha'] = sha
        else:
            source['Sha'] = sha


def compute_pr_state_stats(the_sharings):
    for source in tqdm(the_sharings, desc="source ('State')"):
        if 'State' not in source:
            tqdm.write(f"warning: 'State' field is missing "
                       f"for {source['RepoName']} PR #{source['Number']}")
            continue

        pr_state = source['State']
        # it is a scalar field, we just one-hot encode it in addition

        source['StateOpen'] = bool(pr_state == 'OPEN')
        source['StateClosed'] = bool(pr_state == 'CLOSED')
        source['StateMerged'] = bool(pr_state == 'MERGED')


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
    pr_sharings_path = find_most_recent_pr_sharings(dataset_directory_path)
    print(f"Sharings for pr at '{pr_sharings_path}'", file=sys.stderr)

    pr_df, repo_df, pr_split_df = process_pr_sharings(pr_sharings_path, repo_clone_data)
    # write per-pr data
    pr_sharings_path = output_dir_path.joinpath('pr_sharings_df.csv')
    print(f"Writing {pr_df.shape} of per-pr sharings data "
          f"to '{pr_sharings_path}'", file=sys.stderr)
    pr_df.to_csv(pr_sharings_path, index=False)
    # write per-repo data
    repo_sharings_path = output_dir_path.joinpath('pr_sharings_groupby_repo_df.csv')
    print(f"Writing {repo_df.shape} of repo-aggregated pr sharings data "
          f"to '{repo_sharings_path}'", file=sys.stderr)
    repo_df.to_csv(repo_sharings_path, index=True)
    # write per-pr data, split into individual commits
    pr_split_sharings_path = output_dir_path.joinpath('pr_sharings_split_commit_df.csv')
    print(f"Writing {pr_split_df.shape} of per-pr sharings data, split into commits in pr, "
          f"to '{pr_split_sharings_path}'", file=sys.stderr)
    pr_split_df.to_csv(pr_split_sharings_path, index=False)


if __name__ == '__main__':
    main()
