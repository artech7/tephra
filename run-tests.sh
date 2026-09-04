#!/usr/bin/env bash
# All Tephra suites. Exits non-zero if any fail.
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "no .venv -- run: python3 run.py --headless once"; exit 1; }

# Every api_*.py suite gets its own throwaway config dir.
#
# settings.py keeps "which vault to open" in the platform config dir, and
# only two suites (api_admin, api_vaults) ever isolated it -- the other
# seven wrote straight into the operator's real ~/.config/Tephra. A test
# run would leave its /tmp vaults sitting in "recent" and repoint "vault"
# at a directory the same run had just deleted, so the app came up on a
# missing vault afterwards. Per-suite rather than one shared dir because
# these suites assert on config contents (api_vaults checks "config
# follows" a rename and that there's "no dead recents entry"), and a dir
# shared with whatever ran before is a dir those assertions can't trust.
#
# The suites that set this themselves use os.environ.setdefault, so they
# defer to what we export here and still work when run standalone.
CFGROOT="$(cd "$(mktemp -d)" && pwd -P)"   # pwd -P: macOS /tmp is a symlink
trap 'rm -rf "$CFGROOT"' EXIT

failed=()
for t in tests/api_*.py; do
  echo "── $t"
  TEPHRA_CONFIG_DIR="$CFGROOT/$(basename "$t" .py)/Tephra" \
    PYTHONPATH=. "$PY" "$t" || failed+=("$t")
done
for t in tests/ui_*.mjs; do
  echo "── $t"
  node "$t" || failed+=("$t")
done
echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "all suites passed"
else
  echo "FAILED (${#failed[@]}):"
  printf '  %s\n' "${failed[@]}"
fi
exit ${#failed[@]}
