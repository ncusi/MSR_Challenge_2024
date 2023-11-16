import unittest

import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.tests import slow_test
from src.utils.git import GitRepo, DiffSide


class GitTestCase(unittest.TestCase):
    repo_path = 'test_utils_git-repo'
    default_branch = 'main'

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare Git repository for testing `utils.git` module

        Uses GitRepo.create_tag() for creating one of lightweight tags,
        so that test_list_tags() test also tests GitRepo.create_tag().
        """
        if Path(cls.repo_path).exists():
            # assume everything went all right, but tearDownClass() failed to remove directory
            # NOTE: usually it removed almost all files, but some were blocked
            print(f"Directory '{cls.repo_path}' exists, skipping re-creating the repo",
                  file=sys.stderr)
            return

        # initialize repository and  configure it
        subprocess.run(['git', 'init', cls.repo_path], check=True, stdout=subprocess.DEVNULL)  # noisy
        subprocess.run(['git', '-C', cls.repo_path, 'config', 'user.name', 'A U Thor'], check=True)
        subprocess.run(['git', '-C', cls.repo_path, 'config', 'user.email', 'author@example.com'], check=True)
        subprocess.run(['git', '-C', cls.repo_path, 'branch', '-m', cls.default_branch], check=True)

        # create files, and initial commit
        Path(cls.repo_path).joinpath('example_file').write_text('example')
        Path(cls.repo_path).joinpath('subdir').mkdir()
        Path(cls.repo_path).joinpath('subdir', 'subfile').write_text('subfile')
        subprocess.run(['git', '-C', cls.repo_path, 'add', '.'], check=True)
        subprocess.run(['git', '-C', cls.repo_path, 'commit', '-m', 'Initial commit'],
                       check=True, stdout=subprocess.DEVNULL)  # noisy
        subprocess.run(['git', '-C', cls.repo_path, 'tag', 'v1'])

        # add new file
        Path(cls.repo_path).joinpath('new_file').write_text(''.join([f"{i}\n" for i in range(10)]))
        subprocess.run(['git', '-C', cls.repo_path, 'add', 'new_file'], check=True)
        # change file
        Path(cls.repo_path).joinpath('subdir', 'subfile').write_text('subfile\nsubfile\n')
        # rename file
        subprocess.run(['git', '-C', cls.repo_path, 'mv',
                        'example_file', 'renamed_file'], check=True)
        # commit changes
        subprocess.run(['git', '-C', cls.repo_path, 'commit', '-a',
                        '-m', 'Change some files\n\n* one renamed file\n* one new file'],
                       env=dict(
                           # inherit environment variables
                           os.environ,
                           # configure git-commit behavior
                           # see https://git-scm.com/docs/git-commit#_commit_information
                           GIT_AUTHOR_NAME='Joe Random',
                           GIT_AUTHOR_EMAIL='joe@random.com',
                           GIT_AUTHOR_DATE='1693605193 -0600',
                       ),
                       check=True, stdout=subprocess.DEVNULL)  # noisy
        # tag for easy access
        GitRepo(cls.repo_path).create_tag('v2')

    @classmethod
    def tearDownClass(cls) -> None:
        """Remove Git repository created in `setUpClass`
        """
        if sys.platform != 'win32':
            shutil.rmtree(cls.repo_path)  # on MS Windows removing file can fail
            # PermissionError: [WinError 5] Permission denied: 'test_utils_git-repo\\.git\\objects\\3f\\20edf9b03502c9e73abdd0df93ec66461b8980'

    def setUp(self) -> None:
        self.repo = GitRepo(GitTestCase.repo_path)

    def test_list_files(self):
        """Test that GitRepo.list_files() returns correct list of files"""
        expected = [
            'example_file',
            'subdir/subfile'
        ]
        actual = self.repo.list_files('v1')
        self.assertCountEqual(actual, expected, "list of files in v1")

        expected = [
            'renamed_file',
            'subdir/subfile',
            'new_file'
        ]
        actual = self.repo.list_files()
        self.assertCountEqual(actual, expected, "list of files in HEAD")

    def test_list_changed_files(self):
        """Test that GitRepo.list_changed_files returns correct list of files"""
        expected = [
            'new_file',
            'subdir/subfile',
            'renamed_file',
        ]
        actual = self.repo.list_changed_files('v2')
        self.assertCountEqual(actual, expected, "list of changed files in v2 (post)")

        expected = [
            # no 'new_file'
            'subdir/subfile',
            'example_file',  # before rename
        ]
        actual = self.repo.list_changed_files('v2', side=DiffSide.PRE)
        self.assertCountEqual(actual, expected, "list of changed files in v2 (post)")

    def test_diff_file_status(self):
        """Test the result of GitRepo.diff_file_status"""
        expected = {
            (None, 'new_file'): 'A',  # file added in v2
            ('example_file', 'renamed_file'): 'R',  # file renamed in v2
            ('subdir/subfile',)*2: 'M',  # file modified in v2 without name change
        }
        actual = self.repo.diff_file_status('v2')
        self.assertCountEqual(actual, expected, "status of changed files in v2")

    def test_unidiff(self):
        """Test extracting data from GitRepo.unidiff"""
        patch = self.repo.unidiff()
        files = [f.path for f in patch]
        expected = [
            'new_file',  # file added in v2
            'renamed_file',  # file renamed in v2 from 'example_file'
            'subdir/subfile',  # file modified in v2 without name change
        ]
        self.assertCountEqual(files, expected, "extracted changed files match")
        diffstat = {
            f.path: (f.removed, f.added)
            for f in patch
        }
        self.assertEqual(diffstat['new_file'][0], 0, "new file has no deletions")
        self.assertEqual(diffstat['renamed_file'], (0, 0), "pure rename has no changes")
        # before: 'subfile', after: 'subfile\nsubfile\n'
        self.assertEqual(diffstat['subdir/subfile'], (1, 2), "changed file stats matches")

        expected_src = {
            # changed from 'subfile'
            1: 'subfile'
        }
        expected_dst = {
            # changes to 'subfile\nsubfile\n'
            1: 'subfile',
            2: 'subfile'
        }
        self.assertEqual(
            {
                line.source_line_no: line.value.strip()
                # there is only one hunk in changes in 'subdir/subfiles' file
                for line in patch[-1][0] if line.is_removed
            }, expected_src, "pre-image on last file matches"
        )
        self.assertEqual(
            {
                line.target_line_no: line.value.strip()
                # there is only one hunk in changes in 'subdir/subfiles' file
                for line in patch[-1][0] if line.is_added
            }, expected_dst, "post-image on last file matches"
        )

    def test_changed_lines_extents(self):
        actual = self.repo.changed_lines_extents()
        expected = {
            'new_file': [(1,10)],  # whole file added in v2
            'renamed_file': [],  # file renamed in v2 from 'example_file', no changes
            'subdir/subfile': [(1,2)],  # file modified in v2 without name change
        }
        self.assertEqual(actual, expected, "changed lines for post-image for changed files match")

    def test_file_contents(self):
        """Test that GitRepo.file_contents returns file contents as text"""
        expected = 'example'
        actual = self.repo.file_contents('v1', 'example_file')
        self.assertEqual(actual, expected, "contents of 'example_file' at v1")

        actual = self.repo.file_contents('v2', 'renamed_file')
        self.assertEqual(actual, expected, "contents of 'renamed_file' at v2")

    def test_open_file(self):
        """Test that GitRepo.open_file works as a context manager, returning binary file"""
        expected = b'example'
        with self.repo.open_file('v1', 'example_file') as fpb:
            actual = fpb.read()

        self.assertEqual(actual, expected, "streamed contents of 'example_file' at v1")

    @slow_test
    def test_checkout_revision(self):
        """Test that GitRepo.checkout_revision works correctly

        This is done by checking that list of files matches.  Comparison is done
        on two commits with different set of files.

        Should return to the starting position, which is tested.

        NOTE: this is relatively slow test, taking around 600 ms to run
        compared to less than 200 ms for the next slowest test.
        """
        beg_files = self.repo.list_files()  # at start
        beg_branch = self.repo.get_current_branch()  # starting branch or None

        v1_expected = self.repo.list_files('v1')  # list of files at v1
        self.repo.checkout_revision('v1')         # checkout v1, detached HEAD
        v1_actual = self.repo.list_files('HEAD')  # list of files at checkout = v1
        self.repo.checkout_revision(beg_branch or 'HEAD@{1}')   # back to the starting position

        end_files = self.repo.list_files()  # at end

        self.assertEqual(v1_actual, v1_expected, "checkout and list files at v1")
        self.assertEqual(beg_files, end_files, "no side effects of the test")

    def test_list_tags(self):
        """Test that GitRepo.list_tags list all tags"""
        expected = ['v1', 'v2']
        actual = self.repo.list_tags()

        self.assertEqual(actual, expected, "list of tags matches")

    def test_get_commit_metadata(self):
        commit_info = self.repo.get_commit_metadata('v2')

        self.assertEqual(commit_info['tree'], '5347fe7b8606e7a164ab5cd355ee5d86c99796c0',
                         "'tree' field did not change")
        self.assertEqual(commit_info['message'], 'Change some files\n\n* one renamed file\n* one new file\n',
                         "commit message matches")
        self.assertEqual(commit_info['author'], {
            'author': 'Joe Random <joe@random.com>',
            'email': 'joe@random.com',
            'name': 'Joe Random',
            'timestamp': 1693605193,
            'tz_info': '-0600'
        }, "author info matches")
        self.assertEqual(commit_info['committer']['committer'], 'A U Thor <author@example.com>',
                         "committer matches repository setup")

    def test_is_valid_commit(self):
        """Test that GitRepo.is_valid_commit returns correct answer

        Tested only with references and <rev>^ notation, as the test repository
        is not created in such way that SHA-1 identifiers are be stable; and
        currently GitRepo class lack method that would turn <commit-ish> or
        <object> into SHA-1 identifier.
        """
        # all are valid references that resolve to commit
        self.assertTrue(self.repo.is_valid_commit("HEAD"), "HEAD is valid")
        self.assertTrue(self.repo.is_valid_commit("v1"), "tag v1 is valid")
        self.assertTrue(self.repo.is_valid_commit("v2"), "tag v2 is valid")

        # all are not existing references
        self.assertFalse(self.repo.is_valid_commit("non_existent"), "no 'non_existent' reference")

        # <rev>^ notation within existing commit history
        self.assertTrue(self.repo.is_valid_commit("HEAD^"), "HEAD^ is valid")

        # <rev>^ notation leading outside existing commit history
        self.assertFalse(self.repo.is_valid_commit("HEAD^3"), "HEAD^3 is invalid")
        self.assertFalse(self.repo.is_valid_commit("HEAD~20"), "HEAD~20 is invalid")

    def test_get_current_branch(self):
        """Basic test of GitRepo.get_current_branch"""
        self.assertEqual(self.repo.get_current_branch(), self.default_branch,
                         f"current branch is default branch: '{self.default_branch}'")

    def test_resolve_symbolic_ref(self):
        """Test that GitRepo.resolve_symbolic_ref works correctly"""
        self.assertEqual(
            self.repo.resolve_symbolic_ref("HEAD"),
            f'refs/heads/{self.default_branch}',
            f"'HEAD' resolves to 'refs/heads/{self.default_branch}'"
        )
        self.assertIsNone(
            self.repo.resolve_symbolic_ref("v2"),
            "'v2' is not a symbolic ref"
        )

    def test_is_merged_into(self):
        """Test GitRepo.is_merged_into for various combinations of commit and into"""
        actual = self.repo.is_merged_into('v1')
        self.assertGreater(len(actual), 0, "'v1' is merged [into HEAD]")
        actual = self.repo.is_merged_into('v1', ['refs/heads/', 'refs/tags/'])
        expected = [
            f'refs/heads/{self.default_branch}',
            'refs/tags/v1',
            'refs/tags/v2',
        ]
        self.assertCountEqual(actual, expected, "'v1' is merged into HEAD, v1, v2")
        actual = self.repo.is_merged_into('v2', 'refs/tags/v1')
        self.assertFalse(actual, "'v2' is not merged into v1")


class GitClassMethodsTestCase(unittest.TestCase):
    def test_clone_repository(self):
        """Tests for GitRepo.clone_repository() class method

        NOTE: Calling with make_path_absolute=True was tested only manually;
        this test does not check that it works as intended.
        """
        variants = [
            {'kwargs': {}, 'expected_path': 'hellogitworld'},
            {'kwargs': {'directory': 'hello'}, 'expected_path': 'hello'},
            #{'kwargs': {'working_dir': 'data'}, 'expected_path': 'hellogitworld'},  # failed, at least on Windows
            {'kwargs': {'directory': 'data/hello'}, 'expected_path': str(Path('data/hello'))},
        ]
        # small example repository, so
        repo_url = 'https://github.com/githubtraining/hellogitworld'
        for variant in variants:
            with self.subTest(f"calling variant", variant=variant):
                repo = GitRepo.clone_repository(repo_url, **variant['kwargs'])
                self.assertEqual(variant['expected_path'], str(repo.repo))

                # attempt cleanup; you might need to do it manually
                # rm -rf src/tests/{,data/}hello{,gitworld}/
                try:
                    if repo:
                        shutil.rmtree(repo.repo)
                except PermissionError:
                    pass


if __name__ == '__main__':
    unittest.main()
