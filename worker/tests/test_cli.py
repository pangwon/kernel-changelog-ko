import unittest
from unittest import mock

from kclog import cli


class NewReleasesTest(unittest.TestCase):
    def test_only_uncollected_since_releases(self):
        remote = ["v6.17", "v6.18", "v7.3", "v7.4", "v7.5"]
        with mock.patch.object(cli, "remote_releases", return_value=remote):
            # v6.17은 since(v6.18) 이전, v6.18·v7.3은 이미 수집됨
            self.assertEqual(cli.new_releases("ufs"), ["v7.4", "v7.5"])


if __name__ == "__main__":
    unittest.main()
