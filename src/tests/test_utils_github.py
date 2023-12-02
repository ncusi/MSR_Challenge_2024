import os
import unittest

import fnc
import ghgql

from src.utils.github import is_github, full_name_from_github_url, GITHUB_API_TOKEN
from src.utils.github import (get_Github, get_github_repo, get_github_commit,
                              get_github_issue, get_github_pull_request,
                              get_github_repo_cached)

from src.tests import can_connect_to_url


class NoNetworkGitHubTestCase(unittest.TestCase):
    """Includes those tests of utils.github that do not require network"""
    def test_is_github(self):
        """Test utils.github.is_github(url) function"""
        github_urls = [
            'https://github.com/ansible/ansible',
            'https://github.com/pallets/flask.git',
            'https://github.com/jakubroztocil/httpie/',
            'https://github.com/matrix-org/synapse/pull/9240',
            'https://github.com/lxml/lxml/pull/316/commits/10ec1b4e9f93713513a3264ed6158af22492f270',
            'https://github.com/dogtagpki/pki/commit/50c23ec146ee9abf28c9de87a5f7787d495f0b72',
            'https://github.com/dogtagpki/pki/compare/v10.9.0-a2...v10.9.0-b1',
            'https://github.com/nltk/nltk/issues/2866',
        ]
        for url in github_urls:
            self.assertTrue(is_github(url), f"GitHub detected for {url}")

        other_urls = [
            'https://pypi.org/project/matrix-synapse/',
            'https://bugzilla.redhat.com/show_bug.cgi?id=1855273',
            'http://www.ubuntu.com/usn/USN-2531-1',
            'http://www.openwall.com/lists/oss-security/2015/03/15/1',
            'http://www.securitytracker.com/id/1038083',
            'https://bugs.launchpad.net/nova/+bug/1070539',
        ]
        for url in other_urls:
            self.assertFalse(is_github(url), f"no GitHub detected for {url}")

    def test_full_name_from_github_clone_url(self):
        """Test utils.github.full_name_from_github_url for GitHub clone URLs"""
        github_url_to_name = {
            'https://github.com/ansible/ansible': 'ansible/ansible',
            'https://github.com/pallets/flask.git': 'pallets/flask',
            'https://github.com/jakubroztocil/httpie/': 'jakubroztocil/httpie',
            'https://github.com/matrix-org/synapse.git/': 'matrix-org/synapse',
        }
        for (url, full_name) in github_url_to_name.items():
            self.assertEqual(full_name, full_name_from_github_url(url),
                             f"extracted '{full_name}' out of {url}")

    def test_full_name_from_any_github_url(self):
        """Test utils.github.full_name_from_github_url for any GitHub URLs"""
        github_url_to_name = {
            'https://github.com/ansible/ansible/issues/81546': 'ansible/ansible',
            'https://github.com/dogtagpki/pki/compare/v10.9.0-a2...v10.9.0-b1': 'dogtagpki/pki',
            'https://github.com/pallets/flask/commit/d67c47b81f4cbfda79f108a8ee4a183855127efb':
                'pallets/flask',
            'https://github.com/lxml/lxml/pull/316/commits/10ec1b4e9f93713513a3264ed6158af22492f270':
                'lxml/lxml',
            'https://github.com/matrix-org/synapse/pull/9240': 'matrix-org/synapse',
        }
        for (url, full_name) in github_url_to_name.items():
            self.assertEqual(full_name, full_name_from_github_url(url),
                             f"extracted '{full_name}' out of {url}")

        invalid_github_urls = [
            'https://github.com',
            'https://github.com/',
            'https://github.com/spotify',
            'https://github.com/spotify/',
        ]
        for url in invalid_github_urls:
            self.assertIsNone(full_name_from_github_url(url),
                              f"invalid GitHub URL for repo name extraction: {url}")


