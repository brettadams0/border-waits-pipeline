#!/usr/bin/env bash
# Commits the named paths of the data-branch checkout and pushes them.
#
#   scripts/commit-data.sh ingest snapshots raw history   # right after ingest: this run's readings are durable
#   scripts/commit-data.sh publish published              # after a successful export: the new last-good site data
#
# Only the paths given are staged, never the whole tree, so a half-written export or a stray file can't ride
# along with the snapshots. The two stages are separate commits on purpose: when dbt or the export fails after
# ingest, the snapshots are already stored and published/ still holds the last good export.
set -euo pipefail
stage=${1:?usage: commit-data.sh <stage> <path>...}; shift
cd "${DATASTORE:-datastore}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for path in "$@"; do
  if [ -e "$path" ] || git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then git add -A -- "$path"; fi
done
if git diff --cached --quiet; then echo "$stage: nothing to commit"; exit 0; fi
git commit -q -m "$stage ${RUN_ID:?RUN_ID is not set}"
# Runs are serialized (concurrency: pipeline), so a rejected push means something else wrote the branch:
# replay this commit on top of it rather than overwrite it. Snapshot files are named by fetch time and
# never collide; published/ is replaced whole by the later commit.
for attempt in 1 2 3; do
  if git push -q origin HEAD:data; then echo "$stage: pushed $(git rev-parse --short HEAD)"; exit 0; fi
  echo "$stage: push rejected (attempt $attempt), rebasing on origin/data" >&2
  git pull -q --rebase origin data
done
echo "$stage: could not push to the data branch" >&2
exit 1
