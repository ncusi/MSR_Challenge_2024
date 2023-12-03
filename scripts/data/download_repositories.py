#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage: {script_name} <dataset_path> <repositories_path> <output.json>

Saves all git repositories to specific directory, skips already present ones.
Creates <output.json> with information about cloned repositories, which can
be used in those later stage of pipeline that need access to Git repos.

Example:
    python scripts/data/download_repositories.py data/DevGPT/ \\
        data/repositories data/repositories_download_status.json
"""
import json
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.data.sharings import find_sharings_files, SharingsPaths
from src.utils.functools import timed
from src.utils.git import GitRepo

# constants
ERROR_ARGS = 1

PRETTY_PRINT_OUTPUT = True


def download_repository(repository, repositories_path, verbose=True):
    """Clones git repository `repository` into `repositories_path`

    Assumes existing directories are already cloned repositories,
    ignores all problems.

    :param str repository: string in format "owner/repository"
    :param Path repositories_path: path to directory where to download repositories
    :param bool verbose: whether to print non-error debugging-like information
    :return: dictionary with information about cloned repository, or None on failure
    :rtype: dict or None
    """
    project_name = repository.split('/')[1]
    repository_name = '_'.join(repository.split('/'))
    repository_url = 'https://github.com/' + repository + '.git'
    repository_dir = repositories_path / repository_name

    # check if repository was already cloned
    if repository_dir.is_dir():
        if verbose:
            print(f"Repository already exists: {repository_name}")

        return {
            'project': repository_name,
            'repository': repository,
            'repository_url': repository_url,
            'repository_path': str(repository_dir)
        }
    elif repository_dir.exists():
        print(f"Could not clone repository for {repository_name} "
              f"because '{repository_dir}' is in the way")
        return None

    # upgrade from legacy storage, where repository was stored under `project_name`
    legacy_dir = repositories_path / project_name
    if legacy_dir.is_symlink():
        # legacy dir already processed
        reference_dir = legacy_dir.readlink()
        if not reference_dir.is_absolute():
            reference_dir = repository_dir / reference_dir
        # there is possibility that this clone is not needed, if referenced URL == our URL
        repo = GitRepo.clone_repository(repository_url, repository_dir,
                                        reference_local_repository=reference_dir)
        if repo is None:
            print(f"Could not clone {repository_name} at {repository_url}\n"
                  f"using local '{reference_dir}' as reference")
            return None

        return {
            'project': repository_name,
            'repository': repository,
            'repository_url': repository_url,
            'repository_path': str(repo),
            'reference_repository_path': str(reference_dir),
        }
    if legacy_dir.is_dir():
        # upgrade legacy storage
        origin_url = GitRepo(legacy_dir).get_config('remote.origin.url')
        if repository_url.startswith(origin_url):  # take into account repo.git vs repo
            # at this point we know that `repository_dir` does not exist
            legacy_dir.replace(repository_dir)
            legacy_dir.symlink_to(repository_dir, target_is_directory=True)

            return {
                'project': repository_name,
                'repository': repository,
                'repository_url': repository_url,
                'repository_path': str(repository_dir),
                'alternative_path': str(legacy_dir),
            }
        else:
            # we can use it as reference, but need to dissociate
            # because the symlink can be removed
            repo = GitRepo.clone_repository(repository_url, repository_dir,
                                            reference_local_repository=legacy_dir,
                                            dissociate=True)
            if repo is None:
                print(f"Could not clone {repository_name} at {repository_url}\n"
                      f"using local '{legacy_dir}' as temporary reference")
                return None

            return {
                'project': repository_name,
                'repository': repository,
                'repository_url': repository_url,
                'repository_path': str(repo),
                'disassociated_reference_repository_path': str(legacy_dir),
            }

    try:
        repo = GitRepo.clone_repository(repository_url, repository_dir)
        if repo is None:
            print(f"Could not clone {repository_name} at {repository_url}")
            return None

        return {
            'project': repository_name,
            'repository': repository,
            'repository_url': repository_url,
            'repository_path': str(repo)
        }
    except Exception as ex:
        print(f"Could not clone repository for {repository_name} at {repository_url}: {ex}")
        return None


def download_repositories(repositories, repositories_path):
    """Clones all repositories into `repositories_path`

    :param list[str] repositories: list of repository names
    :param Path repositories_path: path to save data
    :return: information about successfully cloned repositories
    :rtype: list[dict]
    """
    result = []
    for repository in tqdm(repositories, desc='repositories'):
        repo_info = download_repository(repository, repositories_path,
                                        verbose=False)
        if repo_info is not None:
            result.append(repo_info)

    return result


def load_sharings(sharings_path):
    with open(sharings_path) as sharings_file:
        sharings = json.load(sharings_file)
    df = pd.DataFrame.from_records(sharings['Sources'])
    return df


def combine_sharings(sharings_paths):
    dfs = []
    for sharing_path in sharings_paths:
        dfs.append(load_sharings(sharing_path))
    df = pd.concat(dfs)
    return df


@timed
def main():
    # handle command line parameters
    # {script_name} <dataset_path> <repositories_path> <output.json>
    if len(sys.argv) != 3 + 1:  # sys.argv[0] is script name
        print(__doc__.format(script_name=sys.argv[0]))
        sys.exit(ERROR_ARGS)

    dataset_directory_path = Path(sys.argv[1])
    repositories_path = Path(sys.argv[2])
    output_file_path = Path(sys.argv[3])

    print(f"Reading data about dataset from '{dataset_directory_path}'...", file=sys.stderr)

    sharings_paths: SharingsPaths = find_sharings_files(dataset_directory_path)

    commit_df = combine_sharings(sharings_paths.commit_sharings_paths)
    issue_df = combine_sharings(sharings_paths.issue_sharings_paths)
    pr_df = combine_sharings(sharings_paths.pr_sharings_paths)
    file_df = combine_sharings(sharings_paths.file_sharings_paths)

    commit_repositories = list(commit_df['RepoName'].unique())
    issue_repositories = list(issue_df['RepoName'].unique())
    pr_repositories = list(pr_df['RepoName'].unique())
    file_repositories = list(file_df['RepoName'].unique())

    repositories = list(set(commit_repositories + issue_repositories + pr_repositories + file_repositories))

    print(f"Cloning {len(repositories)} repositories into '{repositories_path}'...", file=sys.stderr)
    cloned_data = download_repositories(repositories, repositories_path)

    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing output data to '{output_file_path}'...", file=sys.stderr)
    with open(output_file_path, 'w') as output_file:
        if PRETTY_PRINT_OUTPUT:
            json.dump(cloned_data, output_file, indent=2)
        else:
            json.dump(cloned_data, output_file)


if __name__ == '__main__':
    main()
