#!/usr/bin/env bash
set -euo pipefail

# Publish the already validated `stage/` payload without duplicating the orphan-
# branch / force-with-lease protocol in every collection workflow.
#
# Usage:
#   publish_public_payload.sh "live commit message" ["release commit message"]
#
# rate-live is always updated.  Passing the second message also updates rate-data,
# which is the only branch allowed to trigger a Vercel Git deployment.

LIVE_MESSAGE=${1:?"live payload commit message is required"}
RELEASE_MESSAGE=${2:-}
TMP_BRANCH="public-payload-new"

publish_branch() {
  local branch=$1
  local message=$2
  local before=""

  case "$branch" in
    rate-live|rate-data) ;;
    *)
      echo "refusing unexpected public payload branch: $branch" >&2
      return 2
      ;;
  esac

  git fetch --depth=1 origin "+${branch}:refs/remotes/origin/${branch}" 2>/dev/null || true
  before=$(git rev-parse "origin/${branch}" 2>/dev/null || echo "")

  for attempt in 1 2; do
    git checkout -q --detach 2>/dev/null || true
    git branch -D "$TMP_BRANCH" 2>/dev/null || true
    git checkout -q --orphan "$TMP_BRANCH"
    git rm -rq --cached . 2>/dev/null || true

    # Keep build inputs/evidence outside the orphan payload while replacing the
    # public branch working tree with the validated stage directory.
    find . -maxdepth 1 -mindepth 1 \
      -not -name .git -not -name work -not -name publish \
      -not -name stage -not -name data -not -name site \
      -not -name site-public -exec rm -rf {} +
    rm -rf latest site site-public vercel.json api
    cp -r stage/latest stage/site-public stage/api .
    cp stage/vercel.json .

    git add -f latest site-public vercel.json api
    git commit -q -m "$message"

    if [ -n "$before" ]; then
      if git push --force-with-lease="${branch}:${before}" origin "HEAD:${branch}"; then
        echo "$branch push 성공 (시도 $attempt)"
        return 0
      fi
    elif git push origin "HEAD:${branch}"; then
      echo "$branch push 성공 (시도 $attempt)"
      return 0
    fi

    echo "$branch push 거부됨. 원격이 그 사이 바뀌었다. 재시도 $attempt"
    git fetch --depth=1 origin "+${branch}:refs/remotes/origin/${branch}" 2>/dev/null || true
    before=$(git rev-parse "origin/${branch}" 2>/dev/null || echo "")
  done

  echo "$branch push 재시도 실패" >&2
  return 1
}

publish_branch rate-live "$LIVE_MESSAGE"
if [ -n "$RELEASE_MESSAGE" ]; then
  publish_branch rate-data "$RELEASE_MESSAGE"
fi
