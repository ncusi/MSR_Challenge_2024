#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <sharings_df> <repositories.json> <output_similarities_df>

Example:
    python scripts/data/find_chatgpt_changes_similarity.py \\
        data/external/DevGPT/ \\
        data/interim/commit_sharings_df.csv data/repositories_download_status.json \\
        data/interim/commit_sharings_similarities_df.csv
"""
import contextlib
import json
import sys
import time
from pathlib import Path
from pprint import pprint

import joblib
import numpy as np
import pandas as pd
from tqdm import tqdm

from src.data.common import DownloadedRepositories
from src.data.sharings import find_most_recent_sharings_files
from src.utils.compare import CompareFragments, diff_to_conversation
from src.utils.functools import timed

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


# TODO: move to src/utils/helpers.py (or similar)
@contextlib.contextmanager
def tqdm_joblib(tqdm_object):
    """Context manager to patch joblib to report into tqdm progress bar given as argument

    Example:
        >>> from math import sqrt
        >>> from joblib import Parallel, delayed
        >>> with tqdm_joblib(tqdm(desc="My calculation", total=10)) as progress_bar:
        ...     Parallel(n_jobs=16)(delayed(sqrt)(i**2) for i in range(10))
    """

    class TqdmBatchCompletionCallback(joblib.parallel.BatchCompletionCallBack):
        def __call__(self, *args, **kwargs):
            tqdm_object.update(n=self.batch_size)
            return super().__call__(*args, **kwargs)

    old_batch_callback = joblib.parallel.BatchCompletionCallBack
    joblib.parallel.BatchCompletionCallBack = TqdmBatchCompletionCallback
    try:
        yield tqdm_object
    finally:
        joblib.parallel.BatchCompletionCallBack = old_batch_callback
        tqdm_object.close()


def find_commit_pair(source):
    if 'Sha' in source:
        commit = source['Sha']
        versus = None  # default to first parent of 'Sha'
    elif 'CommitSha' in source:
        if isinstance(source['CommitSha'], str):
            commit = source['CommitSha']
            versus = None  # default to first parent of 'Sha'
        else:  # assume it is a list, or equivalent
            commit = source['CommitSha'][-1]  # latest
            versus = source['CommitSha'][0] + '^'  # parent of earliest
    else:
        commit = None
        versus = None
    return commit, versus


def run_diff_to_conv(source, conv, compare, all_repos):
    repo_name = source['RepoName']
    assoc_url = source['URL']

    if 'Conversations' not in conv:
        tqdm.write(f"no 'Conversations' for {assoc_url}\n{conv.keys()=}, {conv['Status']=}")
        return assoc_url, {}, f"no 'Conversations' for {assoc_url}"

    commit, versus = find_commit_pair(source)
    if commit is None:
        tqdm.write(f"missing Sha or CommitSha for {assoc_url}")
        return assoc_url, {}, f"missing Sha or CommitSha for {assoc_url}"

    try:
        the_repo = all_repos.repo(repo_name)
        curr_diff = the_repo.unidiff(commit=commit, prev=versus)

        start = time.perf_counter()
        cmp_result = diff_to_conversation(curr_diff, conv, compare=compare, debug=True)
        return assoc_url, cmp_result, time.perf_counter() - start

    except Exception as ex:
        tqdm.write(f"exception {type(ex)} for {assoc_url}:\n{ex}")
        return assoc_url, {}, f"{type(ex)} exception for {assoc_url}: {ex}"


def process_sharings(sharings_data, sharings_df, all_repos):
    total_conv_len = sharings_df['NumberOfChatgptSharings'].sum()

    if 'Sha' in sharings_data[0]:
        print(f"'Sha' in sharings_data[0]: {sharings_data[0]['Sha']}", file=sys.stderr)
    elif 'CommitSha' in sharings_data[0]:
        print(f"'CommitSha' in sharings_data[0]: {sharings_data[0]['CommitSha']}", file=sys.stderr)
    else:
        print("No 'Sha' or 'CommitSha' in sharings_data[0]", file=sys.stderr)

    with tqdm_joblib(tqdm(desc="process_sharings", total=total_conv_len)) as progress_bar:
        ret_similarities = joblib.Parallel(n_jobs=1000)(
            joblib.delayed(run_diff_to_conv)(source, conv,
                                             compare=CompareFragments, all_repos=all_repos)
            for source in sharings_data
            for conv in source['ChatgptSharing']
        )
        progress_bar.set_postfix_str('done')

    print(f"There were {sum(1 for x in ret_similarities if not x[1])} problems"
          f"during the processing of {len(sharings_data)}/{total_conv_len} elements", file=sys.stderr)
    max_time = max(ret_similarities, key=lambda x: x[2] if x[1] else 0.0)
    sum_time = sum(x[2] for x in ret_similarities if x[1])
    print(f"Slowest at {max_time[2]} sec was with {len(max_time[1])} size for\n"
          f"  URL={max_time[0]}", file=sys.stderr)
    print(f"Sum of all times is {sum_time} sec (sequential time)", file=sys.stderr)

    # TODO: extract into separate function
    sharings_dict = { source['URL']: source for source in sharings_data }

    result_data = []
    stats = { 'n_no_FILES': 0, 'n_no_HUNKS': 0 }
    for ret in ret_similarities:
        url, sim_info, _ = ret

        # skip problematic entries (404 for ChatGPT, or error parsing commit diff)
        if not sim_info:
            continue

        source = sharings_dict[url]
        commit, versus = find_commit_pair(source)
        per_url_data = {
            'URL': url,
            'RepoName': source['RepoName'],
            'Sha': commit,
            'Prev': versus,
            'NumberOfChatGptSharings': len(source['ChatgptSharing']),
            'postimage_all': sim_info['ALL']['all'],
            'postimage_coverage': sim_info['ALL']['coverage'],
            'preimage_all': sim_info['ALL']['preimage_all'],
            'preimage_coverage': sim_info['ALL']['preimage_coverage'],
        }

        if 'FILES' not in sim_info:
            stats['n_no_FILES'] += 1
            continue

        for file, file_data in sim_info['FILES'].items():
            per_file_data = per_url_data
            per_file_data.update({
                'filename': file,
                'path_a': file_data['FILE'][0],
                'path_b': file_data['FILE'][1],
            })

            if 'HUNKS' not in file_data:
                stats['n_no_HUNKS'] += 1
                continue

            for hunk_idx, hunk_data in file_data['HUNKS'].items():
                per_hunk_data = per_file_data
                per_hunk_data.update({
                    'hunk_idx': hunk_idx,
                    'n_matched_lines': len(hunk_data['lines']),
                    'preimage_Prompt_ratio': hunk_data['pre']['p']['r'],
                    'postimage_Answer_ratio': hunk_data['post']['a']['r'],
                    'postimage_ListOfCode_ratio': hunk_data['post']['l']['r'],
                    # TODO: add other data, or save raw data as JSON/YAML/...
                })

                postimage_Answer_lines_ratio = {x[0]: x[2] for x in hunk_data['post']['A']}
                postimage_ListOfCode_lines_ratio = {x[0]: x[2] for x in hunk_data['post']['L']}
                for diff_line_no in hunk_data['lines']:
                    per_line_data = per_hunk_data
                    per_line_data.update({
                        'diff_line_no': diff_line_no,
                        'matches': True,
                        'postimage_Answer_line_ratio':
                            postimage_Answer_lines_ratio[diff_line_no]
                            if diff_line_no in postimage_Answer_lines_ratio
                            else np.nan,
                        'postimage_ListOfCode_line_ratio':
                            postimage_ListOfCode_lines_ratio[diff_line_no]
                            if diff_line_no in postimage_ListOfCode_lines_ratio
                            else np.nan,
                    })

                    result_data.append(per_line_data)

    print(f"Some statistics: {stats=}", file=sys.stderr)
    print(f"Creating dataframe with per matched line data from {len(result_data)} records...",
          file=sys.stderr)
    result_df = pd.DataFrame.from_records(result_data)
    print(f"Created dataframe with {result_df.shape} shape", file=sys.stderr)

    return result_df


@timed
def main():
    # handle command line parameters
    # {script_name} <dataset_path> <sharings_df> <repositories.json> <output_similarities_df>
    if len(sys.argv) != 4 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    dataset_path = Path(sys.argv[1])
    sharings_df_path = Path(sys.argv[2])
    repositories_info_path = Path(sys.argv[3])
    output_file_path = Path(sys.argv[4])

    # ensure that directory/directories leading to output_file_path exists
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    # .......................................................................
    # CHECKING AND PROCESSING ARGUMENTS

    # sanity check values of command line parameters
    if not dataset_path.exists():
        print(f"ERROR: <dataset_path> '{dataset_path}' does not exist")
        sys.exit(ERROR_ARGS)
    if not sharings_df_path.is_file():
        print(f"ERROR: <sharings_df> '{sharings_df_path}' does not exist or is not a file")
        sys.exit(ERROR_ARGS)
    if not repositories_info_path.is_file():
        print(f"ERROR: <repositories.json> '{repositories_info_path}' does not exist or is not a file")
        sys.exit(ERROR_ARGS)

    # handling dataset_path being a file or a directory
    if dataset_path.is_dir():
        sharings_df_basename = str(sharings_df_path.name)
        possible_types = ['commit', 'pr', 'issue', 'file']
        for guess_type in possible_types:
            if sharings_df_basename.startswith(f"{guess_type}_sharings_"):
                print(f"Guessing sharings type to be '{guess_type}'", file=sys.stderr)
                dataset_path = find_most_recent_sharings_files(dataset_path, verbose=True)[guess_type]
                print(f"Sharings for {guess_type} at '{dataset_path}'", file=sys.stderr)
                break

        else:
            print(f"Did not find sharing among {possible_types}\n"
                  f"for <sharings_df> '{sharings_df_path}'", file=sys.stderr)

    # .......................................................................
    # READING INPUTS
    print(f"Reading dataset sharings JSON from '{dataset_path}'...", file=sys.stderr)
    with open(dataset_path) as dataset_sharings_file:
        sharings_data = json.load(dataset_sharings_file)

    if 'Sources' not in sharings_data:
        print(f"ERROR: unexpected format of '{dataset_sharings_file}'")
        sys.exit(ERROR_OTHER)

    sharings_data = sharings_data['Sources']

    print(f"Reading sharings dataframe from '{sharings_df_path}'...", file=sys.stderr)
    sharings_df = pd.read_csv(sharings_df_path)
    print(f"Read {sharings_df.shape} sharings data...", file=sys.stderr)

    all_repos = DownloadedRepositories(repositories_info_path, verbose=True)

    # .......................................................................
    # PROCESSING
    output_df = process_sharings(sharings_data, sharings_df, all_repos)

    # .......................................................................
    # SAVING RESULTS
    print(f"Writing {output_df.shape} of augmented commit sharings data\n"
          f"  to '{output_file_path}'", file=sys.stderr)
    output_df.to_csv(output_file_path, index=False)

    print("(done)")


if __name__ == '__main__':
    main()
