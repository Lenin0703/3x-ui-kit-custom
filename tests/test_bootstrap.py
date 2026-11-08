"""Offline checks of the public one-line installer wrapper."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTests(unittest.TestCase):
    def invoke(self, *args: str, tamper: str = '') -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as td:
            fake_curl = Path(td) / 'curl'
            fake_curl.write_text('''#!/usr/bin/env python3
import os, pathlib, shutil, sys
args = sys.argv[1:]
dest = pathlib.Path(args[args.index('--output') + 1])
name = args[-1].split('/main/', 1)[1]
src = pathlib.Path(os.environ['BOOTSTRAP_TEST_REPO']) / name
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(src, dest)
if name == os.environ.get('BOOTSTRAP_TEST_TAMPER'):
    dest.write_text('UNTRUSTED SCRIPT\\n')
''')
            fake_curl.chmod(0o755)
            env = dict(os.environ)
            env['PATH'] = td + os.pathsep + env.get('PATH', '')
            env['BOOTSTRAP_TEST_REPO'] = str(ROOT)
            env['BOOTSTRAP_TEST_TAMPER'] = tamper
            return subprocess.run(['bash', str(ROOT / 'bootstrap.sh'), *args],
                                  env=env, capture_output=True, text=True,
                                  timeout=25)

    def test_versions_download_and_checksum(self) -> None:
        result = self.invoke('--versions')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('v3.9.0', result.stdout)
        self.assertIn('SHA256', result.stdout)

    def test_forged_download_is_rejected(self) -> None:
        result = self.invoke('--versions', tamper='kit_custom/cli.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256', result.stderr)
        self.assertNotIn('v3.9.0', result.stdout)

    def test_unknown_mode_rejected(self) -> None:
        result = self.invoke('--uninstall')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Неизвестный режим', result.stderr)


if __name__ == '__main__':
    unittest.main()
