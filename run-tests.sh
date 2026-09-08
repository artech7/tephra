#!/usr/bin/env bash
# All Tephra suites. Exits non-zero if any fail.
#
# Terminal output is one line per suite plus a failure digest; the full
# verbose output of every suite goes to test-results.log. A suite that dies
# before printing its own "N passed, M failed" line is reported as CRASH --
# distinct from FAIL, because a crashed suite's counts are unknown rather
# than bad, and the reason is in the log rather than in a FAIL line.
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
WORK="$(mktemp -d)"
trap 'rm -rf "$CFGROOT" "$WORK"' EXIT

LOG=test-results.log
: > "$LOG"

if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; DIM=$'\033[2m'; B=$'\033[1m'; Z=$'\033[0m'
else
  R=; G=; Y=; DIM=; B=; Z=
fi

failed=()          # suite names that failed or crashed
tot_pass=0
tot_checks=0

# Runs one suite, streams its full output to the log, prints one summary
# line, and stashes its FAIL lines for the digest at the end.
report() {
  local t="$1" rc="$2" out="$3"
  local name; name="$(basename "$t")"

  { echo "── $t"; cat "$out"; echo; } >> "$LOG"

  # The suites print their own tally; take the last one, since a couple
  # wrap it in a banner and print section headers above it.
  local summary ok bad
  summary="$(grep -oE '[0-9]+ passed, [0-9]+ failed' "$out" | tail -1)"

  if [ -z "$summary" ]; then
    failed+=("$name")
    printf '  %sCRASH%s  %-26s %s(exit %s -- see %s)%s\n' "$Y" "$Z" "$name" "$DIM" "$rc" "$LOG" "$Z"
    return
  fi

  ok="${summary%% passed*}"
  bad="${summary#*passed, }"; bad="${bad%% failed*}"
  local total=$((ok + bad))
  tot_pass=$((tot_pass + ok))
  tot_checks=$((tot_checks + total))

  if [ "$bad" -eq 0 ] && [ "$rc" -eq 0 ]; then
    printf '  %sPASS%s   %-26s %s%s/%s%s\n' "$G" "$Z" "$name" "$DIM" "$ok" "$total" "$Z"
  else
    failed+=("$name")
    printf '  %sFAIL%s   %-26s %s/%s\n' "$R" "$Z" "$name" "$ok" "$total"
    grep -E '^[[:space:]]*FAIL[[:space:]]' "$out" > "$WORK/fail.$name" 2>/dev/null || true
  fi
}

for t in tests/api_*.py; do
  out="$WORK/out"
  TEPHRA_CONFIG_DIR="$CFGROOT/$(basename "$t" .py)/Tephra" \
    PYTHONPATH=. "$PY" "$t" > "$out" 2>&1
  report "$t" "$?" "$out"
done
for t in tests/ui_*.mjs; do
  out="$WORK/out"
  node "$t" > "$out" 2>&1
  report "$t" "$?" "$out"
done

echo
pct=0
[ "$tot_checks" -gt 0 ] && pct=$(( tot_pass * 100 / tot_checks ))
printf '  %s%s/%s checks passed (%s%%)%s across %s suites\n' \
  "$B" "$tot_pass" "$tot_checks" "$pct" "$Z" "$(ls tests/api_*.py tests/ui_*.mjs | wc -l | tr -d ' ')"
printf '  %sfull output: %s%s\n' "$DIM" "$LOG" "$Z"

if [ ${#failed[@]} -eq 0 ]; then
  echo
  echo "  ${G}all suites passed${Z}"
  exit 0
fi

echo
echo "  ${R}${B}FAILED (${#failed[@]}):${Z}"
for name in "${failed[@]}"; do
  echo
  echo "  ${R}── ${name}${Z}"
  if [ -s "$WORK/fail.$name" ]; then
    sed 's/^[[:space:]]*/    /' "$WORK/fail.$name"
  else
    echo "    ${DIM}crashed before reporting -- see $LOG${Z}"
  fi
done
echo
exit ${#failed[@]}
