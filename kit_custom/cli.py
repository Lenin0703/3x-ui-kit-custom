"""Preflight, verified download, compatibility gate and safe upstream launch."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib import error, request

from . import manifest
from .patcher import patch_kit, patch_official, PatchError

USER_AGENT = '3x-ui-kit-custom/0.1 (first-stage-install)' 
SOURCE_ROOT = Path(__file__).resolve().parent.parent
EXISTING_PATHS = (
    '/etc/x-ui', '/usr/local/x-ui', '/usr/bin/x-ui', '/root/3x-ui.txt',
    '/etc/kit', '/etc/kit-sub', '/usr/local/bin/kit',
    '/etc/systemd/system/x-ui.service', '/etc/systemd/system/kit-sub.service',
    '/var/lib/x-ui',
)


class InstallError(RuntimeError):
    pass


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def sha256_file(filename: Path) -> str:
    h = hashlib.sha256()
    with filename.open('rb') as fd:
        for part in iter(lambda: fd.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def arch_name(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    return {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine, '')


def read_os_release(filename: str = '/etc/os-release') -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path(filename).read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                result[k] = v.strip('"\'')
    except OSError:
        pass
    return result


def existing_installation(paths=EXISTING_PATHS) -> list[str]:
    found = [str(p) for p in map(Path, paths) if p.exists() or p.is_symlink()]
    # systemctl is read-only here. A service may exist outside the usual path.
    if shutil.which('systemctl'):
        result = subprocess.run(['systemctl', 'is-enabled', 'x-ui'], capture_output=True, text=True, check=False)
        if result.returncode == 0 and 'systemd: x-ui enabled' not in found:
            found.append('systemd: x-ui enabled')
        result = subprocess.run(['systemctl', 'is-active', 'x-ui'], capture_output=True, text=True, check=False)
        if result.returncode == 0 and 'systemd: x-ui active' not in found:
            found.append('systemd: x-ui active')
    return found


def verified_bytes(data: bytes, sha1: str | None = None, sha256: str | None = None) -> None:
    if sha1 and git_blob_id(data) != sha1:
        raise InstallError('SHA Git Blob не совпала с закреплённым исходником; файл отвергнут.')
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise InstallError('SHA256 исходного файла не совпала; файл отвергнут.')


def fetch_small(url: str, timeout: int = 18) -> bytes:
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/octet-stream'})
    with request.urlopen(req, timeout=timeout) as res:
        if res.status != 200:
            raise InstallError(f'HTTP {res.status}: {url}')
        data = res.read(2_000_000 + 1)
        if len(data) > 2_000_000:
            raise InstallError('Слишком большой исходный файл: отклонено')
        return data


def fetch_verified_source(url: str, blob: str, destination: Path, offline: Path | None = None,
                          sha256: str | None = None, github_repo: str | None = None) -> None:
    if offline:
        source = offline
        if not source.is_file():
            raise InstallError(f'Отсутствует локальный файл: {source}')
        data = source.read_bytes()
        verified_bytes(data, blob, sha256)
    else:
        exceptions = []
        data = None
        for attempt in range(3):
            try:
                candidate = fetch_small(url)
                verified_bytes(candidate, blob, sha256)
                data = candidate
                break
            except (OSError, error.URLError, InstallError) as exc:
                exceptions.append(str(exc))
                if attempt < 2:
                    time.sleep(attempt + 1)
        if data is None and github_repo:
            # Second *official* source: GitHub Git Blobs API.
            api = f'https://api.github.com/repos/{github_repo}/git/blobs/{blob}'
            try:
                metadata = json.loads(fetch_small(api))
                candidate = base64.b64decode(metadata['content'], validate=False)
                verified_bytes(candidate, blob, sha256)
                data = candidate
            except (OSError, ValueError, KeyError, error.URLError, InstallError) as exc:
                exceptions.append('GitHub API: ' + str(exc))
        if data is None:
            raise InstallError('Не удалось получить подтверждённый исходник ' + url + '\n' + '\n'.join(exceptions[-3:]))
    destination.write_bytes(data)
    destination.chmod(0o600)


def fetch_archive_url(url: str, destination: Path, expected: str) -> None:
    req = request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/octet-stream'})
    h = hashlib.sha256()
    total = 0
    with request.urlopen(req, timeout=40) as res, destination.open('wb') as output:
        if res.status != 200:
            raise InstallError(f'HTTP {res.status} ({url})')
        while True:
            chunk = res.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 256 * 1024 * 1024:
                raise InstallError('Архив неожиданно большой: отклонён')
            h.update(chunk)
            output.write(chunk)
    if h.hexdigest() != expected:
        raise InstallError('Архив не совпадает с закреплённой SHA256 ' +
                           f'({total} байт; источник {url}); не запускаю')


def fetch_archive(dest: Path, arch: str, local: Path | None = None) -> None:
    sha = manifest.PANEL_ARCHIVES[arch]
    if local is not None:
        if not local.is_file():
            raise InstallError(f'Файл архива не найден: {local}')
        if sha256_file(local) != sha:
            raise InstallError('Переданный локальный архив имеет неправильную SHA256. Никаких изменений не внесено.')
        shutil.copyfile(local, dest)
        dest.chmod(0o600)
        # Verify a second time AFTER copying; a symlink/local source can change
        # between the first check and the copy (TOCTOU).
        if sha256_file(dest) != sha:
            dest.unlink(missing_ok=True)
            raise InstallError('Контрольная сумма локального архива изменилась при копировании.')
        return
    name = f'x-ui-linux-{arch}.tar.gz'
    release_url = f'https://github.com/MHSanaei/3x-ui/releases/download/{manifest.PANEL_VERSION}/{name}'
    errors: list[str] = []
    # The release download is preferable; fall back ONLY to the official GitHub API.
    for attempt in range(3):
        try:
            fetch_archive_url(release_url, dest, sha)
            dest.chmod(0o600)
            return
        except (OSError, error.URLError, InstallError) as exc:
            errors.append('releases/download: ' + str(exc))
            dest.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(attempt + 1)
    try:
        meta_url = f'https://api.github.com/repos/MHSanaei/3x-ui/releases/tags/{manifest.PANEL_VERSION}'
        metadata = json.loads(fetch_small(meta_url))
        assets = [asset for asset in metadata.get('assets', []) if asset.get('name') == name]
        if len(assets) != 1:
            raise InstallError('В официальном релизе GitHub архив не найден.')
        asset = assets[0]
        if asset.get('digest') not in (None, 'sha256:' + sha):
            raise InstallError('Официальный digest релиза отличается от закреплённого значения.')
        api_url = f'https://api.github.com/repos/MHSanaei/3x-ui/releases/assets/{asset["id"]}'
        fetch_archive_url(api_url, dest, sha)
        dest.chmod(0o600)
        return
    except (OSError, error.URLError, KeyError, ValueError, InstallError) as exc:
        errors.append('GitHub API: ' + str(exc))
        dest.unlink(missing_ok=True)
    raise InstallError('Не удалось скачать официальный архив релиза.\n' + '\n'.join(errors[-4:]) +
                       '\nМожно скачать x-ui-linux-' + arch + '.tar.gz на другом компьютере из ' +
                       'https://github.com/MHSanaei/3x-ui/releases/tag/v3.9.0 ' +
                       'и выполнить --install --archive /путь/к/архиву')


def check_https(url: str) -> str:
    try:
        req = request.Request(url, headers={'User-Agent': USER_AGENT}, method='HEAD')
        with request.urlopen(req, timeout=9) as res:
            return f'HTTP {res.status} ({res.geturl()[:90]})'
    except error.HTTPError as exc:
        return f'HTTP {exc.code} (сервер отвечает; доступ может быть ограничен)'
    except (OSError, error.URLError) as exc:
        return f'ошибка сети/TLS: {exc}'


def diagnostic(no_network: bool = False) -> None:
    os_info = read_os_release()
    arch = arch_name()
    print('3X-UI KIT Custom — диагностика без изменения файлов')
    print(f'Система: {os_info.get("PRETTY_NAME", "неизвестна")}')
    print(f'Архитектура: {platform.machine()} -> {arch or "не поддерживается"}')
    found = existing_installation()
    print('Существующая установка:', ', '.join(found) if found else 'не обнаружена')
    if found:
        print('ЗАЩИТА: режим установки будет заблокирован; старые настройки не меняются.')
    for f in ('/etc/x-ui/x-ui.db', '/root/cert/ip/fullchain.pem', '/etc/letsencrypt/live'):
        p = Path(f)
        if p.exists():
            print('Найден:', f)
            if p.is_file() and p.suffix == '.pem' and shutil.which('openssl'):
                try:
                    details = subprocess.run(
                        ['openssl', 'x509', '-in', str(p), '-noout', '-enddate'],
                        capture_output=True, text=True, timeout=8, check=False,
                    )
                    print('  Срок сертификата:', details.stdout.strip() if details.returncode == 0
                          else 'не удалось прочитать сертификат')
                except (OSError, subprocess.TimeoutExpired):
                    print('  Проверка сертификата недоступна')
    if shutil.which('ss'):
        proc = subprocess.run(['ss', '-lntup'], capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            lines = proc.stdout.splitlines()
            interesting = [x for x in lines[1:] if re.search(r':(?:22|80|443|8388)(?:\s|$)', x)]
            print('Открытые локальные сокеты (22/80/443/8388):')
            for line in interesting[:20]:
                print(' ', line)
    if no_network:
        print('Проверка сети пропущена (--offline).')
        return
    urls = {
        'GitHub': 'https://github.com',
        'GitHub API': 'https://api.github.com',
        'GitHub raw': 'https://raw.githubusercontent.com',
        'Архив 3X-UI v3.9.0':
            f'https://github.com/MHSanaei/3x-ui/releases/download/v3.9.0/x-ui-linux-{arch or "amd64"}.tar.gz',
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        checks = dict(zip(urls.keys(), executor.map(check_https, urls.values())))
    for label, result in checks.items():
        print(f'{label}: {result}')
    print('Проверка HEAD не гарантирует, что GET полного архива сработает; установка проверяет SHA256.')


def validate_environment() -> str:
    current = read_os_release()
    if current.get('ID') != 'ubuntu' or current.get('VERSION_ID') != '24.04':
        raise InstallError('Этап 1 поддерживает только Ubuntu 24.04 LTS; установка не выполнялась.')
    arch = arch_name()
    if arch not in manifest.PANEL_ARCHIVES:
        raise InstallError('Архитектура не проверена; установка заблокирована.')
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise InstallError('Запустите --install от root на Ubuntu 24.04 LTS.')
    if not shutil.which('systemctl'):
        raise InstallError('Не найден systemd; установка заблокирована.')
    found = existing_installation()
    if found:
        raise InstallError('Уже обнаружены файлы или служба 3X-UI: ' + ', '.join(found) +
                           '.\nНичего не изменено. Используйте --diagnose. ' +
                           'Обновление/восстановление существующей панели будет отдельной проверенной операцией.')
    return arch


def install(args: argparse.Namespace) -> int:
    if args.version != manifest.PANEL_VERSION:
        raise InstallError(f'Версия {args.version} ещё не прошла совместимость с KIT. Разрешена {manifest.PANEL_VERSION}.')
    if args.forward and args.forward[0] != '--':
        raise InstallError('Параметры оригинального KIT передавайте после отдельного --.')
    original_args = args.forward[1:] if args.forward else []
    if any(a == '--restore' or a.startswith('--restore=') for a in original_args):
        raise InstallError('Восстановление из резервной копии в первом этапе отключено.')
    arch = validate_environment()  # before any directory/file creation or download
    if not args.yes:
        try:
            answer = input('Чистая Ubuntu подтверждена. Для установки введите УСТАНОВИТЬ: ').strip()
        except EOFError:
            answer = ''
        if answer != 'УСТАНОВИТЬ':
            raise InstallError('Подтверждение не получено. Ничего не изменено.')
    with tempfile.TemporaryDirectory(prefix='kit-custom-', dir='/tmp') as temp:
        work = Path(temp)
        work.chmod(0o700)
        archive = work / f'x-ui-linux-{arch}.tar.gz'
        print(f'Подготовка проверенного официального архива панели {manifest.PANEL_VERSION} ({arch})...', flush=True)
        fetch_archive(archive, arch, args.archive)
        print('SHA256 архива подтверждена.', flush=True)
        upstream_dir = work / 'scripts'
        upstream_dir.mkdir(mode=0o700)
        for name, spec in manifest.KIT_FILES.items():
            src = (args.upstream_dir / name) if args.upstream_dir else None
            fetch_verified_source(
                f'https://raw.githubusercontent.com/itsnotkubrick/3X-UI_KIT/{manifest.KIT_TAG}/{spec["path"]}',
                spec['blob'], upstream_dir / name, offline=src,
                github_repo='itsnotkubrick/3X-UI_KIT',
            )
        installer = work / 'official-install.sh'
        fetch_verified_source(
            f'https://raw.githubusercontent.com/MHSanaei/3x-ui/{manifest.PANEL_VERSION}/install.sh',
            manifest.PANEL_INSTALL_BLOB, installer,
            offline=(args.upstream_dir / 'install.sh') if args.upstream_dir else None,
            github_repo='MHSanaei/3x-ui', sha256=manifest.PANEL_INSTALL_SHA256,
        )
        # Patch and syntax-check in a private temp directory, before running anything as root.
        kit = upstream_dir / '3x-ui.sh'
        kit.write_text(patch_kit(kit.read_text(encoding='utf-8')), encoding='utf-8')
        if not shutil.which('bash'):
            raise InstallError('Не найден bash.')
        for script in (kit, upstream_dir / 'kit.sh'):
            subprocess.run(['bash', '-n', str(script)], check=True)
        official_text = installer.read_text(encoding='utf-8')
        check_patched = work / 'official-check.sh'
        check_patched.write_text(patch_official(official_text), encoding='utf-8')
        subprocess.run(['bash', '-n', str(check_patched)], check=True)
        # Recheck immediately before running upstream's root install script.
        found = existing_installation()
        if found:
            raise InstallError('Во время загрузки найдена установка 3X-UI: ' + ', '.join(found) + '. Прервано.')
        env = os.environ.copy()
        env.update({
            'KIT_CUSTOM_OFFICIAL_INSTALLER': str(installer),
            'KIT_CUSTOM_PREVERIFIED_ARCHIVE': str(archive),
            'KIT_CUSTOM_ARCHIVE_SHA256': manifest.PANEL_ARCHIVES[arch],
            'KIT_CUSTOM_PATCHER': str(SOURCE_ROOT / 'kit_custom' / 'patcher.py'),
        })
        print('Проверки пройдены. Запускаю оригинальную установку KIT с минимальным патчем загрузки.', flush=True)
        return subprocess.run(['bash', str(kit), *original_args], env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='3X-UI KIT Custom: безопасная установка поверх исходного KIT без изменения работающей панели',
        epilog='Параметры оригинального KIT: --install --yes -- --protocols reality,hy2 --sni example.com',
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--diagnose', action='store_true', help='только чтение и диагностика, доступно без root')
    mode.add_argument('--install', action='store_true', help='установка ТОЛЬКО на чистую Ubuntu 24.04')
    mode.add_argument('--versions', action='store_true', help='статусы совместимости версий')
    parser.add_argument('--version', default=manifest.PANEL_VERSION, help='версия панели, доступна для установки только проверенная')
    parser.add_argument('--archive', type=Path, help='локальный архив релиза, если GitHub Releases заблокирован')
    parser.add_argument('--upstream-dir', type=Path, help='локальная папка с файлами upstream: 3x-ui.sh, kit.sh, kit-sub.py, install.sh')
    parser.add_argument('--offline', action='store_true', help='для диагностики пропустить сетевые проверки')
    parser.add_argument('--yes', action='store_true', help='подтвердить запуск установки, только с --install')
    parser.add_argument('forward', nargs=argparse.REMAINDER, help='после -- аргументы оригинального KIT')
    args = parser.parse_args(argv)
    try:
        if args.versions:
            for version, status in manifest.VERSION_STATUS.items():
                print(f'{version}: {status}')
            return 0
        if args.diagnose:
            diagnostic(args.offline)
            return 0
        return install(args)
    except (InstallError, PatchError, subprocess.CalledProcessError) as exc:
        print(f'ОШИБКА: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
