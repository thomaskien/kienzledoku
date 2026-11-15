from pathlib import Path
import tempfile
import unittest

try:
    import packaging
except ImportError:
    raise unittest.SkipTest('packaging is needed for dependency-closure tests')

from installer.verify_windows_runtime import check


class WindowsDependencies(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.site = Path(temporary.name)

    def distribution(self, name, version='1.0', requirements=(), python=None):
        directory = self.site / f'{name}-{version}.dist-info'
        directory.mkdir()
        lines = ['Metadata-Version: 2.1', f'Name: {name}', f'Version: {version}']
        if python:
            lines.append('Requires-Python: ' + python)
        lines.extend('Requires-Dist: ' + item for item in requirements)
        (directory / 'METADATA').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def test_windows_only_requirement_is_not_hidden_by_host(self):
        self.distribution('humanfriendly', '10.0', ['pyreadline3; sys_platform == "win32" and python_version >= "3.8"'])
        with self.assertRaisesRegex(ValueError, 'pyreadline3.*fehlt'):
            check(self.site, '3.12.10')
        self.distribution('pyreadline3', '3.5.6')
        result = check(self.site, '3.12.10')
        self.assertTrue(result['dependency_closure'])
        self.assertEqual(result['distributions']['pyreadline3'], '3.5.6')

    def test_non_windows_requirements_and_unused_extras_are_ignored(self):
        self.distribution('synthetic', requirements=['not-installed; sys_platform == "darwin"', 'pytest; extra == "tests"'])
        self.assertTrue(check(self.site, '3.12.10')['dependency_closure'])

    def test_requested_transitive_extra_is_checked(self):
        self.distribution('application', requirements=['helper[console]'])
        self.distribution('helper', requirements=['readline-helper; extra == "console"'])
        with self.assertRaisesRegex(ValueError, 'readline-helper.*fehlt'):
            check(self.site, '3.12.10')

    def test_incompatible_version_and_python_are_rejected(self):
        self.distribution('application', requirements=['helper>=2'])
        self.distribution('helper', python='>=3.13')
        with self.assertRaises(ValueError) as result:
            check(self.site, '3.12.10')
        self.assertIn('passt nicht', str(result.exception))
        self.assertIn('Python 3.12.10', str(result.exception))

    def test_no_distribution_is_not_success(self):
        with self.assertRaisesRegex(ValueError, 'Keine Windows-Python-Pakete'):
            check(self.site, '3.12.10')


if __name__ == '__main__':
    unittest.main()