@unittest.skipIf('SKIP_SLOW_TESTS' in os.environ, 'Skipping slow networked tests')
@unittest.skipUnless(
    can_connect_to_url('https://api.github.com', timeout=0.1),
    'Skipping because of no access to https://api.github.com in 0.1 seconds'
)
class NetworkedGitHubTestCase(unittest.TestCase):
    """Includes those tests of `utils.github` that do require network access to https://github.com

    NOTE that these tests can fail for no fault of their own with timeout,
    with `requests.exceptions.ConnectTimeout` exception
    """
    g = None

    @classmethod
    def setUpClass(cls) -> None:
        """Set-up GitHub API client once for all tests"""
        cls.g = get_Github()

    def test_get_github_repo(self):
        """Test `utils.github.get_github_repo` (positive case only)"""
        cls = NetworkedGitHubTestCase
        if cls.g is None:
            self.skipTest("no access to GitHub API, cls.g is None")

        repo_name = 'PyGithub/PyGithub'
        repo = get_github_repo(cls.g, repo_name)

        self.assertEqual(repo_name, repo.full_name, f"full_name matches {repo_name}")
        self.assertCountEqual(
            ['pygithub', 'python', 'github', 'github-api'],
            repo.get_topics(),
            f"repository topics matches in {repo_name}"
        )

    def test_get_github_repo_cached(self):
        """Test `utils.github.get_github_repo_cached` (positive case only)"""
        cls = NetworkedGitHubTestCase
        if cls.g is None:
            self.skipTest("no access to GitHub API, cls.g is None")

        repo_name = 'jakubroztocil/httpie'

        with self.subTest("with explicit `cache` parameter"):
            repo_cache = {}
            repo = get_github_repo_cached(cls.g, repo_name, 'httpie', repo_cache)

            # there is entry in the cache
            self.assertIn('httpie', repo_cache, f"'httpie' in repo_cache={repo_cache}")
            self.assertEqual('httpie/cli', repo.full_name, f"correct full_name (after redirect)")
            self.assertEqual(repo, repo_cache['httpie'], f"object in cache matches result {repo}")

            # using cached result
            (rate_limit_remaining_beg, _) = cls.g.rate_limiting
            repo = get_github_repo_cached(cls.g, repo_name, 'httpie', repo_cache)
            (rate_limit_remaining_end, _) = cls.g.rate_limiting
            self.assertEqual(repo_cache['httpie'], repo, f"result is the same as object in cache {repo}")
            self.assertGreaterEqual(rate_limit_remaining_end, rate_limit_remaining_beg,
                                    "no change in rate limit, or limit increased")

        with self.subTest("without explicit `cache` parameter"):
            repo_1 = get_github_repo_cached(cls.g, repo_name, 'httpie')
            (rate_limit_remaining_beg, _) = cls.g.rate_limiting
            repo_2 = get_github_repo_cached(cls.g, repo_name, 'httpie')
            (rate_limit_remaining_end, _) = cls.g.rate_limiting

            self.assertEqual(repo_1, repo_2, "second access returns the same repo")
            self.assertGreaterEqual(rate_limit_remaining_end, rate_limit_remaining_beg,
                                    "no change in rate limit, or limit increased")

    def test_get_github_commit(self):
        """Test `utils.github.get_github_commit` (positive case only)"""
        import datetime

        cls = NetworkedGitHubTestCase
        if cls.g is None:
            self.skipTest("no access to GitHub API, cls.g is None")

        repo_name = 'PyGithub/PyGithub'
        commit_id = 'f82ad61c37b997fe00978e12cdd4d62d320db06a'
        repo = get_github_repo(cls.g, repo_name)
        commit = get_github_commit(repo, commit_id)

        self.assertEqual(commit_id, commit.sha, "commit id matches")
        self.assertEqual(
            datetime.datetime(2023, 6, 1, 8, 36, 31),
            commit.commit.author.date,
            "author date matches"
        )

    def test_get_github_issue(self):
        """Test `utils.github.get_github_issue` (positive case only)"""
        cls = NetworkedGitHubTestCase
        if cls.g is None:
            self.skipTest("no access to GitHub API, cls.g is None")

        repo_name = 'PyGithub/PyGithub'
        issue_no = 874
        repo = get_github_repo(cls.g, repo_name)
        issue = get_github_issue(repo, issue_no)

        self.assertEqual(issue_no, issue.number, f"issue number {issue_no} matches for {issue}")
        self.assertEqual(repo, issue.repository, f"repository matches for {issue}")
        self.assertEqual('PyGithub example usage', issue.title, f"issue title matches for {issue}")
        self.assertIn(issue.state, {'open', 'closed'}, f"valid issue state for {issue}")

    def test_get_github_pull_request(self):
        """Test `utils.github.get_github_pull_request` (positive case only)"""
        cls = NetworkedGitHubTestCase
        if cls.g is None:
            self.skipTest("no access to GitHub API, cls.g is None")

        repo_name = 'PyGithub/PyGithub'
        pr_no = 2393
        repo = get_github_repo(cls.g, repo_name)
        pr = get_github_pull_request(repo, pr_no)

        self.assertEqual(pr_no, pr.number, f"pull request number {pr_no} matches for {pr}")
        self.assertEqual('Fix broken urls in docstrings', pr.title, f"pull request title matches for {pr}")
        self.assertFalse(pr.draft, f"pull request {pr} is not draft")
        self.assertTrue(pr.merged, f"pull request {pr} is merged")


