#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <commit_sharings_df> <repositories.json> <output_commit_df> <output_lines_df>

Compute survival of changed lines for each commit in the <commit_sharings_df>,
using cloned repositories (as described by <repositories.json>) and the
reverse blame.

While at it, add some commit metadata to the dataframe.  This information
is gathered into dataframe and saved in the <output_commit_df>.

Information about the fate of each post-image changed line ("added" line in
the unified diff of commit changes), for example in which commit it vanished
if it did vanish, is gathered into dataframe and saved in the <output_lines_df>.

See docstring for :func:`process_single_commit` to find columns added to original
<commit_sharings_df> columns in <output_commit_df>, and docstring for
:func:`process_commit_changed_lines` to find columns in <output_lines_df>.

Example:
    python scripts/data/compute_changes_survival.py \\
        data/interim/commit_sharings_df.csv data/repositories_download_status.json \\
        data/interim/commit_sharings_changes_survival_df.csv \\
        data/interim/commit_sharings_lines_survival_df.csv
"""
import subprocess
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import Optional, Tuple, List, NamedTuple

import pandas as pd
import unidiff
from tqdm import tqdm

from src.data.common import load_repositories_json, reponame_to_repo_path
from src.utils.functools import timed
from src.utils.git import GitRepo, changes_survival_perc

# constants
ERROR_ARGS = 1
ERROR_OTHER = 2


class GptCommitInfo(NamedTuple):
    """Return value for process_single_commit() function"""
    curr_commit_info: dict
    line_survival_info: Optional[dict] = None
    blamed_commits_data: Optional[dict] = None


def process_single_commit(repo: GitRepo,
                          project_name: str, gpt_commit: str,
                          process_stats: dict) -> GptCommitInfo:
    """Process single commit from DevGPT dataset, computing its survival info

    Using reverse blame for each of lines "added" by the patch of `gpt_commit`,
    find if some of them vanish at some point, or if they all survive to present
    day (until HEAD).  The result of reverse blame is added to the return
    value of this function, together with data about the commit it computed
    or extracted.

    This function returns GptCommitInfo named tuple, where first field,
    `curr_commit_info`, contains information about the processed commit,
    `line_survival_info` comes directly from repo.changes_survival(),
    and `blamed_commits_data` is information about blamed commits
    from repo.changes_survival() post-processed to be a dict with
    commits SHA-1 identifiers as keys, and commit data as values.

    The data in `curr_commit_info` has the following structure:
    - 'Sha': SHA-1 identifier of commit from DevGPT, to be used for join
      with the <commit_sharings_df> data
    - 'author_timestamp': Unix timestamp of when `Sha` commit was authored,
      should be same date as in `AuthorAt` field in DevGPT dataset
    - 'committer_timestamp': Unix timestamp of when `Sha` commit was
      committed to repo, should be the same date as `CommitAt` from DevGPT
    - 'n_parents': number of `Sha` commit parents, to distinguish merge
      and root commits
    - 'is_merged_HEAD': boolean value denoting whether `Sha` is merged
      into HEAD, or in other words whether HEAD codeline contains `Sha`
    - `error`: boolean value, whether there were errors while trying to
      compute reverse blame for the commit; if True all following fields
      will be missing (will be N/A in the dataframe)
    - 'change_lines_survived': number of lines in post-image that survived
      until present day (until HEAD)
    - 'change_lines_total': total number of lines in post-image of `Sha`
      ("added" lines in unified diff of `Sha` commit changes)
    - 'min_died_committer_timestamp': Unix timestamp of earliest date
      when first line of `Sha` post-image changes vanished; missing
      if all change lines suvived

    :param GitRepo repo: local, cloned `project_name` repository
    :param str project_name: name of the project (full name on GitHub)
        e.g. "sqlalchemy/sqlalchemy"
    :param str gpt_commit: commit from DevGPT dataset, for example one
        where its commit message includes ChatGPT sharing link
    :param dict process_stats: used to gather statistics about the process
    :return: data about the commit, and reverse blame info
    :rtype: GptCommitInfo
    """
    try:
        commit_metadata = repo.get_commit_metadata(gpt_commit)
    except subprocess.CalledProcessError as err:
        tqdm.write("ERROR when calling repo.get_commit_metadata(gpt_commit)")
        tqdm.write(f"{err=}")
        if hasattr(err, 'stderr') and err.stderr:
            tqdm.write(f"-----\n{err.stderr}\n-----")
        tqdm.write("Exiting...")
        sys.exit(ERROR_OTHER)

    augment_curr = {
        'Sha': gpt_commit,  # to be used for join
        'Sha_is_valid': True,
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
        return GptCommitInfo(augment_curr)

    # at this point we know that HEAD contains gpt_commit
    commits_from_HEAD = repo.count_commits(until_commit=gpt_commit)
    augment_curr['number_of_commits_from_HEAD'] = commits_from_HEAD

    try:
        commits_data, survival_info = repo.changes_survival(gpt_commit)
        augment_curr['error'] = False

    except subprocess.CalledProcessError as err:
        tqdm.write(f"{err=}")
        if hasattr(err, 'stderr') and err.stderr:
            tqdm.write(f"-----\n{err.stderr}\n-----")
        augment_curr['error'] = True
        process_stats['n_errors'] += 1
        return GptCommitInfo(augment_curr)

    except unidiff.UnidiffParseError as err:
        tqdm.write(f"Project '{project_name}', commit {gpt_commit}\n"
                   f"  at '{repo!s}'")
        tqdm.write(f"{err=}")
        augment_curr['error'] = True
        process_stats['n_errors'] += 1
        return GptCommitInfo(augment_curr)

    lines_survived, lines_total = changes_survival_perc(survival_info)
    augment_curr.update({
        'change_lines_survived': lines_survived,
        'change_lines_total': lines_total,
    })
    process_stats['lines_survived_sum'] += lines_survived
    process_stats['lines_total_sum'] += lines_total

    # TODO: extract this into separate function
    all_blame_commit_data = None
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

    return GptCommitInfo(curr_commit_info=augment_curr,
                         line_survival_info=survival_info,
                         blamed_commits_data=all_blame_commit_data)


def process_commit_changed_lines(repo: GitRepo,
                                 project_name: str, gpt_commit: str,
                                 survival_info: dict, blamed_commits_info: dict,
                                 process_stats: dict) -> List[dict]:
    """Compute survival for each change (post-image) line in given commit

    Using reverse blame for each of lines "added" by the patch of `gpt_commit`,
    find if they vanish at some point, or if they survive to present day
    (until HEAD).

    Fill in information about relevant commits related to reverse history
    of the line: last commit that line was seen in the same form as in
    `gpt_commit`, first commit that does not have the line in question
    (if there is such commit), and of course about the starting commit:
    `gpt_commit`.  The part of per-commit information that is needed for
    survival analysis is the timestamp (the author timestamp, and the
    committer timestamp).

    The output of 'git blame --reverse' uses the same nomenclature, the
    same terms, as ordinary 'git blame' - which is much more common, and
    which was created first.

    The returned data has the following structure (dicts on the list
    have the following keys):
    - 'RepoName': full name of repository, from DevGPT dataset, in which
      commit identified `Sha` can e found
    - 'Sha': SHA-1 identifier of commit from DevGPT, can be used for join
      (the same field name as in DevGPT dataset files)
    - 'Sha_filename': post-image name of file changed by `Sha` commit;
      only those files changed by `Sha` commits for which there is
      non-empty post-image are included in the "dataframe"
    - 'Sha_lineno': line number in `Sha_filename` at `Sha`
    - 'last_commit': SHA-1 identifier of the last commit (in chronological
      order starting from `Sha`) where given line still exists
    - 'last_filename': file in which the line is at `last_commit`,
      taking into account code movement and code copying, if 'git blame'
      was configured to consider those
    - 'last_lineno': line number in `last_filename` at `last_commit`
    - 'line': the contents of the line (present both in `Sha` and
      `last_commit`)
    - 'next_commit': SHA-1 identifier of the next commit after `last_commit`,
      i.e. commit that has `last_commit` as a parent, and which do not
      contain the line in question any longer; might be N/A if line
      survived until present (until HEAD)
    - 'next_filename': name of `last_filename` in `next_commit`,
      taking into account file renames if 'git blame' was configured
      to do so; it there is no `next_commit` it is None / N/A
    - 'Sha_author_timestamp', 'Sha_committer_timestamp': Unix timestamp
      of when `Sha` commit was authored, and when it was committed to repo
    - 'last_author_timestamp', 'last_committer_timestamp': as above,
      but for `last_commit` commit
    - 'next_author_timestamp', 'next_committer_timestamp': as above,
      but for `next_commit` commit, it it exists, else None / N/A

    :param GitRepo repo: local, cloned `project_name` repository
    :param str project_name: name of the project (full name on GitHub)
        e.g. "sqlalchemy/sqlalchemy"
    :param str gpt_commit: commit from DevGPT dataset, for example one
        where its commit message includes ChatGPT sharing link
    :param dict survival_info: reverse blame information about lines,
        generated by repo.changes_survival() method
    :param dict blamed_commits_info: information about blamed commits,
        gathered per-project from different reverse blame runs
    :param dict process_stats: used to gather statistics about the process
    :return: information about lines lifetime, in a format suitable for
        converting into dataframe with pd.DataFrame.from_records()
    :rtype: list[dict]
    """
    lines_data = []
    for change_path, change_lines_list in survival_info.items():
        for change_line_info in change_lines_list:
            if 'previous' in change_line_info:
                prev_commit, prev_file = change_line_info['previous'].split(' ', maxsplit=1)
                change_line_info['previous_commit'] = prev_commit
                change_line_info['previous_filename'] = prev_file

            for sha_key in 'Sha', 'commit', 'previous_commit':
                if sha_key == 'previous_commit' and sha_key not in change_line_info:
                    continue
                if sha_key == 'Sha':
                    commit_sha = gpt_commit
                else:
                    commit_sha = change_line_info[sha_key]
                # TODO: create a function or transformation to remove this code duplication
                if commit_sha in blamed_commits_info:
                    process_stats[f"{sha_key}_metadata_from_blame"] += 1
                    change_line_info[f"{sha_key}_author_timestamp"] \
                        = int(blamed_commits_info[commit_sha]['author-time'])
                    change_line_info[f"{sha_key}_committer_timestamp"] \
                        = int(blamed_commits_info[commit_sha]['committer-time'])
                else:
                    process_stats[f"{sha_key}_metadata_from_repo"] += 1
                    commit_metadata = repo.get_commit_metadata(commit_sha)
                    change_line_info[f"{sha_key}_author_timestamp"] \
                        = commit_metadata['author']['timestamp']
                    change_line_info[f"{sha_key}_committer_timestamp"] \
                        = commit_metadata['committer']['timestamp']
                    # use blamed_commits_info as cache
                    blamed_commits_info[commit_sha] = {
                        'author-time': commit_metadata['author']['timestamp'],
                        'committer-time': commit_metadata['committer']['timestamp'],
                    }

            lines_data.append({
                # the same field names as used in DevGPT dataset
                'RepoName': project_name,
                'Sha': gpt_commit,
                # field names renamed to be more meaningful
                'Sha_filename': change_path,
                'Sha_lineno': change_line_info['final'],
                'last_commit': change_line_info['commit'],
                'last_filename': change_line_info['original_filename'],
                'last_lineno': change_line_info['original'],
                'line': change_line_info['line'],
                'next_commit':
                    change_line_info.get('previous_commit', None),
                'next_filename':
                    change_line_info.get('previous_filename', None),
                'Sha_author_timestamp': change_line_info['Sha_author_timestamp'],
                'Sha_committer_timestamp': change_line_info['Sha_committer_timestamp'],
                'last_author_timestamp': change_line_info['commit_author_timestamp'],
                'last_committer_timestamp': change_line_info['commit_committer_timestamp'],
                'next_author_timestamp':
                    change_line_info.get('previous_commit_author_timestamp', None),
                'next_committer_timestamp':
                    change_line_info.get('previous_commit_committer_timestamp', None),
            })

    return lines_data


def process_commits(commits_df: pd.DataFrame, repo_clone_data: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Process commits in the `commits_df` dataframe, augmenting the data

    For each commit, compute how many of its post-image lines survived to current
    state of the project, and use it to augment per-commit data.

    For each of post-image change lines ("added" lines in unified diff), gather
    and extract information about its survival, using reverse git blame.

    :param pd.DataFrame commits_df: DataFrame with commits sharings from DevGPT
    :param dict repo_clone_data: information about cloned project's repositories
    :return: tuple of DataFrame augmented with changes survival information,
        and DataFrame with information about change lines survival
    :rtype: (pd.DataFrame, pd.DataFrame)

    TODO: replace tuple with named tuple for return value
    """
    commits_df.rename(columns={'ModelGPT3.5': 'ModelGPT3_5'}, inplace=True)

    repo_cache = {}
    total_stats = Counter({
        'n_skipped': 0,
        'n_missing_sha': 0,
        'n_missing_commit': 0,
        'n_errors': 0,
        'n_unmerged': 0,
        'lines_survived_sum': 0,
        'lines_total_sum': 0,
    })
    augment_data = []
    lines_data = []
    all_blamed_commits_info = defaultdict(dict)
    for row in tqdm(commits_df.itertuples(index=False, name='GptCommit'), desc='commit'):
        project_name = row.RepoName
        gpt_commit = row.Sha

        repository_path = reponame_to_repo_path(repo_clone_data, project_name)
        if repository_path is None:
            total_stats['n_skipped'] += 1
        if pd.isna(gpt_commit):
            total_stats['n_missing_sha'] += 1
        if repository_path is None or pd.isna(gpt_commit):
            continue

        repo = repo_cache.get(project_name, None)
        if repo is None:
            # call only if needed
            repo = GitRepo(repository_path)
            # remember for re-use
            repo_cache[project_name] = repo

        gpt_commit_is_valid = repo.is_valid_commit(gpt_commit)
        if not gpt_commit_is_valid:
            total_stats['n_missing_commit'] += 1
            augment_data.append({
                'Sha': gpt_commit,  # to be used for join
                'Sha_is_valid': False,
            })
            continue

        augment_curr, survival_info, blamed_commits_info \
            = process_single_commit(repo, project_name, gpt_commit, total_stats)
        augment_data.append(augment_curr)

        if blamed_commits_info is not None:
            all_blamed_commits_info[project_name].update(blamed_commits_info)

        if survival_info is not None:
            commit_lines_data = process_commit_changed_lines(repo, project_name, gpt_commit,
                                                             survival_info, all_blamed_commits_info[project_name],
                                                             total_stats)
            lines_data.extend(commit_lines_data)

    if total_stats['n_skipped'] > 0:
        print(f"Skipped {total_stats['n_skipped']} rows because repo was not cloned",
              file=sys.stderr)
    if total_stats['n_missing_sha'] > 0:
        print(f"Skipped {total_stats['n_missing_sha']} rows because of missing/NA 'Sha'",
              file=sys.stderr)
    if total_stats['n_errors'] > 0:
        print(f"Skipped {total_stats['n_errors']} rows because of an error",
              file=sys.stderr)
    if total_stats['n_missing_commit'] > 0:
        print(f"There were {total_stats['n_missing_commit']} commits not found in their repo",
              file=sys.stderr)
    if total_stats['n_unmerged'] > 0:
        print(f"There were {total_stats['n_unmerged']} commits not merged into HEAD",
              file=sys.stderr)

    print(f"Created {len(repo_cache)} of GitRepo objects", file=sys.stderr)
    print("Lines survival stats:", file=sys.stderr)
    if total_stats['lines_total_sum'] > 0:
        print("  "
              f"{total_stats['lines_survived_sum']} / {total_stats['lines_total_sum']} = "
              f"{100.0 * total_stats['lines_survived_sum'] / total_stats['lines_total_sum']:.2f}% lines survived; "
              f"{total_stats['lines_total_sum'] - total_stats['lines_survived_sum']} did not",
              file=sys.stderr)
    else:
        print(f"WARNING: captured {total_stats['lines_total_sum']} changed lines "
              f"and {total_stats['lines_survived_sum']} surviving lines",
              file=sys.stderr)

    # TODO: reduce code duplication
    print("  "
          f"orig commit metadata: {total_stats['Sha_metadata_from_blame']:6d} from blame, "
          f"{total_stats['Sha_metadata_from_repo']:5d} from repo = "
          f"{total_stats['Sha_metadata_from_blame'] + total_stats['Sha_metadata_from_repo']:6d} total",
          file=sys.stderr)
    print("  "
          f"last commit metadata: {total_stats['commit_metadata_from_blame']:6d} from blame, "
          f"{total_stats['commit_metadata_from_repo']:5d} from repo = "
          f"{total_stats['commit_metadata_from_blame'] + total_stats['commit_metadata_from_repo']:6d} total",
          file=sys.stderr)
    print("  "
          f"next commit metadata: {total_stats['previous_commit_metadata_from_blame']:6d} from blame, "
          f"{total_stats['previous_commit_metadata_from_repo']:5d} from repo = "
          f"{total_stats['previous_commit_metadata_from_blame'] + total_stats['previous_commit_metadata_from_repo']:6d} total",
          file=sys.stderr)
    print(" ",
          total_stats['Sha_metadata_from_repo'] +
          total_stats['commit_metadata_from_repo'] +
          total_stats['previous_commit_metadata_from_repo'],
          "from repo total")

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
