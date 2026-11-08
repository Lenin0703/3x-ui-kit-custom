"""Offline regression tests for 504 / 415 and SHA256 verification on proxies."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from kit_custom import cli, manifest


class Response:
    status = 200

    def __init__(self, data: bytes):
        self._fd = io.BytesIO(data)

    def read(self, size):
        return self._fd.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._fd.close()


class ReleaseFallbackTests(unittest.TestCase):
    def test_github_api_metadata_gets_json_accept(self):
        requested_headers = []

        def handler(req, timeout=0):
            requested_headers.append(req.get_header('Accept'))
            return Response(b'{}')

        with patch('kit_custom.cli.request.urlopen', side_effect=handler):
            self.assertEqual(cli.fetch_small('https://api.github.com/example',
                                             accept='application/vnd.github+json'), b'{}')
        self.assertEqual(requested_headers, ['application/vnd.github+json'])

    def test_install_command_no_longer_demands_magic_word(self):
        # An actual installation remains gated on Ubuntu, root, absence of x-ui,
        # and verified downloads. It must not consume an interactive confirmation.
        from unittest.mock import patch as mocked
        with mocked('kit_custom.cli.validate_environment', return_value='amd64'), \
             mocked('kit_custom.cli.fetch_archive', side_effect=cli.InstallError('simulated download failure')), \
             mocked('builtins.input', side_effect=AssertionError('unexpected confirmation prompt')):
            self.assertEqual(cli.main(['--install']), 1)

    def test_504_and_415_fallback_to_verified_proxy(self):
        payload = b'fake archive content; unit-test ONLY'
        digest = hashlib.sha256(payload).hexdigest()
        requested_urls = []

        def handler(req, timeout=0):
            url = req.full_url
            requested_urls.append(url)
            if 'ghfast.top' in url:
                return Response(payload)
            if 'releases/download' in url:
                raise HTTPError(url, 504, 'Gateway Timeout', {}, None)
            raise HTTPError(url, 415, 'Unsupported Media Type', {}, None)

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(manifest.PANEL_ARCHIVES, {'amd64': digest}), \
             patch('kit_custom.cli.request.urlopen', side_effect=handler), \
             patch('kit_custom.cli.time.sleep', return_value=None), \
             patch.dict('os.environ', {'KIT_CUSTOM_DISABLE_MIRRORS': '0'}):
            dest = Path(td) / 'panel.tar.gz'
            cli.fetch_archive(dest, 'amd64')
            self.assertEqual(dest.read_bytes(), payload)
        self.assertEqual(sum(u.startswith('https://github.com/') for u in requested_urls), 3)
        self.assertTrue(any(u.startswith('https://api.github.com/') for u in requested_urls))
        self.assertTrue(any(u.startswith('https://ghfast.top/') for u in requested_urls))

    def test_proxy_corruption_is_rejected_and_removed(self):
        payload = b'expected archive'
        requested_urls = []

        def handler(req, timeout=0):
            url = req.full_url
            requested_urls.append(url)
            if 'ghfast.top' in url or 'gh-proxy.com' in url:
                return Response(b'bad archive!')
            raise HTTPError(url, 504, 'Gateway Timeout', {}, None)

        with tempfile.TemporaryDirectory() as td, \
             patch.dict(manifest.PANEL_ARCHIVES, {'amd64': hashlib.sha256(payload).hexdigest()}), \
             patch('kit_custom.cli.request.urlopen', side_effect=handler), \
             patch('kit_custom.cli.time.sleep', return_value=None), \
             patch.dict('os.environ', {'KIT_CUSTOM_DISABLE_MIRRORS': '0'}):
            dest = Path(td) / 'panel.tar.gz'
            with self.assertRaises(cli.InstallError) as ctx:
                cli.fetch_archive(dest, 'amd64')
            self.assertFalse(dest.exists())
            self.assertIn('SHA256', str(ctx.exception))
        self.assertTrue(any('ghfast.top' in u for u in requested_urls))
        self.assertTrue(any('gh-proxy.com' in u for u in requested_urls))

    def test_opt_out_disables_third_party_mirrors(self):
        urls = []

        def handler(req, timeout=0):
            urls.append(req.full_url)
            raise HTTPError(req.full_url, 504, 'Gateway Timeout', {}, None)

        with tempfile.TemporaryDirectory() as td, \
             patch('kit_custom.cli.request.urlopen', side_effect=handler), \
             patch('kit_custom.cli.time.sleep', return_value=None), \
             patch.dict('os.environ', {'KIT_CUSTOM_DISABLE_MIRRORS': '1'}):
            with self.assertRaises(cli.InstallError):
                cli.fetch_archive(Path(td) / 'panel.tar.gz', 'amd64')
        self.assertFalse(any('ghfast.top' in u or 'gh-proxy.com' in u for u in urls))


if __name__ == '__main__':
    unittest.main()
