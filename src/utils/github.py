"""Module with various GitHub-related utilities

Those utilities can be split into those functions that operate on GitHub URLs
and use urllib.parse, and those that use GitHub API via PyGithub module.
"""
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

import github
from github import Auth, Github

from src.utils.functools import describe_func_call
from src.utils.strings import strip_suffixes

# TODO: read from environment variable or configuration file
GITHUB_API_TOKEN= "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"  # from jnareb


def is_github(url):
    """Does `url` looks like URL of GitHub repository?

    Note that currently SSH URL that lack schema part, for example
    git@github.com:ncusi/python_bug_localization.git, are not supported.
    But URLs should be HTTP(S) URL to public repositories
    for read-only access.

    :param url: URL to check
    :return: whether URL looks like to GitHub repository
    :rtype: bool
    """
    return urlparse(url).hostname.endswith('github.com')


def full_name_from_github_url(url):
    """Extract full repository name <owner>/<repo> from appropriate GitHub URL

    Assumes that URL has the following structure:
       https://github.com/{owner}/{repo}/<whatever>
                         ^^^^^^^^^^^^^^^ <- URL path

    Strips "/" and ".git" from the end of the {repo} name.

    Examples:
        >>> full_name_from_github_url('https://github.com/pallets/flask.git')
        'pallets/flask'

        >>> full_name_from_github_url('https://github.com/jakubroztocil/httpie/')
        'jakubroztocil/httpie'

    :param str url: GitHub repository URL (HTTP or HTTPS)
    :return: full name of GitHub repository, to be used in `get_github_repo()`
    :rtype: str or None
    """
    path_info = urlparse(url).path[1:]  # [1:] strips leading '/'
    if not path_info or '/' not in path_info:
        return None
    (owner, repo) = path_info.split('/')[:2]
    if not (owner and repo):
        return None
    return strip_suffixes(f"{owner}/{repo}", ["/", ".git"])


def get_Github():
    """Return GitHub API client from PyGithub, authenticated if available

    :return: GitHub client object to be used to access GitHub API
    :rtype: github.Github
    """
    # NOTE: it looks like there is no easy way to check if auth is valid,M
    # but to check if _later_ command like get_repo() fails with BadCredentialsException
    if GITHUB_API_TOKEN:
        auth = Auth.Token(GITHUB_API_TOKEN)
        g = Github(auth=auth)
    else:
        # use unauthenticated access
        g = Github()
    return g


def rate_limited_github_api(func):
    """Handle GitHub API rate limits and not-found errors in wrapped function

    If the wrapped function is hit with GitHub API rate limit, find when rate limit
    resets, and wait until that time.

    If object cannot be found via GitHub API, make wrapped function return `None`.

    In both cases print a warning.

    Example:
         >>> @rate_limited_github_api
         >>> def get_github_repo(g, project_name):
         >>>     return g.get_repo(project_name)
    """
    @wraps(func)
    def wrapper_rate_limited_github_api(*args, **kwargs):
        value = None
        # retry with wait if rate limit exceeded
        while value is None:
            try:
                value = func(*args, **kwargs)

            except github.RateLimitExceededException as err:
                # TODO: use tqdm.write() to avoid overlapping tqdm() progress bar,
                # or use logger, or make it configurable (optional decorator parameter)
                print("\nWARNING: GitHub API rate limit exceeded for",
                      describe_func_call(func, *args, **kwargs))
                print(f"........ ratelimit-limit: "
                      f"{err.headers['x-ratelimit-remaining']}/{err.headers['x-ratelimit-limit']} "
                      f"(resets at {err.headers['x-ratelimit-reset']} timestamp)")
                curr_time = time.time()
                # sleep for remaining time, but minimum for 1 second
                sleep_for = max(int(err.headers['x-ratelimit-reset']) - curr_time, 1)
                print(f"........ sleeping for {sleep_for} seconds")
                if sleep_for > 120:
                    # explain larger values of delay: how much to wait?
                    print(f"........ sleeping from {datetime.today()} "
                          f"until {datetime.today() + timedelta(seconds=sleep_for)}")
                time.sleep(sleep_for)

            except github.UnknownObjectException:
                print(f"\nWARNING: Result for {describe_func_call(func, *args, **kwargs)} "
                      "not found")

                return None

        return value

    return wrapper_rate_limited_github_api


