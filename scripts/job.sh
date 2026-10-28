#!/usr/bin/env bash
# Dev helper: start a stage and follow its job until it ends.
#   scripts/job.sh <project id> <stage path> [json body]     e.g. scripts/job.sh abc123 voice/generate
set -euo pipefail
BASE="${BTV_URL:-http://localhost:8765}/api/projects/$1"
BODY="${3:-}"; [ -n "$BODY" ] || BODY='{}'
RESP=$(curl -s ${BTV_COOKIE:+-b $BTV_COOKIE} -XPOST "$BASE/$2" -H 'content-type: application/json' -d "$BODY")
JOB=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
if [ -z "$JOB" ]; then echo "start failed: $RESP"; exit 1; fi
SINCE=0
while true; do
  S=$(curl -s ${BTV_COOKIE:+-b $BTV_COOKIE} "$BASE/jobs/$JOB?since=$SINCE")
  SINCE=$(echo "$S" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for l in d['lines']: print('  ', l['msg'], file=sys.stderr)
print(d['next'])")
  ST=$(echo "$S" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])")
  [ "$ST" = running ] || { echo "$S" | python3 -c "import sys,json; d=json.load(sys.stdin); print('==>', d['status'], d.get('result') or d.get('error'))"; break; }
  sleep 3
done
