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
import subprocess
import sys
import time
from datetime import timedelta, datetime
from pathlib import Path

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

TRY_COMMITSHA = False  #: try 'CommitSha' field if 'Sha' is missing


# TODO: move to src/utils/helpers.py (or similar)
@contextlib.contextmanager
def tqdm_joblib_batch(tqdm_object):
    """Context manager to patch joblib to report into tqdm progress bar given as argument

    Example:
        >>> from math import sqrt
        >>> from joblib import Parallel, delayed
        >>> with tqdm_joblib_batch(tqdm(desc="My calculation", total=10)) as progress_bar:
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


# TODO: move to src/utils/helpers.py (or similar)
@contextlib.contextmanager
def tqdm_joblib_progress(tqdm_object):
    """Context manager to patch joblib to report into tqdm progress bar given as argument

    Example:
        >>> import time
        >>> from joblib import Parallel, delayed
        >>> from tqdm import tqdm
        >>>
        >>> def some_method(wait_time):
        >>>     time.sleep(wait_time)
        >>>
        >>> with tqdm_joblib_progress(tqdm(desc="My method", total=10)) as progress_bar:
        >>>     Parallel(n_jobs=2)(delayed(some_method)(0.2) for i in range(10))

    More detailed description of code on StackOverflow, where it was taken from
    https://stackoverflow.com/questions/24983493/tracking-progress-of-joblib-parallel-execution/61689175#61689175
    """
    def tqdm_print_progress(self):
        if self.n_completed_tasks > tqdm_object.n:
            n_completed = self.n_completed_tasks - tqdm_object.n
            tqdm_object.update(n=n_completed)

    original_print_progress = joblib.parallel.Parallel.print_progress
    joblib.parallel.Parallel.print_progress = tqdm_print_progress

    try:
        yield tqdm_object
    finally:
        joblib.parallel.Parallel.print_progress = original_print_progress
        tqdm_object.close()


def find_commit_pair(source):
    if 'Sha' in source:
        commit = source['Sha']
        versus = None  # default to first parent of 'Sha'
    elif TRY_COMMITSHA and 'CommitSha' in source:
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
        tqdm.write(f"no 'Conversations' for {assoc_url} ({conv['Status']=})")
        return assoc_url, {}, f"no 'Conversations' for {assoc_url}"

    commit, versus = find_commit_pair(source)
    if commit is None:
        # tqdm.write(f"missing Sha or CommitSha for {assoc_url}")
        return assoc_url, {}, f"missing Sha or CommitSha for {assoc_url}"

    try:
        the_repo = all_repos.repo(repo_name)
        curr_diff = the_repo.unidiff(commit=commit, prev=versus)

        start = time.perf_counter()
        cmp_result = diff_to_conversation(curr_diff, conv, compare=compare, debug=True)
        return assoc_url, cmp_result, time.perf_counter() - start

    except subprocess.CalledProcessError as err:
        tqdm.write(f"CalledProcessError for {assoc_url}\n{err}")
        tqdm.write(f"{repo_name=}, {commit=}, {versus=}")
        if hasattr(err, 'stderr') and err.stderr:
            if isinstance(err.stderr, (bytes, bytearray)):
                tqdm.write(f"{err.stderr.decode('utf8')}-----")
            else:
                tqdm.write(f"{err.stderr}-----")
        return assoc_url, {}, f"{type(err)} exception for {assoc_url}: {err}"
    except Exception as ex:
        tqdm.write(f"exception {type(ex)} for {assoc_url}:\n{ex}")
        return assoc_url, {}, f"{type(ex)} exception for {assoc_url}: {ex}"


def augment_sharings_data_with_sha(sharings_data, sharings_df):
    """Augment `sharings_data` with 'Sha' from `sharings_df`

    :param dict sharings_data: sharings data from DevGPT dataset
    :param pd.DataFrame sharings_df: dataframe generated by some
        previous step in pipeline, adding 'Sha'
    :rtype: None
    """
    if 'Sha' not in sharings_df.columns:
        print(f"No 'Sha' among sharings_df columns {sharings_df.shape}:\n"
              f"{sharings_df.columns}", file=sys.stderr)
        return

    # TODO: handle the rare case when there is more than one 'Sha' for an 'URL'
    # like there can be for issues (closed, reopened, closed again)
    # currently the code uses last 'Sha' for given 'URL'

    # list comprehension trick taken from
    # https://stackoverflow.com/questions/16476924/how-to-iterate-over-rows-in-a-pandas-dataframe/55557758#55557758
    url_to_sha = {
        url: sha
        for url, sha in
        zip(sharings_df['URL'], sharings_df['Sha'])
        if pd.notna(sha)
    }
    print(f"Found {len(url_to_sha)} 'URL' to 'Sha' mappings in sharings_df {sharings_df.shape}",
          file=sys.stderr)

    n_added_sha = 0
    for source in sharings_data:
        if 'Sha' not in source:
            url = source['URL']
            if url in url_to_sha:
                source['Sha'] = url_to_sha[url]
                n_added_sha += 1
    print(f"Added {n_added_sha}/{len(url_to_sha)} 'Sha' to {len(sharings_data)} sharings_data",
          file=sys.stderr)
    print(f"There are {sum(1 for x in sharings_data if 'Sha' not in x)} sharings without 'Sha'",
          file=sys.stderr)


def compute_chatgpt_changes_similarities(sharings_data, all_repos, total):
    start = time.perf_counter()
    with tqdm_joblib_batch(tqdm(desc="process_sharings", total=total)) as progress_bar:
        ret_similarities = joblib.Parallel(n_jobs=1000)(
            joblib.delayed(run_diff_to_conv)(source, conv,
                                             compare=CompareFragments, all_repos=all_repos)
            for source in sharings_data
            for conv in source['ChatgptSharing']
        )
        progress_bar.set_postfix_str('done')
    par_time = time.perf_counter() - start

    print(f"There were {sum(1 for x in ret_similarities if not x[1])} problems "
          f"during the processing of {len(sharings_data)}/{total} elements", file=sys.stderr)
    max_time = max(ret_similarities, key=lambda x: x[2] if x[1] else 0.0)
    sum_time = sum(x[2] for x in ret_similarities if x[1])
    print(f"Slowest at {max_time[2]} sec = {timedelta(seconds=max_time[2])}, "
          f"with {max_time[1]['ALL']['all']} 'postimage_all' was\n"
          f"  URL={max_time[0]}", file=sys.stderr)
    print(f"Sum of all times is {sum_time} sec = {timedelta(seconds=sum_time)} (serial)", file=sys.stderr)
    print(f"Actual compute time {par_time} sec = {timedelta(seconds=par_time)} (joblib)", file=sys.stderr)

    return ret_similarities


def process_sharings(sharings_data, sharings_df, all_repos,
                     checkpoint_file_path=None):
    """Process sharings, creating similarity data to save

    :param dict sharings_data: sharings data from DevGPT dataset
    :param pd.DataFrame sharings_df: dataframe generated by some
        previous step in pipeline, adding 'Sha' info to dataset if needed
    :param DownloadedRepositories all_repos: is used to retrieve
        `GitRepo` for repository given by its full GitHub name
    :param checkpoint_file_path: path to save/restore checkpoint JSON, optional
    :type checkpoint_file_path: Path or None
    :return: ChatGPT versus 'Sha' commit changes similarity data
    :rtype: pd.DataFrame
    """
    total_conv_len = sharings_df['NumberOfChatgptSharings'].sum()

    needs_augmenting = True
    if 'Sha' in sharings_data[0]:
        print(f"'Sha' in sharings_data[0]: {sharings_data[0]['Sha']}", file=sys.stderr)
        needs_augmenting = False
    elif 'CommitSha' in sharings_data[0]:
        print(f"'CommitSha' in sharings_data[0]: {sharings_data[0]['CommitSha']}", file=sys.stderr)
        if TRY_COMMITSHA:
            needs_augmenting = False
        else:
            print(f"which will not be used because {TRY_COMMITSHA=}", file=sys.stderr)
    else:
        print("No 'Sha' or 'CommitSha' in sharings_data[0]", file=sys.stderr)

    print(f"sharings_data needs augmenting with 'Sha' from sharings_df: {needs_augmenting}",
          file=sys.stderr)
    if needs_augmenting:
        augment_sharings_data_with_sha(sharings_data, sharings_df)

    recomputed = False
    if checkpoint_file_path is not None and checkpoint_file_path.exists():
        print(f"WARNING: reading state checkpoint from "
              f"{datetime.fromtimestamp(checkpoint_file_path.stat().st_mtime)}",
              file=sys.stderr)
        print(f"Reading ret_similarities data\n"
              f"  from '{checkpoint_file_path}'", file=sys.stderr)

        with open(checkpoint_file_path, 'r') as checkpoint_file:
            ret_similarities = json.load(checkpoint_file)

        print(f"Read {len(ret_similarities)} elements")

    else:
        ret_similarities = compute_chatgpt_changes_similarities(sharings_data, all_repos,
                                                                total_conv_len)
        recomputed = True

    if checkpoint_file_path is not None and recomputed:
        print(f"Saving ret_similarities data ({len(ret_similarities)} elements)\n"
              f"  to '{checkpoint_file_path}'", file=sys.stderr)
        with open(checkpoint_file_path, 'w') as checkpoint_file:
            json.dump(ret_similarities, checkpoint_file)

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
            per_file_data = {
                **per_url_data,
                'filename': file,
                'path_a': file_data['FILE'][0],
                'path_b': file_data['FILE'][1],
            }

            if 'HUNKS' not in file_data:
                stats['n_no_HUNKS'] += 1
                continue

            for hunk_idx, hunk_data in file_data['HUNKS'].items():
                per_hunk_data = {
                    **per_file_data,
                    'hunk_idx': hunk_idx,
                    'n_matched_lines': len(hunk_data['lines']),
                    'preimage_Prompt_ratio': hunk_data['pre']['p']['r'],
                    'postimage_Answer_ratio': hunk_data['post']['a']['r'],
                    'postimage_ListOfCode_ratio': hunk_data['post']['l']['r'],
                    # TODO: add other data, or save raw data as JSON/YAML/...
                }

                postimage_Answer_lines_ratio = {x[0]: x[2] for x in hunk_data['post']['A']}
                postimage_ListOfCode_lines_ratio = {x[0]: x[2] for x in hunk_data['post']['L']}
                for diff_line_no in hunk_data['lines']:
                    per_line_data = {
                        **per_hunk_data,
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
                    }

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
    checkpoint_file_path = output_file_path.with_suffix('.checkpoint_data.json')

    output_df = process_sharings(sharings_data, sharings_df, all_repos,
                                 checkpoint_file_path)

    # .......................................................................
    # SAVING RESULTS
    print(f"Writing {output_df.shape} of augmented commit sharings data\n"
          f"  to '{output_file_path}'", file=sys.stderr)
    output_df.to_csv(output_file_path, index=False)

    print("(done)")


if __name__ == '__main__':
    main()
