#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <commit_sharings_df> <repositories.json> <output_commit_df> <output_lines_df>

Compute survival of changed lines for each commit in the <commit_sharings_df>,
using cloned repositories (as described by <repositories.json>) and the
reverse blame.

While at it, add some commit metadata to the dataframe.

TODO: describe <output_lines_df>

Example:
    python scripts/data/compute_changes_survival.py \\
        data/interim/commit_sharings_df.csv data/repositories_download_status.json \\
        data/interim/commit_sharings_changes_survival_df.csv \\
        data/interim/commit_sharings_lines_survival_df.csv
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List

import pandas as pd
import unidiff
from tqdm import tqdm

from src.data.common import load_repositories_json
from src.utils.functools import timed
from src.utils.git import GitRepo, changes_survival_perc

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_single_commit(repo: GitRepo, project_name: str, gpt_commit: str, process_stats: dict) \
        -> Tuple[dict, Optional[dict]]:
    commit_metadata = repo.get_commit_metadata(gpt_commit)
    augment_curr = {
        'Sha': gpt_commit,  # to be used for join
        'author_timestamp': commit_metadata['author']['timestamp'],
        'committer_timestamp': commit_metadata['committer']['timestamp'],
        'n_parents': len(commit_metadata['parents']),
    }

    is_merged = repo.check_merged_into(gpt_commit, 'HEAD')
    augment_curr['is_merged_HEAD'] = bool(is_merged)
    if not is_merged:
        # TODO: add to lines_data even if commit is not merged into HEAD
        # (currently, so far all commits are found to be merged)
        process_stats['n_unmerged'] += 1
        return augment_curr, None

    # at this point we know that HEAD contains gpt_commit
    commits_from_HEAD = repo.count_commits(until_commit=gpt_commit)
    augment_curr['number_of_commits_from_HEAD'] = commits_from_HEAD

    try:
        commits_data, survival_info = repo.changes_survival(gpt_commit)
        augment_curr['error'] = False

    except subprocess.CalledProcessError as err:
        tqdm.write(f"{err=}")
        augment_curr['error'] = True
        process_stats['n_errors'] += 1
        return augment_curr, None

    except unidiff.UnidiffParseError as err:
        tqdm.write(f"Project '{project_name}', commit {gpt_commit}\n"
                   f"  at '{repo!s}'")
        tqdm.write(f"{err=}")
        augment_curr['error'] = True
        process_stats['n_errors'] += 1
        return augment_curr, None

    lines_survived, lines_total = changes_survival_perc(survival_info)
    augment_curr.update({
        'change_lines_survived': lines_survived,
        'change_lines_total': lines_total,
    })
    process_stats['lines_survived_sum'] += lines_survived
    process_stats['lines_total_sum'] += lines_total

    # TODO: extract this into separate function
    if lines_survived < lines_total:
        survived_until = []

        all_blame_commit_data = {}
        for change_path_data in commits_data.values():
            all_blame_commit_data.update(change_path_data)

        for change_path_data in commits_data.values():
            for blame_commit_data in change_path_data.values():
                if 'previous' in blame_commit_data:
                    blame_prev = blame_commit_data['previous'].split(' ')[0]

                    if blame_prev in all_blame_commit_data:
                        blame_prev_timestamp = int(all_blame_commit_data[blame_prev]['committer-time'])
                    else:
                        blame_prev_timestamp = repo.get_commit_metadata(blame_prev)['committer']['timestamp']

                    survived_until.append(blame_prev_timestamp)

        # DEBUGGING for 'min_died_committer_timestamp'
        # tqdm.write(f"* {project_name} {gpt_commit[:8]} changes died at {sorted(survived_until)}")
        if survived_until:  # is not empty
            augment_curr['min_died_committer_timestamp'] = min(survived_until)

    return augment_curr, survival_info


def process_commit_changed_lines(project_name: str, gpt_commit: str, survival_info: dict) -> List[dict]:
    lines_data = []
    for change_path, change_lines_list in survival_info.items():
        for change_line_info in change_lines_list:
            if 'previous' in change_line_info:
                prev_commit, prev_file = change_line_info['previous'].split(' ')
                change_line_info['previous_commit'] = prev_commit
                change_line_info['previous_filename'] = prev_file

            lines_data.append({
                'RepoName': project_name,
                'Sha': gpt_commit,
                'filename': change_path,
                **change_line_info,
            })

    return lines_data


