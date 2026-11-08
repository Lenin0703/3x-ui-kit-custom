#!/usr/bin/env bash
# 3X-UI KIT Custom: one-command launcher for a PUBLIC GitHub repository.
# Downloads only pinned source files, verifies SHA256, then delegates to install.sh.
# No system changes are made until install.sh explicitly enters --install mode.
set -Eeuo pipefail

REPO="Lenin0703/3x-ui-kit-custom"
REF="main"
RAW="https://raw.githubusercontent.com/$REPO/$REF"

fail() { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }
for tool in curl bash python3 sha256sum mktemp; do
  command -v "$tool" >/dev/null 2>&1 || fail "Не найдена команда $tool. Установите её и повторите запуск."
done

umask 077
work=$(mktemp -d "${TMPDIR:-/tmp}/3x-ui-kit-custom.XXXXXXXX") || fail 'Не удалось создать временный каталог.'
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Hashes of audited project files on main. Update these with every intentional code release.
# A moving branch or compromised download must not silently replace the executable payload.
fetch_file() {
  local path=$1 expected=$2 target="$work/$1" actual
  mkdir -p -- "$(dirname -- "$target")"
  if ! curl -fLsS --retry 3 --retry-delay 1 --connect-timeout 15 --max-time 90 \
      --max-filesize 1048576 --output "$target" "$RAW/$path"; then
    fail "Не удалось скачать $path из GitHub. Проверьте, что репозиторий Public и GitHub Raw доступен."
  fi
  actual=$(sha256sum "$target" | awk '{print $1}')
  [[ $actual == "$expected" ]] || fail "SHA256 файла $path не совпадает с проверенной версией. Установка отменена."
}

fetch_file 'install.sh' '870247bb8621feb44b07245f49dbf8dbb60b82b6d3ad3b6eb71a468a735d4d9d'
fetch_file 'kit_custom/__init__.py' '22ab08a8997e0e6ce769e63a733a273b04eae852dedad41d8352de8e63c8b1fc'
fetch_file 'kit_custom/cli.py' 'c63c0f2ae86328dea92e054a3d6ab6bbcba206945a92a45dde0741a5648b3eb9'
fetch_file 'kit_custom/manifest.py' '3c823575f09b6c6de6fda4de023f1c7f1947b24b9e4c6cd4bcdaf6d7cdf7f07c'
fetch_file 'kit_custom/patcher.py' '057a86bd8c3f6acc70ab795f3158125969a28cdc43c435cf678a8e5660f89786'

if [[ $# -eq 0 ]]; then
  set -- --install
fi

printf '%s\n' '3X-UI KIT Custom: исходники загружены и проверены (SHA256).'
# Diagnostics/version information never require sudo or alter system state.
case "$1" in
  --diagnose|--versions)
    bash "$work/install.sh" "$@"
    ;;
  --install)
    if (( EUID == 0 )); then
      bash "$work/install.sh" "$@"
    else
      command -v sudo >/dev/null 2>&1 || fail 'Для установки нужны права root: войдите под root или установите sudo.'
      sudo bash "$work/install.sh" "$@"
    fi
    ;;
  *)
    fail "Неизвестный режим: $1. Доступны --install, --diagnose, --versions."
    ;;
esac
