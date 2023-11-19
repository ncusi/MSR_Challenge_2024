#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <commit_sharings_df> <repositories.json> <output_file_df>

Compute survival of changed lines for each commit in the <commit_sharings_df>,
using cloned repositories (as described by <repositories.json>) and the
reverse blame.

While at it, add some commit metadata to the dataframe.

Example:
    python scripts/data/compute_changes_survival.py \\
        data/interim/commit_sharings_df.csv data/repositories_download_status.json \\
        data/interim/commit_sharings_changes_survival_df.csv
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import unidiff
from tqdm import tqdm

from src.data.common import load_repositories_json
from src.utils.functools import timed
from src.utils.git import GitRepo, changes_survival_perc

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


def process_commits(commits_df: pd.DataFrame, repo_clone_data: dict) -> pd.DataFrame:
    """Process commits in the `commits_df` dataframe, augmenting the data

    For each commit, compute how many of its post-image lines survived to current
    state of the project, and use it to augment per-commit data.

    :param pd.DataFrame commits_df: DataFrame with commits sharings from DevGPT
    :param dict repo_clone_data: information about cloned project's repositories
    :return: DataFrame augmented with changes survival information
    :rtype: pd.DataFrame
    """
    commits_df.rename(columns={'ModelGPT3.5': 'ModelGPT3_5'}, inplace=True)

    n_skipped = 0
    n_errors = 0
    n_unmerged = 0
    repo_cache = {}
    total_stats = {
        'lines_survived_sum': 0,
        'lines_total_sum': 0,
    }
    augment_data = []
    for row in tqdm(commits_df.itertuples(index=False, name='GptCommit'), desc='commit'):
        project_name = row.RepoName
        gpt_commit = row.Sha

        project_dir = project_name.split('/')[-1]
        if project_dir not in repo_clone_data:
            n_skipped += 1
            continue

        repo = repo_cache.get(project_name, None)
        if repo is None:
            # call only if needed
            repo = GitRepo(repo_clone_data[project_dir]['repository_path'])
            # remember for re-use
            repo_cache[project_name] = repo

        commit_metadata = repo.get_commit_metadata(gpt_commit)
        augment_curr = {
            'Sha': row.Sha,  # to be used for join
            'author_timestamp': commit_metadata['author']['timestamp'],
            'committer_timestamp': commit_metadata['committer']['timestamp'],
        }

        is_merged = repo.check_merged_into(gpt_commit, 'HEAD')
        augment_curr['is_merged_HEAD'] = bool(is_merged)
        if not is_merged:
            augment_data.append(augment_curr)
            n_unmerged += 1
            continue

        # at this point we know that HEAD contains gpt_commit
        commits_from_HEAD = repo.count_commits(until_commit=gpt_commit)
        augment_curr['number_of_commits_from_HEAD'] = commits_from_HEAD

        try:
            _, survival_info = repo.changes_survival(gpt_commit)
            augment_curr['error'] = False

        except subprocess.CalledProcessError as err:
            tqdm.write(f"{err=}")
            augment_curr['error'] = True
            augment_data.append(augment_curr)
            n_errors += 1
            continue

        except unidiff.UnidiffParseError as err:
            tqdm.write(f"Project '{project_name}', commit {gpt_commit}\n"
                       f"  at '{repo!s}'")
            tqdm.write(f"{err=}")
            augment_curr['error'] = True
            augment_data.append(augment_curr)
            n_errors += 1
            continue

        lines_survived, lines_total = changes_survival_perc(survival_info)
        augment_curr.update({
            'change_lines_survived': lines_survived,
            'change_lines_total': lines_total,
        })
        total_stats['lines_survived_sum'] += lines_survived
        total_stats['lines_total_sum'] += lines_total

        augment_data.append(augment_curr)

    if n_skipped > 0:
        print(f"Skipped {n_skipped} rows because repo was not cloned", file=sys.stderr)
    if n_errors > 0:
        print(f"Skipped {n_errors} rows because of an error", file=sys.stderr)
    if n_unmerged > 0:
        print(f"There were {n_unmerged} commits not merged into HEAD", file=sys.stderr)

    print(f"Created {len(repo_cache)} of GitRepo objects", file=sys.stderr)
    print(f"Lines survival stats: {total_stats}", file=sys.stderr)
    print(f"  {100.0*total_stats['lines_survived_sum']/total_stats['lines_total_sum']:.2f}% lines survived",
          file=sys.stderr)

    print(f"Creating dataframe with augmentation data from {len(augment_data)} records...",
          file=sys.stderr)
    augment_df = pd.DataFrame.from_records(augment_data)

    print(f"Merging {commits_df.shape} with {augment_df.shape} dataframes on 'Sha'...", file=sys.stderr)
    return pd.merge(commits_df, augment_df, on='Sha', sort=False)


@timed
def main():
    # handle command line parameters
    # {script_name} <commit_sharings_df> <repositories.json> <output_file_df>
    if len(sys.argv) != 3 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    commit_sharings_path = Path(sys.argv[1])
    repositories_info_path = Path(sys.argv[2])
    output_file_path = Path(sys.argv[3])

    # ensure that directory leading to output_file_path exists
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    # .......................................................................
    # PROCESSING
    print(f"Reading commit sharings data from '{commit_sharings_path}'...",
          file=sys.stderr)
    commits_df = pd.read_csv(commit_sharings_path)
    repo_clone_data = load_repositories_json(repositories_info_path)

    print(f"Processing {commits_df.shape} commit sharings data...",
          file=sys.stderr)
    augmented_df = process_commits(commits_df, repo_clone_data)

    print(f"Writing {augmented_df.shape} of augmented commit sharings data\n"
          f"  to '{output_file_path}'", file=sys.stderr)
    augmented_df.to_csv(output_file_path, index=False)


if __name__ == '__main__':
    main()
