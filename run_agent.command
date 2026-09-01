#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [[ -x ".venv/bin/python" ]]; then
  exec .venv/bin/python -m source.main
fi

exec python3 -m source.main