@unittest.skipIf('SKIP_SLOW_TESTS' in os.environ, 'Skipping slow networked tests')
@unittest.skipUnless(
    can_connect_to_url('https://api.github.com/graphql', timeout=0.1),
    'Skipping because of no access to https://api.github.com/graphql in 0.1 seconds'
)
class NetworkedGitHubGraphQLTestCase(unittest.TestCase):
    """Includes those tests of `src.utils.github` that use GraphQL queries"""
    ghapi = None

    @classmethod
    def setUpClass(cls) -> None:
        """Set-up GitHub GraphQL API client once for all tests"""
        if GITHUB_API_TOKEN:
            cls.ghapi = ghgql.GithubGraphQL(token=GITHUB_API_TOKEN)
        else:
            raise unittest.SkipTest("No GITHUB_API_TOKEN, required for GraphQL queries")

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear-down (close) GitHub GraphQL client after all tests"""
        if cls.ghapi is not None:
            cls.ghapi.close()

    def test_rate_limits(self):
        """Very simple test of basic GraphQL query, without any variables"""
        query = """
        query {
            rateLimit {
                limit
                remaining
                used
            }
        }
        """
        result = self.ghapi.query(query=query)
        data = result['data']['rateLimit']

        self.assertGreaterEqual(data['limit'], data['remaining'],
                                "'limit' >= 'remaining'")
        self.assertEqual(data['limit'], data['remaining'] + data['used'],
                         "'limit' == 'remaining' + 'used'")

    def test_retrieving_github_issue_closer(self):
        """Test query to find how GitHub issue was closed

        Based on https://stackoverflow.com/a/62294269/46058 response to
        https://stackoverflow.com/questions/62293896/github-api-how-to-know-if-an-issue-was-closed-by-a-fork-pull-request
        """
        query = """
        query ($owner: String!, $repo: String!, $issue: Int!) {
          repository(name: $repo, owner: $owner) {
            issue(number: $issue) {
              timelineItems(itemTypes: CLOSED_EVENT, last: 1) {
                nodes {
                  ... on ClosedEvent {
                    closer {
                      __typename
                    }
                  }
                }
              }
            }
          }
        }
        """
        test_data = [
            ('mui-org', 'material-ui', 19641, 'PullRequest'),  # Closing via pull request
            ('rubinius', 'rubinius', 1536, 'Commit'),  # Closing via commit message
            ('rubinius', 'rubinius', 3830, None),  # Closing via button
        ]
        for owner, repo, issue, expected in test_data:
            with self.subTest("issue closer matches", expected=expected):
                result = self.ghapi.query(query=query,
                                          variables={'owner': owner, 'repo': repo, 'issue': issue})
                has_closer = fnc.has('data.repository.issue.timelineItems.nodes[0].closer', result)
                typename = fnc.get('data.repository.issue.timelineItems.nodes[0].closer.__typename', result)
                self.assertTrue(has_closer, f"{owner}/{repo} has closer for #{issue}")
                self.assertEqual(typename, expected, f"{owner}/{repo} closer for #{issue} matches")


if __name__ == '__main__':
    unittest.main()
