#!/usr/bin/env bash
set -euo pipefail

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NODE_TLS_REJECT_UNAUTHORIZED
export PATH="$HOME/.local/bin:$PATH"

# Solver tasks in this pipeline explicitly require the live public web and
# declare [environment].allow_internet=true.  pw-harness otherwise enables its
# model-endpoint-only Squid sandbox by default; that sandbox is appropriate for
# offline coding tasks, but it prevents the solver's shell tools from reaching
# the research domains named in each online-search brief.  Keep Codex model
# traffic on launchpad's selective proxy while allowing ordinary curl/browser
# traffic to use the container's direct connection.
export HARBOR_ALLOW_INTERNET="${HARBOR_ALLOW_INTERNET:-1}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$ROOT/config.yaml"
YGG_REPO="https://github.com/Parsewave-internal/yggdrasil.git"
YGG_REF=""
RESUME_PACKAGE=""
RESUME_TASK_ID=""
RESUME_FROM_STAGE=""
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --yggdrasil-ref|--ygg-ref) YGG_REF="$2"; shift 2 ;;
    --yggdrasil-repo) YGG_REPO="$2"; shift 2 ;;
    --resume-package) RESUME_PACKAGE="$2"; shift 2 ;;
    --resume-task-id) RESUME_TASK_ID="$2"; shift 2 ;;
    --resume-from-stage) RESUME_FROM_STAGE="$2"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [[ -n "$RESUME_PACKAGE" || -n "$RESUME_TASK_ID" || -n "$RESUME_FROM_STAGE" ]]; then
  [[ -n "$RESUME_PACKAGE" && -n "$RESUME_TASK_ID" && -n "$RESUME_FROM_STAGE" ]] || {
    echo "resume-package, resume-task-id, and resume-from-stage must be provided together" >&2
    exit 2
  }
fi

CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
CREDENTIALS="$(dirname "$CONFIG")/.credentials.yaml"
[[ -f "$CONFIG" ]] || { echo "missing config: $CONFIG" >&2; exit 2; }
[[ -f "$CREDENTIALS" ]] || { echo "missing credentials: $CREDENTIALS" >&2; exit 2; }

# Let each worker select one immutable idea shard without editing tracked files.
export DORAEMON_IDEA_SOURCE="${DORAEMON_IDEA_SOURCE:-$ROOT/ideas.yaml}"
[[ -f "$DORAEMON_IDEA_SOURCE" ]] || {
  echo "missing ideas file: $DORAEMON_IDEA_SOURCE" >&2
  exit 2
}

read_yaml() {
  python3 - "$1" "$2" <<'PY'
import ast
import re
import sys

target = [part.casefold() for part in sys.argv[2].split(".")]
stack = []
for raw in open(sys.argv[1], encoding="utf-8"):
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    indent = len(raw) - len(raw.lstrip(" "))
    match = re.match(r"\s*([^:#][^:]*):(?:\s*(.*))?$", raw.rstrip())
    if not match:
        continue
    key, value = match.group(1).strip(), (match.group(2) or "").strip()
    while stack and stack[-1][0] >= indent:
        stack.pop()
    path = [item[1] for item in stack] + [key.casefold()]
    if value:
        if path == target:
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                parsed = value
            print(parsed)
            raise SystemExit(0)
    else:
        stack.append((indent, key.casefold()))
print("")
PY
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 2
  }
}

credential_value() {
  local primary="$1" alias="${2:-}" value
  value="$(read_yaml "$CREDENTIALS" "$primary")"
  if [[ -z "$value" && -n "$alias" ]]; then
    value="$(read_yaml "$CREDENTIALS" "$alias")"
  fi
  printf '%s' "$value"
}

require_credential() {
  local primary="$1" alias="${2:-}" value
  value="$(credential_value "$primary" "$alias")"
  if [[ -z "$value" || "$value" == "<...>" ]]; then
    echo "missing required credential: $primary" >&2
    exit 2
  fi
}

