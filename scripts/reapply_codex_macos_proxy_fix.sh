#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_PATH="${ROOT_DIR}/scripts/codex-otel-no-proxy.patch"
SOURCE_DIR="${CODEX_SOURCE_DIR:-/tmp/codex-upstream}"
PROFILE="${CODEX_BUILD_PROFILE:-release}"
REPO_URL="${CODEX_REPO_URL:-https://github.com/openai/codex}"
GIT_REF="${CODEX_GIT_REF:-origin/main}"
INSTALL_PATH="${CODEX_INSTALL_PATH:-$HOME/.local/bin/codex-patched}"

usage() {
  cat <<'EOF'
Rebuild and install a separate locally patched Codex binary that avoids the
macOS system-configuration proxy panic during `codex exec`.

Environment overrides:
  CODEX_SOURCE_DIR      Existing or desired Codex checkout path
  CODEX_BUILD_PROFILE   debug or release (default: release)
  CODEX_REPO_URL        Upstream clone URL (default: official GitHub repo)
  CODEX_GIT_REF         Git ref to build from (default: origin/main)
  CODEX_INSTALL_PATH    Install path for the patched binary
                        (default: ~/.local/bin/codex-patched)

Examples:
  scripts/reapply_codex_macos_proxy_fix.sh
  CODEX_BUILD_PROFILE=release scripts/reapply_codex_macos_proxy_fix.sh
  CODEX_SOURCE_DIR="$HOME/src/codex" scripts/reapply_codex_macos_proxy_fix.sh
  CODEX_GIT_REF=origin/main CODEX_INSTALL_PATH="$HOME/bin/codex-patched" \
    scripts/reapply_codex_macos_proxy_fix.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${PROFILE}" != "debug" && "${PROFILE}" != "release" ]]; then
  echo "Unsupported CODEX_BUILD_PROFILE: ${PROFILE}" >&2
  exit 1
fi

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "cargo is required" >&2; exit 1; }

if [[ ! -f "${PATCH_PATH}" ]]; then
  echo "Patch file not found: ${PATCH_PATH}" >&2
  exit 1
fi

if [[ -d "${SOURCE_DIR}/.git" ]]; then
  git -C "${SOURCE_DIR}" fetch --all --tags --prune
else
  rm -rf "${SOURCE_DIR}"
  git clone "${REPO_URL}" "${SOURCE_DIR}"
fi

if ! git -C "${SOURCE_DIR}" rev-parse --verify --quiet "${GIT_REF}" >/dev/null; then
  echo "Unknown git ref: ${GIT_REF}" >&2
  exit 1
fi

if git -C "${SOURCE_DIR}" apply --reverse --check "${PATCH_PATH}" >/dev/null 2>&1; then
  git -C "${SOURCE_DIR}" apply --reverse "${PATCH_PATH}"
fi

if ! git -C "${SOURCE_DIR}" diff --quiet || ! git -C "${SOURCE_DIR}" diff --cached --quiet; then
  cat >&2 <<EOF
Source checkout has uncommitted changes after removing the proxy patch:
  ${SOURCE_DIR}
Use a disposable CODEX_SOURCE_DIR or clean the checkout before re-running.
EOF
  exit 1
fi

git -C "${SOURCE_DIR}" checkout --quiet --detach "${GIT_REF}"
git -C "${SOURCE_DIR}" apply --check "${PATCH_PATH}"
git -C "${SOURCE_DIR}" apply "${PATCH_PATH}"

BUILD_DIR="${SOURCE_DIR}/codex-rs"
if [[ ! -f "${BUILD_DIR}/Cargo.toml" ]]; then
  echo "Expected Codex Rust workspace at ${BUILD_DIR}" >&2
  exit 1
fi

pushd "${BUILD_DIR}" >/dev/null
if [[ "${PROFILE}" == "release" ]]; then
  cargo build --release -p codex-cli
  BUILT_BINARY="${BUILD_DIR}/target/release/codex"
else
  cargo build -p codex-cli
  BUILT_BINARY="${BUILD_DIR}/target/debug/codex"
fi
popd >/dev/null

if [[ ! -x "${BUILT_BINARY}" ]]; then
  echo "Built Codex binary not found: ${BUILT_BINARY}" >&2
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$(dirname "${INSTALL_PATH}")"
if [[ -e "${INSTALL_PATH}" ]]; then
  BACKUP_PATH="${INSTALL_PATH}.backup-${TIMESTAMP}"
  cp "${INSTALL_PATH}" "${BACKUP_PATH}"
else
  BACKUP_PATH="(none)"
fi
install -m 755 "${BUILT_BINARY}" "${INSTALL_PATH}"

echo
echo "Patched Codex installed as a separate binary."
echo "  source: ${SOURCE_DIR}"
echo "  git ref: ${GIT_REF}"
echo "  built binary: ${BUILT_BINARY}"
echo "  installed binary: ${INSTALL_PATH}"
echo "  backup: ${BACKUP_PATH}"
echo "  official codex remains managed by Homebrew"
echo
echo "Suggested verification:"
echo "  codex --version"
echo "  ${INSTALL_PATH} --version"
echo "  ${INSTALL_PATH} exec --skip-git-repo-check --json --ephemeral \"Reply with the single word OK.\""
