#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <repositories.json> <output_dir>

Extract information about issues from DevGPT's *_issue_sharings.json
in the <dataset_path>, aggregating data about ChatGPT conversations.
Aggregate information about projects (group by project).

From https://github.com/NAIST-SE/DevGPT/blob/main/README.md#github-issue
- 'Type': Source type (always "issue")
- 'URL': URL to the mentioned source
  (https://github.com/{{owner}}/{{repo}}/issues/{{issue_number}})
- 'Author': Author who introduced this mention (GitHub author, e.g. "tisztamo")
- 'RepoName': Name of the repository that contains this issue
  (full repo name: {{owner}}/{{repo}}, e.g. "dotCMS/core")
- 'RepoLanguage': Primary programming language of the repository that contains
  this pull request. NOTE: it can be null when this repository does not contain
  any code (e.g. "C++", "Python", "HTML",...)
- 'Number': Issue number of this issue (that is, {{issue_number}} in URL)
- 'Title': Title of this issue (e.g. "Implement proper error handling")
- 'Body': Description of this issue (might be empty, i.e. "")
- 'AuthorAt': When the author created this issue
  (e.g. "2023-09-16T06:02:27Z")
- 'ClosedAt': When this issue was closed
  NOTE: it can be null when this issue is not closed
- 'UpdatedAt': When the latest update of this issue occurred
- 'State': The state of this pull request (i.e., OPEN, CLOSED)
- 'ChatgptSharing':	A *list* of ChatGPT link mentions.

Example:
    python scripts/data/issue_sharings_to_agg.py \\
        data/external/DevGPT/ data/repositories_download_status.json \\
        data/interim/
"""
import json
import sys
from collections import defaultdict
from os import PathLike
from pathlib import Path
from collections.abc import Iterable

import fnc
import ghgql
import pandas as pd
from tqdm import tqdm

from src.data.common import (load_repositories_json,
                             compute_chatgpt_sharings_stats, add_is_cloned_column)
from src.data.sharings import find_most_recent_issue_sharings
from src.utils.functools import timed
from src.utils.github import GITHUB_API_TOKEN

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_issue_sharings(issue_sharings_path, repo_clone_data):
    """Read issue sharings, convert to dataframe, and aggregate over repos

    In DevGPT's GitHub Issue sharings, there is only a single non-scalar field,
    namely the 'ChaptgptSharing' field.  To convert ChatGPT sharing
    to dataframe, values contained in this field needs to be summarized into
    a few scalars (see docstring for :func:`compute_chatgpt_sharings_stats`).

    TODO: Because there is no 'Sha' of commit that closes the issue,
    it needs to be found with the help of GitHub API.

    Additionally, an aggregate over repositories is computed, and also
    returned.  This aggregate dataframe included basic information about
    the repository, and the summary of the summary of non-scalar fields.

    :param PathLike issue_sharings_path: path to issue sharings JSON file
        from DevGPT dataset; the format of this JSON file is described in
        https://github.com/NAIST-SE/DevGPT/blob/main/README.md#github-issue
    :param dict repo_clone_data: information extracted from <repositories.json>,
        used to add 'is_cloned' column to one of resulting dataframes
    :return: sharings aggregated over pull request (first dataframe),
        and over repos (second dataframe in the tuple)
    :rtype: (pd.DataFrame, pd.DataFrame)
    """
    with open(issue_sharings_path) as issue_sharings_file:
        issue_sharings = json.load(issue_sharings_file)

    if 'Sources' not in issue_sharings:
        print(f"ERROR: unexpected format of '{issue_sharings_path}'")
        sys.exit(ERROR_OTHER)

    issue_sharings = issue_sharings['Sources']
    issue_closer_shas_dict = retrieve_closing_commit_sha_for_issue(issue_sharings)
    issue_closer_shas_list = [
        {'URL': key, **value}
        for key, values
        in issue_closer_shas_dict.items()
        for value in values
    ]
    compute_field_values_stats(issue_sharings,
                               field='State', values=('OPEN', 'CLOSED'))
    compute_field_values_stats(issue_closer_shas_list,
                               field='closer', values=('Commit', 'PullRequest'),
                               missing_ok=True)
    compute_chatgpt_sharings_stats(
        issue_sharings,
        mentioned_property_values=['title', 'body', 'comments.body']
    )

    df_issue = pd.DataFrame.from_records(issue_sharings)
    df_sha = pd.DataFrame.from_records(
        issue_closer_shas_list,
        index='URL'
    )
    print(f"Merging/joining {df_issue.shape} and {df_sha.shape} dataframes into per-issue sharings data",
          file=sys.stderr)
    df_issue = df_issue.join(df_sha, on='URL')

    grouped = df_issue.groupby(by=['RepoName'], dropna=False)
    df_repo = grouped.agg({
        'RepoLanguage': 'first',
        'URL': 'nunique',  # counts issues per repo
        'Sha': 'count',  # generated by retrieve_closing_commit_sha_for_issue(), should be unique
        **{
            col: 'sum'
            for col in [
                # from data added by compute_field_values_stats();
                # states are title-cased as whole: OPEN -> Open, PullRequest -> Pullrequest
                'StateOpen', 'StateClosed',
                'closerCommit', 'closerPullrequest',
                # from data added by compute_chatgpt_sharings_stats()
                'NumberOfChatgptSharings', 'Status404',
                'ModelGPT4', 'ModelGPT3.5', 'ModelOther',
                'TotalNumberOfPrompts', 'TotalTokensOfPrompts', 'TotalTokensOfAnswers',
                'NumberOfConversations',
            ]
        }
    })

    add_is_cloned_column(df_repo, repo_clone_data)

    return df_issue, df_repo


def compute_field_values_stats(list_of_dicts,
                               field='State', values=('OPEN', 'CLOSED'),
                               missing_ok=False):
    """One-hot bool encode values of `field` from `values` subset of values

    This means that for each value in `values`, the dict in `list_of_dict`
    list is getting <field><value> entry, with True or False value depending
    on whether <field> value is <value> or not.

    Modifies `list_of_dicts`, and returns modified value.

    Example:
        >>> lod = [{'State': 'OPEN'}, {'State': 'CLOSED'}]
        >>> compute_field_values_stats(lod, field='State', values=('OPEN', 'CLOSED'))
        source ('State'): 100%|██████████| 2/2 [00:00<?, ?it/s]
        >>> lod
        [{'State': 'OPEN', 'StateOpen': True, 'StateClosed': False},
         {'State': 'CLOSED', 'StateOpen': False, 'StateClosed': True}]

    TODO: move compute_field_values_stats() to src.data.common module

    :param list[dict] list_of_dicts: data to augment with "one-hot"-like
        encoding of `field` field, limited to `values` subset of values;
        modified by the function
    :param str field: the key in dicts on the `list_of_dicts` list to examine
    :param Iterable[str] values: set, or list, or tuple of values
        to iterate and "one-hot"-like encode
    :param bool missing_ok: whether to missing keys are OK (and should
        be considered one of possible states / values), or whether it should
        warn about dict on `list_of_dicts` missing `field` key
    :return: modified `list_of_dicts` input
    :rtype: list[dict]
    """
    for source in tqdm(list_of_dicts, desc=f"source ('{field}')"):
        if field not in source:
            if missing_ok:
                source[f'{field}Missing'] = True
            else:
                tqdm.write(f"warning: '{field}' field is missing "
                           f"for '{source['RepoName']}' issue #{source['Number']}")
            continue

        if missing_ok:
            source[f'{field}Missing'] = False

        issue_field = source[field]
        # it is a scalar field, we just one-hot encode it in addition

        for val in values:
            source[f'{field}{val.title()}'] = bool(issue_field == val)


def retrieve_closing_commit_sha_for_issue(issue_sharings):
    """Retrieve closing PR or commit for every closed issue that has one

    For every issue on `issue_sharings` list, if it was closed, try to find
    using GitHub GraphQL API how it was closed.  If it was closed with
    a pull request, and pull request got merged, find SHA-1 id of its merge
    commit.  If the issue was closed with a commit, find its SHA-1 id.

    Returns information about found 'Sha'-s of closers, using 'URL' of
    issue as key (to be used to merge with the rest of the data about
    issue sharings).

    The GraphQL query is based on the following question on StackOverflow:
    https://stackoverflow.com/questions/62293896/github-api-how-to-know-if-an-issue-was-closed-by-a-fork-pull-request

    :param list[dict] issue_sharings: the 'Sources' part of issue sharings
        from DevGPT dataset, read from the appropriate JSON file (for example
        'snapshot_20231012/20231012_235128_issue_sharings.json')
    :return: information about closing pull request or closing commits
    :rtype: defaultdict[str, list[dict]]
    """
    # tested using https://docs.github.com/en/graphql/overview/explorer
    ghq_query = """
    query ($owner: String!, $repo: String!, $issue: Int!) {
      repository(name: $repo, owner: $owner) {
        issue(number: $issue) {
          timelineItems(itemTypes: CLOSED_EVENT, last: 100) {
            nodes {
              ... on ClosedEvent {
                closer {
                  __typename
                  ...on PullRequest {
                    url
                    merged
                    mergeCommit {
                      oid
                    }
                  }
                  ...on Commit {
                    url
                    oid
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    issue_closer_shas = defaultdict(list)
    print("Adding 'Sha' of issue-closing commit...", file=sys.stderr)
    if not GITHUB_API_TOKEN:
        print("WARNING: no GitHub API token found, skipping...", file=sys.stderr)
        return issue_closer_shas

    stats = {
        'n_open': 0,
        'n_closed': 0,
        'n_errors': 0,
        'n_unmerged': 0,
        'n_closer_pr': 0,
        'n_closer_commit': 0,
        'n_closer_other': 0,
    }
    with ghgql.GithubGraphQL(token=GITHUB_API_TOKEN) as ghapi:
        for source in tqdm(issue_sharings, desc="source (query 'Sha')"):
            owner, repo = source['RepoName'].split('/', maxsplit=1)
            issue = source['Number']  # Issue number of this issue

            # if issue is open, there can be no closing PR or commit
            if source['State'] == 'OPEN':
                stats['n_open'] += 1
                continue
            else:
                stats['n_closed'] += 1

            # perform query
            result = ghapi.query(query=ghq_query,
                                 variables={'owner': owner, 'repo': repo, 'issue': issue})

            # check for errors
            if 'errors' in result:
                tqdm.write(f"ERROR when performing GraphQL query for {owner}/{repo} issue #{issue}")
                for err in result['errors']:
                    tqdm.write(f"message={err['message']}")
                stats['n_errors'] += 1
                continue

            # process results
            if not fnc.has('data.repository.issue.timelineItems.nodes', result):
                tqdm.write(f"warning: unexpected result (no 'nodes') for GraphQL query: {owner}/{repo} issue #{issue}")
                stats['n_errors'] += 1
                continue

            nodes = result['data']['repository']['issue']['timelineItems']['nodes']
            for node in nodes:
                closer_type = fnc.get('closer.__typename', node)
                if closer_type == 'PullRequest':
                    issue_closer_shas[source['URL']].append({
                        'closer': 'PullRequest',
                        'url': fnc.get('closer.url', node),
                        'Sha':
                            fnc.get('closer.mergeCommit.oid', node)
                            if fnc.get('closer.merged', node)
                            else None
                    })
                    if not fnc.get('closer.merged', node):
                        stats['n_unmerged'] += 1
                    stats['n_closer_pr'] += 1
                    pass
                elif closer_type == 'Commit':
                    issue_closer_shas[source['URL']].append({
                        'closer': 'Commit',
                        'url': fnc.get('closer.url', node),
                        'Sha': fnc.get('closer.oid', node),
                    })
                    stats['n_closer_commit'] += 1
                    pass
                else:
                    stats['n_closer_other'] += 1
                    continue

                # end: for node in nodes
            # end: for source in issue_sharings
        # end: with ... as ghapi

    print("issue statistics:", file=sys.stderr)
    print(f"- {stats['n_open']:3d} open (no 'Sha')", file=sys.stderr)
    print(f"- {stats['n_closed']:3d} closed", file=sys.stderr)
    print("GitHub GraphQL API statistics:", file=sys.stderr)
    print(f"- {stats['n_errors']} errors", file=sys.stderr)
    print(f"issue closer statistics (/ {stats['n_closed']}):", file=sys.stderr)
    print(f"- {stats['n_closer_other']:3d} = {100.0*stats['n_closer_other']/stats['n_closed']:5.2f}% other",
          file=sys.stderr)
    print(f"- {stats['n_closer_commit']:3d} = {100.0*stats['n_closer_commit']/stats['n_closed']:5.2f}% commit",
          file=sys.stderr)
    print(f"- {stats['n_closer_pr']:3d} = {100.0*stats['n_closer_pr']/stats['n_closed']:5.2f}% pull request",
          file=sys.stderr)
    print(f"  - {stats['n_unmerged']:3d} unmerged pull requests", file=sys.stderr)
    print(f"  - {stats['n_closer_pr'] - stats['n_unmerged']:3d} merged pull requests", file=sys.stderr)
    print(f"found closer for {len(issue_closer_shas)} / {len(issue_sharings)} issues",
          f"({100.0*len(issue_closer_shas)/len(issue_sharings):5.2f}%)", file=sys.stderr)
    print(f"found {sum([len(elem) for elem in issue_closer_shas.values()])} 'Sha' total,",
          f"with max of {max([len(elem) for elem in issue_closer_shas.values()])} per issue", file=sys.stderr)

    return issue_closer_shas


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
    issue_sharings_path = find_most_recent_issue_sharings(dataset_directory_path)
    print(f"Sharings for issues at '{issue_sharings_path}'", file=sys.stderr)

    # DO WORK
    issue_df, repo_df = process_issue_sharings(issue_sharings_path, repo_clone_data)

    # write per-pr data
    issue_sharings_path = output_dir_path.joinpath('issue_sharings_df.csv')
    print(f"Writing {issue_df.shape} of per-issue sharings data "
          f"to '{issue_sharings_path}'", file=sys.stderr)
    issue_df.to_csv(issue_sharings_path, index=False)
    # write per-repo data
    repo_sharings_path = output_dir_path.joinpath('issue_sharings_groupby_repo_df.csv')
    print(f"Writing {repo_df.shape} of repo-aggregated issue sharings data "
          f"to '{repo_sharings_path}'", file=sys.stderr)
    repo_df.to_csv(repo_sharings_path, index=True)


if __name__ == '__main__':
    main()
