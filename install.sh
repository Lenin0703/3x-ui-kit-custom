#!/usr/bin/env bash
# 3X-UI KIT Custom - first stage. No mutations without explicit --install.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m kit_custom.cli "$@"
