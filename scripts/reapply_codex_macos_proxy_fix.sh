#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_PATH="${ROOT_DIR}/scripts/codex-otel-no-proxy.patch"
SOURCE_DIR="${CODEX_SOURCE_DIR:-/tmp/codex-upstream}"
PROFILE="${CODEX_BUILD_PROFILE:-debug}"
REPO_URL="${CODEX_REPO_URL:-https://github.com/openai/codex}"

usage() {
  cat <<'EOF'
Rebuild and reinstall a locally patched Codex binary that avoids the macOS
system-configuration proxy panic during `codex exec`.

Environment overrides:
  CODEX_SOURCE_DIR      Existing or desired Codex checkout path
  CODEX_BUILD_PROFILE   debug or release (default: debug)
  CODEX_REPO_URL        Upstream clone URL (default: official GitHub repo)

Examples:
  scripts/reapply_codex_macos_proxy_fix.sh
  CODEX_BUILD_PROFILE=release scripts/reapply_codex_macos_proxy_fix.sh
  CODEX_SOURCE_DIR="$HOME/src/codex" scripts/reapply_codex_macos_proxy_fix.sh
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
command -v codex >/dev/null 2>&1 || { echo "codex is required on PATH" >&2; exit 1; }

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

if git -C "${SOURCE_DIR}" apply --reverse --check "${PATCH_PATH}" >/dev/null 2>&1; then
  echo "Patch already present in ${SOURCE_DIR}"
else
  git -C "${SOURCE_DIR}" apply --check "${PATCH_PATH}"
  git -C "${SOURCE_DIR}" apply "${PATCH_PATH}"
fi

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

INSTALLED_LINK="$(command -v codex)"
INSTALLED_BINARY="$(readlink "${INSTALLED_LINK}")"
if [[ -z "${INSTALLED_BINARY}" ]]; then
  echo "Could not resolve installed Codex binary from ${INSTALLED_LINK}" >&2
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_PATH="${INSTALLED_BINARY}.backup-${TIMESTAMP}"
cp "${INSTALLED_BINARY}" "${BACKUP_PATH}"
install -m 755 "${BUILT_BINARY}" "${INSTALLED_BINARY}"

echo
echo "Patched Codex installed."
echo "  source: ${SOURCE_DIR}"
echo "  built binary: ${BUILT_BINARY}"
echo "  installed binary: ${INSTALLED_BINARY}"
echo "  backup: ${BACKUP_PATH}"
echo
echo "Suggested verification:"
echo "  codex --version"
echo "  codex exec --skip-git-repo-check --json --ephemeral \"Reply with the single word OK.\""
