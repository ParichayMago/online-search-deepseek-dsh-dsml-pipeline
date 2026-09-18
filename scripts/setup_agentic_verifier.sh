#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${ONLINE_SEARCH_AGENTIC_VERIFIER_REPO:-https://github.com/Parsewave-internal/agentic-verifier-harness.git}"
COMMIT="${ONLINE_SEARCH_AGENTIC_VERIFIER_COMMIT:-145eba926c53e7ecb1b112c5b021064308ff6536}"
PATCH="$ROOT/patches/agentic-verifier-online-search.patch"
PATCH_SHA="$(sha256sum "$PATCH" | awk '{print $1}')"
TARGET="${ONLINE_SEARCH_AGENTIC_VERIFIER_ROOT:-$HOME/.cache/doraemon/agentic-verifier-online-search-${COMMIT:0:7}-${PATCH_SHA:0:12}}"
MARKER="$TARGET/.online-search-build"
CLI="$TARGET/.venv/bin/agentic-verifier"

# Multiple task windows may start together. Serialize this one install, not
# model work, and reuse it only after validating its exact provenance.
mkdir -p "$(dirname "$TARGET")"
exec 9>"${TARGET}.setup.lock"
flock 9

valid_existing() {
  [[ -x "$CLI" && -f "$MARKER" ]] || return 1
  grep -qx "commit=$COMMIT" "$MARKER" || return 1
  grep -qx "patch_sha256=$PATCH_SHA" "$MARKER" || return 1
  [[ "$(git -C "$TARGET" rev-parse HEAD 2>/dev/null || true)" == "$COMMIT" ]] || return 1
  grep -q 'solution/evidence_graph.json' "$TARGET/src/agentic_verifier/runner.py" || return 1
  grep -q "not self.model.startswith('deepseek/')" "$TARGET/src/agentic_verifier/backend.py" || return 1
}

if valid_existing; then
  printf '%s\n' "$CLI"
  exit 0
fi

[[ ! -e "$TARGET" ]] || {
  echo "agentic verifier target exists but fails its provenance check: $TARGET" >&2
  exit 2
}
command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 127; }
command -v uv >/dev/null 2>&1 || { echo "uv is required" >&2; exit 127; }

git clone --quiet --no-checkout "$REPO" "$TARGET"
git -C "$TARGET" checkout --quiet --detach "$COMMIT"
git -C "$TARGET" apply --check "$PATCH"
git -C "$TARGET" apply "$PATCH"
uv venv --quiet "$TARGET/.venv"
uv pip install --quiet --python "$TARGET/.venv/bin/python" -e "$TARGET"
printf 'commit=%s\npatch_sha256=%s\n' "$COMMIT" "$PATCH_SHA" > "$MARKER"
chmod 0600 "$MARKER"

valid_existing || {
  echo "agentic verifier setup did not produce a valid pinned harness" >&2
  exit 2
}
printf '%s\n' "$CLI"