def process_commits(commits_df: pd.DataFrame, repo_clone_data: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Process commits in the `commits_df` dataframe, augmenting the data

    For each commit, compute how many of its post-image lines survived to current
    state of the project, and use it to augment per-commit data.

    :param pd.DataFrame commits_df: DataFrame with commits sharings from DevGPT
    :param dict repo_clone_data: information about cloned project's repositories
    :return: DataFrame augmented with changes survival information
    :rtype: (pd.DataFrame, pd.DataFrame)
    """
    commits_df.rename(columns={'ModelGPT3.5': 'ModelGPT3_5'}, inplace=True)

    repo_cache = {}
    total_stats = {
        'n_skipped': 0,
        'n_errors': 0,
        'n_unmerged': 0,
        'lines_survived_sum': 0,
        'lines_total_sum': 0,
    }
    augment_data = []
    lines_data = []
    for row in tqdm(commits_df.itertuples(index=False, name='GptCommit'), desc='commit'):
        project_name = row.RepoName
        gpt_commit = row.Sha

        project_dir = project_name.split('/')[-1]
        if project_dir not in repo_clone_data:
            total_stats['n_skipped'] += 1
            continue

        repo = repo_cache.get(project_name, None)
        if repo is None:
            # call only if needed
            repo = GitRepo(repo_clone_data[project_dir]['repository_path'])
            # remember for re-use
            repo_cache[project_name] = repo

        augment_curr, survival_info = process_single_commit(repo, project_name, gpt_commit, total_stats)
        augment_data.append(augment_curr)

        if survival_info is not None:
            commit_lines_data = process_commit_changed_lines(project_name, gpt_commit, survival_info)
            lines_data.extend(commit_lines_data)

    if total_stats['n_skipped'] > 0:
        print(f"Skipped {total_stats['n_skipped']} rows because repo was not cloned",
              file=sys.stderr)
    if total_stats['n_errors'] > 0:
        print(f"Skipped {total_stats['n_errors']} rows because of an error",
              file=sys.stderr)
    if total_stats['n_unmerged'] > 0:
        print(f"There were {total_stats['n_unmerged']} commits not merged into HEAD",
              file=sys.stderr)

    print(f"Created {len(repo_cache)} of GitRepo objects", file=sys.stderr)
    print(f"Lines survival stats: {total_stats}", file=sys.stderr)
    print(f"  {100.0*total_stats['lines_survived_sum']/total_stats['lines_total_sum']:.2f}% lines survived",
          file=sys.stderr)

    print(f"Creating dataframe with augmentation data from {len(augment_data)} records...",
          file=sys.stderr)
    augment_df = pd.DataFrame.from_records(augment_data)

    print(f"Creating dataframe with line survival data from {len(lines_data)} records...",
          file=sys.stderr)
    lines_df = pd.DataFrame.from_records(lines_data)

    print(f"Merging {commits_df.shape} with {augment_df.shape} dataframes on 'Sha'...", file=sys.stderr)
    return pd.merge(commits_df, augment_df, on='Sha', sort=False), lines_df


@timed
def main():
    # handle command line parameters
    # {script_name} <commit_sharings_df> <repositories.json>  <output_commit_df> <output_lines_df>
    if len(sys.argv) != 4 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    commit_sharings_path = Path(sys.argv[1])
    repositories_info_path = Path(sys.argv[2])
    output_commit_file_path = Path(sys.argv[3])
    output_lines_file_path = Path(sys.argv[4])

    # ensure that directory/directories leading to output_*_file_path exists
    output_commit_file_path.parent.mkdir(parents=True, exist_ok=True)
    output_lines_file_path.parent.mkdir(parents=True, exist_ok=True)

    # .......................................................................
    # PROCESSING
    print(f"Reading commit sharings data from '{commit_sharings_path}'...",
          file=sys.stderr)
    commits_df = pd.read_csv(commit_sharings_path)
    repo_clone_data = load_repositories_json(repositories_info_path)

    print(f"Processing {commits_df.shape} commit sharings data...",
          file=sys.stderr)
    augmented_df, lines_df = process_commits(commits_df, repo_clone_data)

    print(f"Writing {augmented_df.shape} of augmented commit sharings data\n"
          f"  to '{output_commit_file_path}'", file=sys.stderr)
    augmented_df.to_csv(output_commit_file_path, index=False)
    print(f"Writing {lines_df.shape} of changed lines survival data\n"
          f"  to '{output_lines_file_path}'", file=sys.stderr)
    lines_df.to_csv(output_lines_file_path, index=False)


if __name__ == '__main__':
    main()
