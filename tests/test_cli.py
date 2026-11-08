import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
from io import StringIO

from kit_custom import cli, manifest


class LauncherTests(unittest.TestCase):
    def test_git_blob_id_matches_git_algorithm(self):
        self.assertEqual(cli.git_blob_id(b'test'),
                         hashlib.sha1(b'blob 4\0test').hexdigest())

    def test_architecture(self):
        self.assertEqual(cli.arch_name('x86_64'), 'amd64')
        self.assertEqual(cli.arch_name('aarch64'), 'arm64')
        self.assertEqual(cli.arch_name('sparc'), '')

    def test_existing_path_detected(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / 'x-ui.db'
            fake.write_text('data')
            with patch('kit_custom.cli.shutil.which', return_value=None):
                self.assertEqual(cli.existing_installation((fake,)), [str(fake)])

    def test_bad_offline_archive_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'bad.tar.gz'
            dst = Path(d) / 'out.tar.gz'
            src.write_bytes(b'corrupted and not the original artifact')
            with self.assertRaises(cli.InstallError):
                cli.fetch_archive(dst, 'amd64', src)
            self.assertFalse(dst.exists())

    def test_verified_source_rejects_bad_data(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'untrusted.sh'
            src.write_text('echo malicious')
            target = Path(d) / 'verified.sh'
            with self.assertRaises(cli.InstallError):
                cli.fetch_verified_source('https://example.org/x', 'a'*40, target, offline=src)
            self.assertFalse(target.exists())

    def test_unsupported_version_fails_before_network(self):
        out = StringIO()
        with redirect_stderr(out):
            result = cli.main(['--install', '--yes', '--version', 'v3.11.0'])
        self.assertEqual(result, 1)
        self.assertIn('не прошла совместимость', out.getvalue())

    def test_existing_installation_guard_blocks_before_download(self):
        with patch('kit_custom.cli.read_os_release', return_value={'ID':'ubuntu','VERSION_ID':'24.04'}), \
             patch('kit_custom.cli.arch_name', return_value='amd64'), \
             patch('kit_custom.cli.os.geteuid', return_value=0), \
             patch('kit_custom.cli.shutil.which', return_value='/usr/bin/systemctl'), \
             patch('kit_custom.cli.existing_installation', return_value=['/etc/x-ui/x-ui.db']):
            with self.assertRaises(cli.InstallError):
                cli.validate_environment()

    def test_all_pinned_manifest_hashes_are_valid(self):
        for hash_ in list(manifest.PANEL_ARCHIVES.values()) + [manifest.PANEL_INSTALL_SHA256]:
            self.assertEqual(len(hash_), 64)
            int(hash_, 16)
        for item in list(manifest.KIT_FILES.values()) + [{'blob':manifest.PANEL_INSTALL_BLOB}]:
            self.assertEqual(len(item['blob']), 40)
            int(item['blob'], 16)

    def test_doctor_offline_does_not_download(self):
        with patch('kit_custom.cli.check_https', side_effect=AssertionError('unexpected network')), \
             patch('kit_custom.cli.existing_installation', return_value=[]), \
             patch('kit_custom.cli.shutil.which', return_value=None):
            cli.diagnostic(no_network=True)


if __name__ == '__main__':
    unittest.main()
