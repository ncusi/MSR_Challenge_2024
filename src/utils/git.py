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
from contextlib import contextmanager
from enum import Enum
from os import PathLike
from pathlib import Path


class DiffSide(Enum):
    """Enum to be used for `side` parameter of `GitRepo.list_changed_files`"""
    PRE = 'pre'
    POST = 'post'
    A = 'pre'
    B = 'post'


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
    commit_lines = commit_text.split('\n')[:-1]  # remove trailing '\0'

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


class GitRepo:
    """Class representing Git repository, for performing operations on"""
    path_encoding = 'utf8'
    default_file_encoding = 'utf8'
    log_encoding = 'utf8'

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
    def clone_repository(cls, repository, directory=None, working_dir=None, make_path_absolute=False):
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
            and it is an absolute path.
        :type working_dir: str or PathLike[str] or Path or None
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
        args.extend([
            'clone', repository
        ])
        if directory is not None:
            args.append(str(directory))

        result = subprocess.run(args, capture_output=True)

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
        from calling 'git diff --file-status -r'.

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

    def is_valid_commit(self, commit):
        cmd = [
            'git', '-C', self.repo,
            'rev-parse', '--verify', '--end-of-options', str(commit)+'^{commit}'
        ]
        try:
            # emits SHA-1 identifier if commit is found in the repo; otherwise, errors out
            subprocess.run(cmd, capture_output=False, check=True)
        except subprocess.CalledProcessError:
            return False

        return True

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

    def is_merged_into(self, commit, ref_pattern='HEAD'):
        # support single patter or list of patterns
        # TODO: use variable number of parameters instead (?)
        if not isinstance(ref_pattern, list):
            ref_pattern = [ref_pattern]

        ref_pattern = filter(
            # filter out cases of detached HEAD, resolved to None (no branch)
            lambda x: x is not None,
            map(
                # resolve symbolic references, currently only 'HEAD' is resolved
                lambda x: x if x != 'HEAD' else self.resolve_symbolic_ref(x),
                ref_pattern
            )
        )

        cmd = [
            'git', '-C', self.repo,
            'for-each-ref', f'--contains={commit}',  # only list refs which contain the specified commit
            '--format=%(refname)',  # we only need list of refs that fulfill the condition mentioned above
            *ref_pattern
        ]
        process = subprocess.run(cmd, capture_output=True, check=True, text=True)
        return process.stdout.splitlines()

# end of file utils/git.py