@rate_limited_github_api
def get_github_repo(g, project_full_name):
    """Get GitHub repository with `project_full_name` on https://github.com

    This can be used to retrieve information about current state of the GitHub
    repository, like number of stars, and to retrieve commits, issues, and
    pull requests associated with given repository.

    Uses PyGithub to access GitHub API.  Does retry after appropriate wait time
    when encountering rate limits.

    :param g: GitHub client object, must support `get_repo` method
    :param str project_full_name: full name of GitHub project, e.g. 'ansible/ansible'
    :return: object representing GitHub repository, or None if not found
    :rtype: github.Repository.Repository or None
    """
    return g.get_repo(project_full_name)


@rate_limited_github_api
def get_github_commit(repo, commit_id):
    """Get commit with `commit_id` in given GitHub repository

    Uses PyGithub to access GitHub API.  Does retry after appropriate wait time
    when encountering rate limits.

    :param repo: object representing GitHub repository, must have `get_commit` method
    :param str commit_id: SHA-1 identifier of the commit
    :return: object representing GitHub commit, or None if not found
    :rtype: github.Commit.Commit or None
    """
    return repo.get_commit(sha=commit_id)  # github.Commit.Commit


@rate_limited_github_api
def get_github_issue(repo, issue_number):
    """Get GitHub issue with `issue_number` in given GitHub repository

    Uses PyGithub to access GitHub API.  Does retry after appropriate
    wait time when encountering rate limits.

    NOTE that returned object may represent **pull request** and not
    real GitHub issue.

    :param repo: object representing GitHub repository, must have `get_issue` method
    :param int issue_number: number identifying GitHub issue or pull request
    :return: object representing GitHub issue, or None if not found
    :rtype: github.Issue.Issue or None
    """
    return repo.get_issue(number=issue_number)  # github.Issue.Issue


@rate_limited_github_api
def get_github_pull_request(repo, pr_number):
    """Get GitHub pull request with `pr_number` in given GitHub repository

    Uses PyGithub to access GitHub API.  Does retry after appropriate
    wait time when encountering rate limits.

    NOTE that returned object may represent issue and not
    real GitHub pull request.

    :param repo: object representing GitHub repository, must have `get_pull` method
    :param int pr_number: number identifying GitHub pull request (or issue)
    :return: object representing GitHub pull request, or None if not found
    :rtype: github.PullRequest.PullRequest or None
    """
    return repo.get_pull(number=pr_number)


# Alternative would be to  create @cache decorator or use @functools.cache
# https://realpython.com/primer-on-python-decorators/#caching-return-values
# https://docs.python.org/3/library/functools.html#functools.lru_cache
# if the `cache` is not used otherwise (like for example to examine which
# GitHub repositories changed their name).
def get_github_repo_cached(g, full_project_name, cache_key, cache={}):
    """Calls `get_github_repo` caching results in `cache`

    Passing cache explicitly allows to examine GitHub repository objects later,
    for example to find all GitHub repositories that got renamed (accessing them
    on GitHub results in redirecting to GitHub repository with another full name,
    for example 'jakubroztocil/httpie' to 'httpie/cli', or 'huge-success/sanic'
    to 'sanic-org/sanic').

    Note that this function uses mutable for default value of `cache` argument
    knowingly and intentionally, to be used as anonymous cache.

    :param g: GitHub client object, must support `get_repo` method
    :param str full_project_name: full name of GitHub project, e.g. 'ansible/ansible'
    :param str cache_key: key used for GitHub repository object in `cache`, e.g. 'ansible'
    :param dict cache: data structure to cache GitHub repository object for reuse
    :return: object representing GitHub repository, or None if not found
    :rtype: github.Repository.Repository or None
    """
    # try to use cached github.Repository object
    repo = cache.get(cache_key, None)
    if repo is None:
        # call only if needed
        repo = get_github_repo(g, full_project_name)
    # remember for re-use, and analysis
    cache[cache_key] = repo

    return repo
