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

        v1_expected = self.repo.list_files('v1')  # list of files at v1
        self.repo.checkout_revision('v1')         # checkout v1
        v1_actual = self.repo.list_files('HEAD')  # list of files at checkout = v1
        self.repo.checkout_revision('HEAD@{1}')   # back to the starting position

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
