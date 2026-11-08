import unittest
from kit_custom.patcher import PatchError, patch_kit, patch_official

KIT_SNIPPET = '''install_xui() {
  curl -fsSL --retry 3 -o "$tmp" "https://raw.githubusercontent.com/$XUI_REPO/$XUI_VERSION/install.sh"
  [[ $(sha256sum "$tmp" | awk '{print $1}') == "$XUI_INSTALL_SHA256" ]] \\
    || die "hash mismatch"
  spin_start "Устанавливаю панель 3X-UI"
  bash "$tmp" "$XUI_VERSION"
}
'''
OFFICIAL_SNIPPET = '''  if [[ "$tag_version" == "latest" ]]; then
        curl -fLR --retry 5 --retry-delay 3 --connect-timeout 15 --speed-limit 1 --speed-time 300 -o ${xui_folder}-linux-$(arch).tar.gz https://github.com/foo
  else
        url="https://github.com/MHSanaei/3x-ui/releases/download/${tag_version}/x-ui-linux-$(arch).tar.gz"
        curl -fLR --retry 5 --retry-delay 3 --connect-timeout 15 --speed-limit 1 --speed-time 300 -o ${xui_folder}-linux-$(arch).tar.gz ${url}
        if [[ $? -ne 0 ]]; then
            exit 1
        fi
        verify_release_checksum "${url}" "${xui_folder}-linux-$(arch).tar.gz"
  fi
'''


class PatchTests(unittest.TestCase):
    def test_kit_patch_is_minimal_and_keeps_sha(self):
        patched = patch_kit(KIT_SNIPPET)
        self.assertIn('KIT_CUSTOM_OFFICIAL_INSTALLER', patched)
        self.assertIn('KIT_CUSTOM_PATCHER', patched)
        self.assertIn('XUI_INSTALL_SHA256', patched)
        self.assertEqual(patched.count('spin_start "Устанавливаю панель 3X-UI"'), 1)
        self.assertIn('bash "$tmp" "$XUI_VERSION"', patched)

    def test_official_patch_keeps_original_else_download(self):
        patched = patch_official(OFFICIAL_SNIPPET)
        self.assertIn('KIT_CUSTOM_PREVERIFIED_ARCHIVE', patched)
        self.assertIn('KIT_CUSTOM_ARCHIVE_SHA256', patched)
        self.assertIn('verify_release_checksum "${url}"', patched)
        self.assertIn('curl -fLR --retry 5', patched)
        self.assertEqual(patched.count('custom_actual=$(sha256sum'), 1)

    def test_unknown_upstream_change_must_fail_closed(self):
        for fn in (patch_official, patch_kit):
            with self.assertRaises(PatchError):
                fn('#!/bin/bash\necho no known anchors\n')

    def test_kit_duplicate_anchor_must_fail(self):
        with self.assertRaises(PatchError):
            patch_kit(KIT_SNIPPET + KIT_SNIPPET)

    def test_official_duplicate_anchor_must_fail(self):
        with self.assertRaises(PatchError):
            patch_official(OFFICIAL_SNIPPET + OFFICIAL_SNIPPET)


if __name__ == '__main__':
    unittest.main()
