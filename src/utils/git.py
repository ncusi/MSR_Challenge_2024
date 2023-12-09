# -*- coding: utf-8-unix -*-
"""Utilities to get data out of git repositories.

This file defines a base class, `GitRepo`, which uses straight-up
calling git commands, and needs Git to be installed.

Usage:
------
Example usage:
  >>> from src.utils.git import GitRepo
  >>> files = GitRepo('path/to/git/repo').list_files('HEAD') # 'HEAD' is the default
  ...     ...

This implementation / backend retrieves data by calling `git` via
`subprocess.Popen`, and parsing the output.

WARNING: at the time this backend does not have error handling implemented;
it would simply return empty result, without any notification about the
error (like incorrect repository path, or incorrect commit)!!!
"""
import re
import subprocess
from collections import defaultdict
from contextlib import contextmanager
from enum import Enum
from operator import attrgetter
from os import PathLike
from pathlib import Path
from typing import overload, Literal, NamedTuple, Tuple

from unidiff.patch import Line as PatchLine
from unidiff import PatchSet


class DiffSide(Enum):
    """Enum to be used for `side` parameter of `GitRepo.list_changed_files`"""
    PRE = 'pre'
    POST = 'post'
    A = 'pre'
    B = 'post'


class StartLogFrom(Enum):
    """Enum to be used for special cases for starting point of 'git log'"""
    CURRENT = 'HEAD'
    HEAD = 'HEAD'  # alias
    ALL = '--all'


class AuthorStat(NamedTuple):
    """Parsed result of 'git shortlog -c -s'"""
    author: str  #: author name (commit authorship info)
    count: int = 0  #: number of commits per author


def _parse_authorship_info(authorship_line, field_name='author'):
    # trick from https://stackoverflow.com/a/279597/
    if not hasattr(_parse_authorship_info, 'regexp'):
        # runs only once
        _parse_authorship_info.regexp = re.compile(r'^((.*) <(.*)>) ([0-9]+) ([-+][0-9]{4})$')

    m = _parse_authorship_info.regexp.match(authorship_line)
    authorship_info = {
        field_name: m.group(1),
        'name': m.group(2),
        'email': m.group(3),
        'timestamp': int(m.group(4)),
        'tz_info': m.group(5),
    }

    return authorship_info


def _parse_commit_text(commit_text, with_parents_line=True, indented_body=True):
    # based on `parse_commit_text` from gitweb/gitweb.perl in git project
    # NOTE: cannot use .splitlines() here
    commit_lines = commit_text.split('\n')[:-1]  # remove trailing '\n'

    if not commit_lines:
        return None

    commit_data = {'parents': []}  # each commit has 0 or more parents

    if with_parents_line:
        parents_data = commit_lines.pop(0).split(' ')
        commit_data['id'] = parents_data[0]
        commit_data['parents'] = parents_data[1:]

    # commit metadata
    line_no = 0
    for (idx, line) in enumerate(commit_lines):
        if line == '':
            line_no = idx
            break

        if line.startswith('tree '):
            commit_data['tree'] = line[len('tree '):]
        if not with_parents_line and line.startswith('parent'):
            commit_data['parents'].append(line[len('parent '):])
        for field in ('author', 'committer'):
            if line.startswith(f'{field} '):
                commit_data[field] = _parse_authorship_info(line[len(f'{field} '):], field)

    # commit message
    commit_data['message'] = ''
    for line in commit_lines[line_no+1:]:
        if indented_body:
            line = line[4:]  # strip starting 4 spaces: 's/^    //'

        commit_data['message'] += line + '\n'

    return commit_data


def _parse_blame_porcelain(blame_text):
    # trick from https://stackoverflow.com/a/279597/
    if not hasattr(_parse_blame_porcelain, 'regexp'):
        # runs only once
        _parse_blame_porcelain.regexp = re.compile(r'^(?P<sha1>[0-9a-f]{40}) (?P<orig>[0-9]+) (?P<final>[0-9]+)')

    # https://git-scm.com/docs/git-blame#_the_porcelain_format
    blame_lines = blame_text.splitlines()
    if not blame_lines:
        # TODO: return NamedTuple
        return {}, []

    curr_commit = None
    curr_line = {}
    commits_data = {}
    line_data = []

    for line in blame_lines:
        if not line:  # empty line, shouldn't happen
            continue

        if match := _parse_blame_porcelain.regexp.match(line):
            curr_commit = match.group('sha1')
            curr_line = {
                'commit': curr_commit,
                'original': match.group('orig'),
                'final': match.group('final')
            }
            if curr_commit in commits_data:
                curr_line['original_filename'] = commits_data[curr_commit]['filename']
        elif line.startswith('\t'):  # TAB
            # the contents of the actual line
            curr_line['line'] = line[1:]  # remove leading TAB
            line_data.append(curr_line)
        else:
            # other header
            if curr_commit not in commits_data:
                commits_data[curr_commit] = {}
            try:
                # e.g. 'author A U Thor'
                key, value = line.split(' ', maxsplit=1)
            except ValueError:
                # e.g. 'boundary'
                key, value = (line, True)
            commits_data[curr_commit][key] = value
            # add 'filename' as 'original_filename' to line info
            if key == 'filename':
                curr_line['original_filename'] = value

    return commits_data, line_data


