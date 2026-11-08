"""Minimal fail-closed patches to the verified upstream installers.

Two patches: use local verified official install.sh, and feed the official
installer a locally verified release archive. No protocol, database or
configuration logic is changed.
"""
from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise PatchError(f'{label}: ожидался ровно один участок кода, найдено: {count}. Выполнение остановлено.')
    return source.replace(old, new, 1)


def patch_kit(source: str) -> str:
    original = '  curl -fsSL --retry 3 -o "$tmp" "https://raw.githubusercontent.com/$XUI_REPO/$XUI_VERSION/install.sh"\n'
    replacement = (
        '  if [[ -n ${KIT_CUSTOM_OFFICIAL_INSTALLER:-} ]]; then\n'
        '    install -m 600 -- "$KIT_CUSTOM_OFFICIAL_INSTALLER" "$tmp"\n'
        '  else\n'
        + original +
        '  fi\n'
    )
    source = once(source, original, replacement, 'локальный установщик 3X-UI')
    insertion = '  spin_start "Устанавливаю панель 3X-UI"\n'
    with_patch = (
        '  if [[ -n ${KIT_CUSTOM_PREVERIFIED_ARCHIVE:-} ]]; then\n'
        '    python3 "${KIT_CUSTOM_PATCHER:?}" patch-official "$tmp" || die "Не удалось безопасно подготовить официальный установщик"\n'
        '  fi\n'
        + insertion
    )
    return once(source, insertion, with_patch, 'точка запуска официального установщика')


def patch_official(source: str) -> str:
    # This is the fixed-version installation branch, NOT the latest branch.
    original = (
        '        curl -fLR --retry 5 --retry-delay 3 --connect-timeout 15 '
        '--speed-limit 1 --speed-time 300 -o ${xui_folder}-linux-$(arch).tar.gz ${url}\n'
    )
    replacement = (
        '        if [[ -n ${KIT_CUSTOM_PREVERIFIED_ARCHIVE:-} ]]; then\n'
        '            cp -- "$KIT_CUSTOM_PREVERIFIED_ARCHIVE" "${xui_folder}-linux-$(arch).tar.gz"\n'
        '        else\n'
        + original +
        '        fi\n'
    )
    source = once(source, original, replacement, 'загрузка релиза')
    checksum = '        verify_release_checksum "${url}" "${xui_folder}-linux-$(arch).tar.gz"\n'
    verification = (
        '        if [[ -n ${KIT_CUSTOM_PREVERIFIED_ARCHIVE:-} ]]; then\n'
        '            local custom_actual\n'
        '            custom_actual=$(sha256sum "${xui_folder}-linux-$(arch).tar.gz" | awk \'{print $1}\')\n'
        '            if [[ "${custom_actual}" != "${KIT_CUSTOM_ARCHIVE_SHA256:?}" ]]; then\n'
        '                echo "3X-UI KIT Custom: неверная SHA256 архива после копирования" >&2\n'
        '                exit 1\n'
        '            fi\n'
        '        else\n'
        + checksum +
        '        fi\n'
    )
    return once(source, checksum, verification, 'проверка SHA256')


def main() -> int:
    p = argparse.ArgumentParser(description='Применить проверенный минимальный патч, строго с проверкой мест замены')
    p.add_argument('operation', choices=['patch-kit', 'patch-official'])
    p.add_argument('path', type=Path)
    args = p.parse_args()
    source = args.path.read_text(encoding='utf-8')
    patched = patch_kit(source) if args.operation == 'patch-kit' else patch_official(source)
    # Write via temp file, then rename; never leave a half-patched script.
    target = args.path.with_name(args.path.name + '.custom-new')
    try:
        target.write_text(patched, encoding='utf-8')
        target.chmod(args.path.stat().st_mode & 0o777)
        target.replace(args.path)
    finally:
        target.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
