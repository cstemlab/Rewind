#!/bin/sh
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Python 3.10 or later is required.'
  exit 1
fi
exec python3 service/server.py --open-browser