def parse_shortlog_count(shortlog_lines: list[str | bytes]) -> list[AuthorStat]:
    """Parse the result of GitRepo.list_authors_shortlog() method

    :param shortlog_lines: result of list_authors_shortlog()
    :type shortlog_lines: str or bytes
    :return: list of parsed statistics, number of commits per author
    :rtype: list[AuthorStat]
    """
    result = []
    for line in shortlog_lines:
        count, author = line.split('\t' if isinstance(line, str) else b'\t', maxsplit=1)
        count = int(count.strip())
        result.append(AuthorStat(author, count))

    return result


def select_core_authors(authors_stats: list[AuthorStat],
                        perc: float = 0.8) -> Tuple[list[AuthorStat], float]:
    """Select sorted list of core authors from `authors_list`

    Core authors are defined (like in World of Code) as those authors with
    the greatest contribution count whose contribution sum up to more than
    given `perc` fraction of contributions from all authors.  Usually
    number of contributions comes from 'git shortlog', and counts commits.

    This function returns a tuple.  First element is list of `AuthorStat`
    named tuples, sorted by `count` field in decreasing order, so that their
    contribution is minimal that covers `perc` fraction of all commits.
    If there is tie at the last element, all tied authors are included.
    Second element is actual fraction of all commits that selected authors'
    contributions covers.

    We have len(result[0]) <= len(authors_stats), and perc <= result[1].

    :param authors_stats: all authors and their contribution statistics,
        for example result of feeding the result of list_authors_shortlog()
        method fed to parse_shortlog_count() function
    :type authors_stats: list[AuthorStat]
    :param float perc: fraction threshold for considering author a core author,
        assumed to be 0.0 <= `perc` <= 1.0 (not checked!)
    :return: list of core authors, and cumulative fraction of contributions
        of returned authors
    :rtype: list[AuthorStat], float
    """
    authors_stats.sort(key=attrgetter('count'), reverse=True)
    total_commits = sum([auth.count
                         for auth in authors_stats])

    result = []
    idx = 0
    running_total = 0
    for idx, auth in enumerate(authors_stats):
        result.append(auth)
        running_total += auth.count
        if running_total > perc*total_commits:
            break

    # handle ex aequo situation (draw / tie)
    last_count = authors_stats[idx].count
    for auth in authors_stats[idx+1:]:
        if auth.count == last_count:
            running_total += auth.count
            result.append(auth)
        else:
            break

    return result, running_total/total_commits


def changes_survival_perc(lines_survival):
    lines_total = 0
    lines_survived = 0
    for _, lines_info in lines_survival.items():
        lines_total += len(lines_info)
        lines_survived += sum(1 for line_data in lines_info
                              if 'previous' not in line_data)

    return lines_survived, lines_total