for command in git gh curl python3 docker flock; do
  require_command "$command"
done
if ! command -v uv >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -LsSf \
    https://astral.sh/uv/0.11.31/install.sh \
    | env UV_UNMANAGED_INSTALL="$HOME/.local/bin" sh
fi
require_command uv
require_credential "proxy_token"
require_credential "github_token" "GH_TOKEN"
require_credential "pwh_github_token" "github_token"
require_credential "aws_access_key_id"
require_credential "aws_secret_access_key"

AWS_ACCESS_KEY_ID="$(credential_value "aws_access_key_id")"
AWS_SECRET_ACCESS_KEY="$(credential_value "aws_secret_access_key")"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export_optional_credential_env() {
  local yaml_key="$1" env_key="$2" value
  value="$(read_yaml "$CREDENTIALS" "$yaml_key")"
  if [[ -n "$value" && "$value" != "<...>" ]]; then
    export "$env_key=$value"
  fi
}
export_optional_credential_env "aws_session_token" "AWS_SESSION_TOKEN"

YGG_REF="${YGG_REF:-$(read_yaml "$CONFIG" yggdrasil_ref)}"
YGG_REF="${YGG_REF:-main}"
YGG_DIR="$HOME/.cache/doraemon/yggdrasil-$YGG_REF"
PWH_PATH="$(read_yaml "$CONFIG" runner.pw_harness_path)"
PWH_PATH="${PWH_PATH:-$HOME/pw-harness}"
PWH_PATH="${PWH_PATH/#\~/$HOME}"
mkdir -p "$HOME/.cache/doraemon"

# Authenticate private GitHub HTTPS clones without embedding the token in a
# remote URL or persistent git configuration. Yggdrasil performs the actual
# pw-harness clone/update using runner.pw_harness_repo from config.yaml.
GH_TOKEN="$(credential_value "github_token" "GH_TOKEN")"
PWH_GITHUB_TOKEN="$(credential_value "pwh_github_token" "github_token")"
export GH_TOKEN PWH_GITHUB_TOKEN GIT_TERMINAL_PROMPT=0
ASKPASS_DIR="$(mktemp -d)"
ASKPASS="$ASKPASS_DIR/git-askpass"
cleanup_askpass() {
  rm -rf "$ASKPASS_DIR"
}
trap cleanup_askpass EXIT
printf '%s\n' '#!/usr/bin/env bash' \
  'case "$1" in' \
  '  *Username*) printf "%s\\n" "x-access-token" ;;' \
  '  *) printf "%s\\n" "$PWH_GITHUB_TOKEN" ;;' \
  'esac' > "$ASKPASS"
chmod 0700 "$ASKPASS"
export GIT_ASKPASS="$ASKPASS"
# A server may have `gh auth setup-git` installed globally. Git consults that
# credential helper before GIT_ASKPASS, which can substitute the deploy-only
# account and make a valid private-harness credential look inaccessible.
# Disable helpers only for the bounded harness fetch/setup window.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="credential.helper"
export GIT_CONFIG_VALUE_0=""

PWH_REPO="$(read_yaml "$CONFIG" runner.pw_harness_repo)"
PWH_REF="$(read_yaml "$CONFIG" runner.pw_harness_ref)"
PWH_REF="${PWH_REF:-main}"
if [[ -n "$PWH_REPO" ]] && ! git ls-remote --exit-code "$PWH_REPO" \
  "refs/heads/$PWH_REF" >/dev/null 2>&1; then
  echo "configured pw-harness repository/ref is inaccessible: $PWH_REPO@$PWH_REF" >&2
  exit 2
fi

sync_repo() {
  local repo="$1" ref="$2" path="$3"
  if [[ ! -d "$path/.git" ]]; then
    git clone --quiet "$repo" "$path"
  fi
  git -C "$path" fetch --quiet origin "$ref"
  git -C "$path" checkout --quiet --detach FETCH_HEAD
}

