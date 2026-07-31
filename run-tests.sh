#!/usr/bin/env bash
# All Tephra suites. Exits non-zero if any fail.
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "no .venv -- run: python3 run.py --headless once"; exit 1; }
failed=()
for t in tests/api_*.py; do
  echo "── $t"
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