class GitRepo:
    """Class representing Git repository, for performing operations on"""
    path_encoding = 'utf8'
    default_file_encoding = 'utf8'
    log_encoding = 'utf8'
    fallback_encoding = 'latin1'  # must be 8-bit encoding
    # see 346245a1bb ("hard-code the empty tree object", 2008-02-13)
    # https://github.com/git/git/commit/346245a1bb6272dd370ba2f7b9bf86d3df5fed9a
    # https://github.com/git/git/commit/e1ccd7e2b1cae8d7dab4686cddbd923fb6c46953
    empty_tree_sha1 = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

    def __init__(self, git_directory):
        # TODO: check that `git_directory` is a path to git repository
        # TODO: remember absolute path (it is safer)
        self.repo = Path(git_directory)

    def __repr__(self):
        class_name = type(self).__name__
        return f"{class_name}(git_directory={self.repo!r})"

    def __str__(self):
        return f"{self.repo!s}"

    @classmethod
    def clone_repository(cls, repository, directory=None,
                         working_dir=None,
                         reference_local_repository=None, dissociate=None,
                         make_path_absolute=False):
        """Clone a repository into a new directory, return cloned GitRepo

        If there is non-empty directory preventing from cloning the repository,
        the method assumes that it is because the repository was already cloned;
        in this case it returns that directory as `GitRepo`.

        :param repository: The (possibly remote) repository to clone from,
            usually a URL (ssh, git, http, or https) or a local path.
        :type repository: str or PathLike[str] or Path
        :param directory: The name of a new directory to clone into, optional.
            The "humanish" part of the source repository is used if `directory`
            is not provided (if it is `None`).
        :type directory:  str or PathLike[str] or Path or None
        :param working_dir: The directory where to run the
            `git-clone https://git-scm.com/docs/git-clone` operation;
            otherwise current working directory is used.  The value
            of this parameter does not matter if `directory` is provided,
            and it is an absolute path.  NOTE: tests fail for it!
        :type working_dir: str or PathLike[str] or Path or None
        :param reference_local_repository: Use `reference_local_repository`
            to avoid network transfer, and to reduce local storage costs
        :type reference_local_repository: str or PathLike[str] or Path or None
        :param dissociate: whether to dissociate with `reference_local_repository`,
            used only if `reference_local_repository` is not None
        :type dissociate: bool or None
        :param bool make_path_absolute: Ensure that returned `GitRepo` uses absolute path
        :return: Cloned repository as `GitRepo` if operation was successful,
            otherwise `None`.
        :type: GitRepo or None
        """
        def _to_repo_path(a_path: str):
            if make_path_absolute:
                if Path(a_path).is_absolute():
                    return a_path
                else:
                    return Path(working_dir or '').joinpath(a_path).absolute()

            return a_path

        args = ['git']
        if working_dir is not None:
            args.extend(['-C', str(working_dir)])
        if reference_local_repository:
            args.extend([
                'clone', f'--reference-if-able={reference_local_repository}'
            ])
            if dissociate:
                args.append('--dissociate')
            args.append(repository)
        else:
            args.extend([
                'clone', repository
            ])
        if directory is not None:
            args.append(str(directory))

        # https://serverfault.com/questions/544156/git-clone-fail-instead-of-prompting-for-credentials
        env = {
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_SSH_COMMAND': 'ssh -oBatchMode=yes',
            'GIT_ASKPASS': 'echo',
            'SSH_ASKPASS': 'echo',
            'GCM_INTERACTIVE': 'never',
        }

        result = subprocess.run(args, capture_output=True, env=env)

        # we are interested only in the directory where the repository was cloned into
        # that's why we are using GitRepo.path_encoding (instead of 'utf8', for example)

        if result.returncode == 128:
            # repository was already cloned
            for line in result.stderr.decode(GitRepo.path_encoding).splitlines():
                match = re.match(r"fatal: destination path '(.*)' already exists and is not an empty directory.", line)
                if match:
                    return GitRepo(_to_repo_path(match.group(1)))

            # could not find where repository is
            return None

        elif result.returncode != 0:
            # other error
            return None

        for line in result.stderr.decode(GitRepo.path_encoding).splitlines():
            match = re.match(r"Cloning into '(.*)'...", line)
            if match:
                return GitRepo(_to_repo_path(match.group(1)))

        return None

    def list_files(self, commit='HEAD'):
        """Retrieve list of files at given revision in a repository

        :param str commit:
            The commit for which to list all files.  Defaults to 'HEAD',
            that is the current commit
        :return: List of full path names of all files in the repository.
        :rtype: list[str]
        """
        args = [
            'git', '-C', str(self.repo), 'ls-tree',
            '-r', '--name-only', '--full-tree', '-z',
            commit
        ]
        # TODO: consider replacing with subprocess.run()
        process = subprocess.Popen(args, stdout=subprocess.PIPE)
        result = process.stdout.read()\
            .decode(GitRepo.path_encoding)\
            .split('\0')[:-1]
        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running
        # TODO: add error checking
        return result

    def list_changed_files(self, commit='HEAD', side=DiffSide.POST):
        """Retrieve list of files changed at given revision in repo

        NOTE: not tested for merge commits, especially "evil merges"
        with respect to file names.

        :param str commit:
            The commit for which to list changes.  Defaults to 'HEAD',
            that is the current commit.  The changes are relative to
            commit^, that is the previous commit (first parent of the
            given commit).

        :param DiffSide side:
            Whether to use names of files in post-image (after changes)
            with side=DiffSide.POST, or pre-image names (before changes)
            with side=DiffSide.PRE.  Renames are detected by Git.

        :return: full path names of files changed in `commit`.
        :rtype: list[str]
        """
        if side == DiffSide.PRE:
            changes_status = self.diff_file_status(commit)
            return [
                pre for (pre, _) in changes_status.keys()
                if pre is not None  # TODO: check how deleted files work with side=DiffSide.POST
            ]

        if side != DiffSide.POST:
            raise NotImplementedError(f"GitRepo.list_changed_files: unsupported side={side} parameter")

        # --no-commit-id is needed for 1-argument git-diff-tree
        cmd = [
            'git', '-C', self.repo, 'diff-tree', '-M',
            '-r', '--name-only', '--no-commit-id', '-z',
            commit
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        result = process.stdout.read() \
            .decode(GitRepo.path_encoding) \
            .split('\0')[:-1]
        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

        return result

    def diff_file_status(self, commit='HEAD', prev=None):
        """Retrieve status of file changes at given revision in repo

        It returns in a structured way information equivalent to the one
        from calling 'git diff --name-status -r'.

        Example output:
            {
                (None, 'added_file'): 'A',
                ('file_to_be_deleted', None): 'D',
                ('mode_changed', 'mode_changed'): 'M',
                ('modified', 'modified'): 'M',
                ('to_be_renamed', 'renamed'): 'R'
            }

        :param commit: The commit for which to list changes for.
            Defaults to 'HEAD', that is the current commit.
        :type: str
        :param prev: The commit for which to list changes from.
            If not set, then changes are relative to the parent of
            the `commit` parameter, which means 'commit^'.
        :type: str or None
        :return: Information about the status of each change.
            Returns a mapping (a dictionary), where the key is the pair (tuple)
            of pre-image and post-image pathname, and the value is a
            single letter denoting the status / type of the change.

            For new (added) files the pre-image path is `None`, and for deleted
            files the post-image path is `None`.

            Possible status letters are:
             - 'A': addition of a file,
             - 'C': copy of a file into a new one (not for all implementations),
             - 'D': deletion of a file,
             - 'M': modification of the contents or mode of a file,
             - 'R': renaming of a file,
             - 'T': change in the type of the file (untested).

        :rtype: dict[tuple[str,str],str]
        """
        if prev is None:
            # NOTE: this means first-parent changes for merge commits
            prev = commit + '^'

        cmd = [
            'git', '-C', self.repo, 'diff-tree', '--no-commit-id',
            # turn on renames [with '-M' or '-C'];
            # note that parsing is a bit easier without '-z', assuming that filenames are sane
            # increase inexact rename detection limit
            '--find-renames', '-l5000', '--name-status', '-r',
            prev, commit
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        lines = process.stdout.read().decode(GitRepo.path_encoding).splitlines()
        result = {}
        for line in lines:
            if line[0] == 'R' or line[0] == 'C':
                status, old, new = line.split("\t")
                result[(old, new)] = status[0]  # no similarity info
            else:
                status, path = line.split("\t")
                if status == 'A':
                    result[(None, path)] = status
                elif status == 'D':
                    result[(path, None)] = status
                else:
                    result[(path, path)] = status

        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

        return result

    @overload
    def unidiff(self, commit: str = ..., prev: str|None = ..., wrap: Literal[True] = ...) -> PatchSet:
        ...

    @overload
    def unidiff(self, commit: str = ..., prev: str|None = ..., *, wrap: Literal[False]) -> str|bytes:
        ...

    @overload
    def unidiff(self, commit: str = ..., prev: str|None = ..., wrap: bool = ...) -> str|bytes|PatchSet:
        ...

    def unidiff(self, commit='HEAD', prev=None, wrap=True):
        """Return unified diff between `commit` and `prev`

        If `prev` is None (which is the default), return diff between the
        `commit` and its first parent, or between the `commit` and the empty
        tree if `commit` does not have any parents (if it is a root commit).

        If `wrap` is True (which is the default), wrap the result in
        unidiff.PatchSet to make it easier to extract information from
        the diff.  Otherwise, return diff as plain text.

        :param str commit: later (second) of two commits to compare,
            defaults to 'HEAD', that is the current commit
        :param prev: earlier (first) of two commits to compare,
            defaults to None, which means comparing to parent of `commit`
        :type prev: str or None
        :param bool wrap: whether to wrap the result in PatchSet
        :return: the changes between two arbitrary commits,
            `prev` and `commit`
        :rtype: str or bytes or PatchSet
        """
        if prev is None:
            try:
                # NOTE: this means first-parent changes for merge commits
                return self.unidiff(commit=commit, prev=commit + '^', wrap=wrap)
            except subprocess.CalledProcessError:
                # commit^ does not exist for a root commits (for first commits)
                return self.unidiff(commit=commit, prev=self.empty_tree_sha1, wrap=wrap)

        cmd = [
            'git', '-C', self.repo,
            'diff', '--find-renames', '--find-copies', '--find-copies-harder',
            prev, commit
        ]
        process = subprocess.run(cmd,
                                 capture_output=True, check=True)
        try:
            diff_output = process.stdout.decode(self.default_file_encoding)
        except UnicodeDecodeError:
            # unidiff.PatchSet can only handle strings
            diff_output = process.stdout.decode(self.fallback_encoding)

        if wrap:
            return PatchSet(diff_output)
        else:
            return diff_output

    def changed_lines_extents(self, commit='HEAD', prev=None, side=DiffSide.POST):
        """List target line numbers of changed files as extents, for each changed file

        For each changed file that appears in `side` side of the diff between
        given commits, it returns list of `side` line numbers (e.g. target line
        numbers for post=DiffSide.POST).

        Line numbers are returned compressed as extents, that is list of
        tuples of start and end range.  For example, if target line numbers
        would be [1, 2, 3, 7, 10, 11], then their extent list would be
        [(1, 3), (7, 7), (10, 11)].

        To make it easier to mesh with other parts of computation, and to
        avoid reparsing diffs, also return parsed patch lines (diff lines).

        Uses :func:`GitRepo.unidiff` to parse git diff between `prev` and `commit`.

        Used by :func:`GitRepo.changes_survival`.

        :param str commit: later (second) of two commits to compare,
            defaults to 'HEAD', that is the current commit
        :param str or None prev: earlier (first) of two commits to compare,
            defaults to None, which means comparing to parent of `commit`
        :param DiffSide side: Whether to use names of files in post-image (after changes)
            with side=DiffSide.POST, or pre-image names (before changes)
            with side=DiffSide.PRE.  Renames are detected by Git.
            Defaults to DiffSide.POST, which is currently the only value
            supported.
        :return: two dicts, with changed files names as keys,
            first with information about change lines extents,
            second with parsed change lines (only for added lines)
        :rtype: (dict[str, list[tuple[int, int]]], dict[str, list[PatchLine]])
        """
        # TODO: implement also for DiffSide.PRE
        if side != DiffSide.POST:
            raise NotImplementedError(f"GitRepo.changed_lines_extents: unsupported side={side} parameter")

        patch = self.unidiff(commit=commit, prev=prev)
        file_ranges = {}
        file_diff_lines_added = defaultdict(list)
        for patched_file in patch:
            if patched_file.is_removed_file:  # no post-image for removed files
                continue
            line_ranges = []
            for hunk in patched_file:
                (range_beg, range_end) = (None, None)
                for line in hunk:
                    # we are interested only in ranges of added lines (in post-image)
                    if line.is_added:
                        if range_beg is None:  # first added line in line range
                            range_beg = line.target_line_no
                        range_end = line.target_line_no

                        file_diff_lines_added[patched_file.path].append(
                            line
                        )

                    else:  # deleted line, context line, or "No newline at end of file" line
                        if range_beg is not None:
                            line_ranges.append((range_beg, range_end))
                            range_beg = None

                # if diff ends with added line
                if range_beg is not None:
                    line_ranges.append((range_beg, range_end))

            file_ranges[patched_file.path] = line_ranges

        return file_ranges, file_diff_lines_added

    def _file_contents_process(self, commit, path):
        cmd = [
            'git', '-C', self.repo, 'show',  # or 'git', '-C', self.repo, 'cat-file', 'blob',
            # assumed that 'commit' is sane
            f'{commit}:{path}'
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)

        return process

    def file_contents(self, commit, path, encoding=None):
        """Retrieve contents of given file at given revision / tree

        :param str commit: The commit for which to return file contents.
        :param str path: Path to a file, relative to the top-level of the repository
        :param encoding: Encoding of the file (optional)
        :type: str or None
        :return: Contents of the file with given path at given revision
        :rtype: str
        """
        if encoding is None:
            encoding = GitRepo.default_file_encoding

        process = self._file_contents_process(commit, path)
        result = process.stdout.read().decode(encoding)
        # NOTE: does not handle errors correctly yet
        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

        return result

    @contextmanager
    def open_file(self, commit, path):
        """Open given file at given revision / tree as binary file

        Works as a context manager, like `pathlib.Path.open()`:
            >>> with GitRepo('/path/to/repo').open_file('v1', 'example_file') as fpb:
            ...     contents = fpb.read().decode('utf8')
            ...

        :param str commit: The commit for which to return file contents.
        :param str path: Path to a file, relative to the top-level of the repository
        :return: file object, opened in binary mode
        :rtype: io.BufferedReader
        """
        process = self._file_contents_process(commit, path)
        try:
            yield process.stdout
        finally:
            # NOTE: does not handle errors correctly yet
            process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
            process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

    def checkout_revision(self, commit):
        """Check out given commit in a given repository

        This would usually (and for some cases always) result in
        'detached HEAD' situation, that is HEAD reference pointing
        directly to a commit, and not being on any named branch.

        This function is called for its effects and does return nothing.

        :param str commit: The commit to check out in given repository.
        :rtype: None
        """
        cmd = [
            'git', '-C', self.repo, 'checkout', '-q', commit,
        ]
        # we are interested in effects of the command, not its output
        subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)

    def list_tags(self):
        """Retrieve list of all tags in the repository

        :return: List of all tags in the repository.
        :rtype: list[str]
        """
        cmd = ['git', '-C', self.repo, 'tag', '--list']
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        # NOTE: f.readlines() might be not the best solution
        tags = [line.decode(GitRepo.path_encoding).rstrip()
                for line in process.stdout.readlines()]

        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

        return tags

    def create_tag(self, tag_name, commit='HEAD'):
        """Create lightweight tag (refs/tags/* ref) to the given commit

        NOTE: does not support annotated tags for now; among others it
        would require deciding on tagger identity (at least for some
        backends).

        :param str tag_name: Name of tag to be created.
            Should follow `git check-ref-format` rules for name;
            see https://git-scm.com/docs/git-check-ref-format ;
            for example they cannot contain space ' ', tilde '~', caret '^',
            or colon ':'.  Those rules are NOT checked.
        :param str commit: Revision to be tagged.  Defaults to 'HEAD'.
        :rtype: None
        """
        cmd = [
            'git', '-C', self.repo, 'tag', tag_name, commit,
        ]
        # we are interested in effects of the command, not its output
        subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)

    def get_commit_metadata(self, commit='HEAD'):
        """Retrieve metadata about given commit

        :param str commit: The commit to examine.
            Defaults to 'HEAD', that is the current (most recent) commit.
        :return: Information about selected parts of commit metadata,
            the following format:

            {
                'id': 'f8ffd4067d1f1b902ae06c52db4867f57a424f38',
                'parents': ['fe4a622e5202cd990c8ec853d56e25922f263243'],
                'tree': '5347fe7b8606e7a164ab5cd355ee5d86c99796c0'
                'author': {
                    'author': 'A U Thor <author@example.com>',
                    'name': 'A U Thor',
                    'email': 'author@example.com',
                    'timestamp': 1112912053,
                    'tz_info': '-0600',
                },
                'committer': {
                    'committer': 'C O Mitter <committer@example.com>'
                    'name': 'C O Mitter',
                    'email': 'committer@example.com',
                    'timestamp': 1693598847,
                    'tz_info': '+0200',
                },
                'message': 'Commit summary\n\nOptional longer description\n',
            }

            TODO: use dataclass for result (for computed fields)

        :rtype: dict
        """
        # NOTE: using low level git 'plumbing' command means 'utf8' encoding is not assured
        # same as in `parse_commit` in gitweb/gitweb.perl in https://github.com/git/git
        # https://github.com/git/git/blob/3525f1dbc18ae36ca9c671e807d6aac2ac432600/gitweb/gitweb.perl#L3591C5-L3591C17
        cmd = [
            'git', '-C', self.repo, 'rev-list',
            '--parents', '--header', '--max-count=1', commit,
            '--'
        ]
        process = subprocess.run(cmd, capture_output=True, check=True)
        return _parse_commit_text(
            process.stdout.decode(GitRepo.log_encoding),
            # next parameters depend on the git command used
            with_parents_line=True, indented_body=True
        )

    def find_commit_by_timestamp(self, timestamp, start_commit='HEAD'):
        """Find first commit in repository older than given date

        :param timestamp: Date in UNIX epoch format, also known as timestamp format.
            Returned commit would be older than this date.
        :type: int or str
        :param str start_commit: The commit from which to start walking through commits,
            trying to find the one we want.  Defaults to 'HEAD'
        :return: Full SHA-1 identifier of found commit.

            WARNING: there is currently no support for error handling,
            among others for not finding any commit that fullfills
            the condition.  At least it is not tested.

        :rtype: str
        """
        cmd = [
            'git', '-C', self.repo, 'rev-list',
            f'--min-age={timestamp}', '-1',
            start_commit
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        # this should be US-ASCII hexadecimal identifier
        result = process.stdout.read().decode('latin-1').strip()
        # NOTE: does not handle errors correctly yet

        process.stdout.close()  # to avoid ResourceWarning: unclosed file <_io.BufferedReader name=3>
        process.wait()  # to avoid ResourceWarning: subprocess NNN is still running

        return result

    def to_oid(self, obj):
        cmd = [
            'git', '-C', self.repo,
            'rev-parse', '--verify', '--end-of-options', obj
        ]
        try:
            # emits SHA-1 identifier if object is found in the repo; otherwise, errors out
            process = subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError:
            return None

        # SHA-1 is ASCII only
        return process.stdout.decode('latin1').strip()

    def is_valid_commit(self, commit):
        return self.to_oid(str(commit)+'^{commit}') is not None

    def get_current_branch(self):
        cmd = [
            'git', '-C', self.repo,
            'symbolic-ref', '--quiet', '--short', 'HEAD'
        ]
        try:
            # Using '--quiet' means that the command would not issue an error message
            # but exit with non-zero status silently if HEAD is not a symbolic ref, but detached HEAD
            process = subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError:
            return None

        return process.stdout.strip()

    def resolve_symbolic_ref(self, ref='HEAD'):
        cmd = [
            'git', '-C', self.repo,
            'symbolic-ref', '--quiet', str(ref)
        ]
        try:
            # Using '--quiet' means that the command would not issue an error message
            # but exit with non-zero status silently if `ref` is not a symbolic ref
            process = subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError:
            return None

        return process.stdout.strip()

    def _to_refs_list(self, ref_pattern='HEAD'):
        # support single patter or list of patterns
        # TODO: use variable number of parameters instead (?)
        if not isinstance(ref_pattern, list):
            ref_pattern = [ref_pattern]

        return filter(
            # filter out cases of detached HEAD, resolved to None (no branch)
            lambda x: x is not None,
            map(
                # resolve symbolic references, currently only 'HEAD' is resolved
                lambda x: x if x != 'HEAD' else self.resolve_symbolic_ref(x),
                ref_pattern
            )
        )

    def check_merged_into(self, commit, ref_pattern='HEAD'):
        """List those refs among `ref_pattern` that contain given `commit`

        This method can be used to check if a given `commit` is merged into
        at least one ref matching `ref_pattern` using 'git for-each-ref --contains',
        see https://git-scm.com/docs/git-for-each-ref

        Return list of refs that contain given commit, or in other words
        list of refs that given commit is merged into.

        Note that symbolic refs, such as 'HEAD', are expanded.

        :param str commit: The commit to check if it is merged
        :param ref_pattern: <pattern>…, that is a pattern or list of patterns;
            check each ref that match against at least one patterns, either using
            fnmatch(3) or literally, in the latter case matching completely,
            or from the beginning up to a slash.  Defaults to 'HEAD'.
        :type ref_pattern: str or list[str]
        :return: list of refs matching `ref_pattern` that `commit` is merged into
            (that contain given `commit`)
        :rtype: list[str]
        """
        ref_pattern = self._to_refs_list(ref_pattern)

        cmd = [
            'git', '-C', self.repo,
            'for-each-ref', f'--contains={commit}',  # only list refs which contain the specified commit
            '--format=%(refname)',  # we only need list of refs that fulfill the condition mentioned above
            *ref_pattern
        ]
        process = subprocess.run(cmd, capture_output=True, check=True, text=True)
        return process.stdout.splitlines()

    def reverse_blame(self, commit, file, ref_pattern='HEAD', line_extents=None):
        ref_pattern = self._to_refs_list(ref_pattern)

        line_args = []
        if line_extents is not None:
            for beg, end in line_extents:
                line_args.extend(['-L', f'{beg},{end}'])

        cmd = [
            'git', '-C', self.repo,
            'blame', '--reverse', commit, '--porcelain',
            *line_args,
            file
        ]
        process = subprocess.run(cmd, capture_output=True, check=True)

        # TODO: extract this into a helper function
        try:
            output = process.stdout.decode(self.default_file_encoding)
        except UnicodeDecodeError:
            # not a valid utf-8, simply use bytes
            #output = process.stdout
            # _parse_blame_porcelain _currently_ can only handle strings
            output = process.stdout.decode(self.fallback_encoding)

        return _parse_blame_porcelain(
            output
        )

    def changes_survival(self, commit, prev=None,
                         addition_optimization=False):
        lines_survival = {}
        all_commits_data = {}
        diff_stat = {}

        # if we are doing the optimization, we need additiona information
        if addition_optimization:
            diff_stat = self.diff_file_status(commit, prev)

        changes_info, _ = self.changed_lines_extents(commit, prev, side=DiffSide.POST)
        for file_path, line_extents in changes_info.items():
            if not line_extents:
                # empty changes, for example pure rename
                continue

            # if file was added in commit, blame whole file
            if addition_optimization:
                if (None, file_path) in diff_stat:  # pure addition
                    line_extents = None  # blame whole file

            commits_data, lines_data = self.reverse_blame(commit, file_path,
                                                          line_extents=line_extents)
            for line_info in lines_data:
                if 'previous' in commits_data[line_info['commit']]:
                    line_info['previous'] = commits_data[line_info['commit']]['previous']

            lines_survival[file_path] = lines_data
            # NOTE: 'filename', 'boundary', and details of 'previous'
            # are different for different files, but common data could be extracted
            all_commits_data[file_path] = commits_data

        return all_commits_data, lines_survival

    def count_commits(self, start_from=StartLogFrom.CURRENT, until_commit=None,
                      first_parent=False):
        """Count number of commits in the repository

        Starting from `start_from`, count number of commits, stopping
        at `until_commit` if provided.

        If `first_parent` is set to True, makes Git follow only the first
        parent commit upon seeing a merge commit.

        :param start_from: where to start from to follow 'parent' links
        :type start_from: str or StartLogFrom
        :param until_commit: where to stop following 'parent' links;
            also ensures that we follow ancestry path to it, optional
        :type until_commit: str or None
        :param bool first_parent: follow only the first parent commit
            upon seeing a merge commit
        :return: number of commits
        :rtype: int
        """
        if hasattr(start_from, 'value'):
            start_from = start_from.value
        cmd = [
            'git', '-C', self.repo,
            'rev-list', '--count', str(start_from),
        ]
        if until_commit is not None:
            cmd.extend(['--not', until_commit, f'--ancestry-path={until_commit}', '--boundary'])
        if first_parent:
            cmd.append('--first-parent')
        process = subprocess.run(cmd, capture_output=True, check=True, encoding='utf8')

        return int(process.stdout)

    def list_authors_shortlog(self, start_from=StartLogFrom.ALL):
        """List all authors using git-shortlog

        Summarizes the history of the project by providing list of authors
        together with their commit counts.  Uses `git shortlog --summary`
        internally.

        :param start_from: where to start from to follow 'parent' links
        :type start_from: str or StartLogFrom
        :return: list of authors together with their commit count,
            in the 'SPACE* <count> TAB <author>' format
        :rtype: list[str|bytes]
        """
        if hasattr(start_from, 'value'):
            start_from = start_from.value
        elif start_from is None:
            start_from = '--all'
        cmd = [
            'git', '-C', self.repo,
            'shortlog',
            '--summary',  # Suppress commit description and provide a commit count summary only.
            '-n',  # Sort output according to the number of commits per author
            start_from,
        ]
        process = subprocess.run(cmd, capture_output=True, check=True)
        try:
            # try to return text
            return process.stdout.decode(GitRepo.log_encoding).splitlines()
        except UnicodeDecodeError:
            # if not possible, return bytes
            return process.stdout.splitlines()

    def list_core_authors(self, start_from=StartLogFrom.ALL, perc=0.8):
        """List core authors using git-shortlog, and their fraction of commits

        Get list of authors contributions via 'git-shortlog' with
        `list_authors_shortlog`, parse it with `parse_shortlog_count`,
        and select core authors from this list with `select_core_authors`.

        :param start_from: where to start from to follow 'parent' links
        :type start_from: str or StartLogFrom
        :param float perc: fraction threshold for considering author a core author,
            assumed to be 0.0 <= `perc` <= 1.0 (not checked!)
        :return: list of core authors, and cumulative fraction of contributions
            of returned authors
        :rtype: (list[AuthorStat], float)
        """
        return select_core_authors(
            parse_shortlog_count(self.list_authors_shortlog(start_from)),
            perc
        )

    def find_roots(self, start_from=StartLogFrom.CURRENT):
        """Find root commits (commits without parents), starting from `start_from`

        :param start_from: where to start from to follow 'parent' links
        :type start_from: str or StartLogFrom
        :return: list of root commits, as SHA-1
        :rtype: list[str]
        """
        if hasattr(start_from, 'value'):
            start_from = start_from.value
        elif start_from is None:
            start_from = 'HEAD'

        cmd = [
            'git', '-C', self.repo,
            'rev-list', '--max-parents=0',  # gives all root commits
            str(start_from),
        ]
        process = subprocess.run(cmd, capture_output=True, check=True, text=True)
        return process.stdout.splitlines()

    def get_config(self, name, value_type=None):
        """Query specific git config option

        If there is no Git configuration variable named `name`,
        then it returns None.

        :param str name: name of configuration option, for example
            'remote.origin.url' or 'user.name'
        :param value_type: name of git type to canonicalize outgoing value,
            see https://git-scm.com/docs/git-config#Documentation/git-config.txt---typelttypegt
            optional
        :type value_type: Literal['bool', 'int', 'bool-or-int', 'path', 'expiry-date', 'color'] or None
        :return: value of requested git configuration variable
        :rtype: str or None
        """
        cmd = [
            'git', '-C', self.repo,
            'config', str(name)
        ]
        if value_type is not None:
            cmd.append(f"--type={value_type}")

        try:
            process = subprocess.run(cmd, capture_output=True, check=True, text=True)
            return process.stdout.strip()
        except subprocess.CalledProcessError as err:
            # This command will fail with non-zero status upon error. Some exit codes are:
            # - The section or key is invalid (ret=1),
            # - ...
            if err.returncode == 1:
                return None
            else:
                raise err

# end of file utils/git.py