git -C "$ROOT" diff --quiet -- . || {
  echo "pipeline worktree has uncommitted tracked changes" >&2
  exit 2
}
git -C "$ROOT" diff --cached --quiet -- . || {
  echo "pipeline index has uncommitted tracked changes" >&2
  exit 2
}
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]] || {
  echo "pipeline worktree contains uncommitted or untracked runtime bytes" >&2
  exit 2
}
export DORAEMON_PIPELINE_COMMIT
export DORAEMON_YGGDRASIL_COMMIT
DORAEMON_PIPELINE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"

# Harbor expands these values into the verifier environment. They are not
# consumed by Yggdrasil's credential dataclass, so export them explicitly.
export_optional_credential_env "LLM_JUDGE_API_KEY" "LLM_JUDGE_API_KEY"
export_optional_credential_env "LLM_JUDGE_MODEL" "LLM_JUDGE_MODEL"
export_optional_credential_env "LLM_JUDGE_BASE_URL" "LLM_JUDGE_BASE_URL"
export_optional_credential_env "LLM_JUDGE_REASONING_EFFORT" "LLM_JUDGE_REASONING_EFFORT"
export_optional_credential_env "openrouter_api_key" "OPENROUTER_API_KEY"
export_optional_credential_env "parsewave_token" "PARSEWAVE_TOKEN"

# Existing installations commonly used proxy_token for Launchpad. Preserve
# that non-persistent fallback while preferring the explicit Muse key.
if [[ -z "${PARSEWAVE_TOKEN:-}" ]]; then
  PARSEWAVE_TOKEN="$(credential_value "parsewave_token" "proxy_token")"
  export PARSEWAVE_TOKEN
fi

[[ -n "${OPENROUTER_API_KEY:-}" ]] || {
  echo "OpenRouter judge requires OPENROUTER_API_KEY" >&2
  exit 2
}
if grep -q 'step: doraemon.muse_solver_lane' "$CONFIG"; then
  [[ -n "${PARSEWAVE_TOKEN:-}" ]] || {
    echo "Muse solver requires parsewave_token or PARSEWAVE_TOKEN" >&2
    exit 2
  }
fi
export LLM_JUDGE_API_KEY="$OPENROUTER_API_KEY"
export LLM_JUDGE_BASE_URL=https://openrouter.ai/api/v1
export LLM_JUDGE_MODEL=deepseek/deepseek-v4.1-flash
export LLM_JUDGE_REASONING_EFFORT=xhigh
export VERIFIER_REASONING_EFFORT=xhigh
export VERIFIER_SEARCH_URL="${VERIFIER_SEARCH_URL:-http://127.0.0.1:18120}"
export ONLINE_SEARCH_AGENTIC_VERIFIER_BIN
ONLINE_SEARCH_AGENTIC_VERIFIER_BIN="$($ROOT/scripts/setup_agentic_verifier.sh)"
[[ -x "$ONLINE_SEARCH_AGENTIC_VERIFIER_BIN" ]] || {
  echo "pinned Agentic Verifier setup failed" >&2
  exit 2
}
[[ -n "${LLM_JUDGE_API_KEY:-}" ]] || {
  echo "OpenRouter environment supplied no usable judge credential" >&2
  exit 2
}
JUDGE_MODELS_URL="${LLM_JUDGE_BASE_URL%/}/models"
JUDGE_HTTP_STATUS="$(
  curl -sS --connect-timeout 5 --max-time 20 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $LLM_JUDGE_API_KEY" \
    "$JUDGE_MODELS_URL" || true
)"
if [[ ! "$JUDGE_HTTP_STATUS" =~ ^2[0-9][0-9]$ ]]; then
  echo "OpenRouter judge preflight failed at $JUDGE_MODELS_URL (HTTP ${JUDGE_HTTP_STATUS:-unreachable})" >&2
  exit 2
fi

# Current Yggdrasil owns pw-harness setup (including its configured private
# repository URL and ref). Do not duplicate that logic here.
BOOTSTRAP_LOCK="$HOME/.cache/doraemon/bootstrap.lock"
exec 8>"$BOOTSTRAP_LOCK"
flock 8

# Every task has an independent run.sh process, but these two shared checkouts
# are per-server caches. Serialize only their fetch/setup window; release the
# lock before the actual task engine starts so task and trace concurrency is
# unaffected.
sync_repo "$YGG_REPO" "$YGG_REF" "$YGG_DIR"
DORAEMON_YGGDRASIL_COMMIT="$(git -C "$YGG_DIR" rev-parse HEAD)"
if [[ -d "$PWH_PATH/.git" && -n "$PWH_REPO" ]]; then
  git -C "$PWH_PATH" remote set-url origin "$PWH_REPO"
fi
uv run --project "$YGG_DIR" python -m yggdrasil.cli setup --config "$CONFIG"
export DORAEMON_PW_HARNESS_COMMIT
DORAEMON_PW_HARNESS_COMMIT="$(git -C "$PWH_PATH" rev-parse HEAD)"
flock -u 8
exec 8>&-

assert_expected_commit() {
  local label="$1" actual="$2" expected="$3"
  if [[ -n "$expected" && "$actual" != "$expected" ]]; then
    printf '%s\n' "$label commit mismatch: expected $expected, got $actual" >&2
    exit 2
  fi
}
assert_expected_commit "pipeline" "$DORAEMON_PIPELINE_COMMIT" \
  "${DORAEMON_EXPECTED_PIPELINE_COMMIT:-}"
assert_expected_commit "yggdrasil" "$DORAEMON_YGGDRASIL_COMMIT" \
  "${DORAEMON_EXPECTED_YGGDRASIL_COMMIT:-}"
assert_expected_commit "pw-harness" "$DORAEMON_PW_HARNESS_COMMIT" \
  "${DORAEMON_EXPECTED_PW_HARNESS_COMMIT:-}"

RUN_MANIFEST="$HOME/.cache/doraemon/doraemon-run-manifest-${DORAEMON_PIPELINE_COMMIT:0:12}.json"
python3 - "$RUN_MANIFEST" \
  "$DORAEMON_PIPELINE_COMMIT" \
  "$DORAEMON_YGGDRASIL_COMMIT" \
  "$DORAEMON_PW_HARNESS_COMMIT" \
  "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": "doraemon-run-manifest-v1",
    "pipeline_commit": sys.argv[2],
    "yggdrasil_commit": sys.argv[3],
    "pw_harness_commit": sys.argv[4],
    "config": sys.argv[5],
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
temporary.replace(path)
PY
rm -rf "$ASKPASS_DIR"
trap - EXIT
unset GIT_ASKPASS GIT_TERMINAL_PROMPT GH_TOKEN PWH_GITHUB_TOKEN
unset GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0

export PWH_PATH
if [[ -n "$RESUME_PACKAGE" ]]; then
  exec uv run --project "$PWH_PATH" \
    --with-editable "$YGG_DIR" \
    --with boto3 --with httpx --with beautifulsoup4 --with pypdf --with pyyaml \
    python "$ROOT/scripts/resume_media_package.py" \
    --config "$CONFIG" \
    --task-root "$RESUME_PACKAGE" \
    --task-id "$RESUME_TASK_ID" \
    --from-stage "$RESUME_FROM_STAGE" \
    "${ARGS[@]}"
fi
exec uv run --project "$PWH_PATH" \
  --with-editable "$YGG_DIR" \
  --with boto3 --with httpx --with beautifulsoup4 --with pypdf --with pyyaml \
  python -m yggdrasil.cli run \
  --config "$CONFIG" "${ARGS[@]}"
