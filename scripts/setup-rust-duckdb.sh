#!/usr/bin/env bash
# Install the pinned official native engine and its signed spatial extension.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_destination="${1:-$task_root/.local/rust-duckdb}"
task_platform="${DUCKDB_PLATFORM:-$(uname -s)-$(uname -m)}"
case "$task_platform" in
  Darwin-arm64|osx-arm64) task_asset=osx-arm64; task_sha=c35d60080b31ba5d11a3ce505a6831be784f003b4c575d32a4c2badb3b41cdf0 ;;
  Darwin-x86_64|osx-amd64) task_asset=osx-amd64; task_sha=98fef9fcad856555ca0403fe4d9d6680acfd26c67e8c6f004d61a248d6bc0eff ;;
  Linux-aarch64|linux-arm64) task_asset=linux-arm64; task_sha=c60eecf91143ca6bbac55c4f4d40dc22520488b0ac257c86e0fe9a2b451cf2b7 ;;
  Linux-x86_64|linux-amd64) task_asset=linux-amd64; task_sha=993ad89e7dfca66cd6da994c2cad090c2fc160ddf9f550498a098ab4bb13cfb1 ;;
  *) echo "Unsupported platform: $task_platform" >&2; exit 1 ;;
esac
mkdir -p "$task_destination"
task_archive="$task_destination/duckdb-shared-libs-$task_asset.tar.gz"
curl --fail --location --retry 3 --output "$task_archive" "https://github.com/duckdb/duckdb/releases/download/v2.0.0/duckdb-shared-libs-$task_asset.tar.gz"
if command -v sha256sum >/dev/null; then
  task_actual="$(sha256sum "$task_archive")"
else
  task_actual="$(shasum -a 256 "$task_archive")"
fi
task_actual="${task_actual%% *}"
if [ "$task_actual" != "$task_sha" ]; then
  echo "DuckDB archive checksum mismatch: $task_archive" >&2
  exit 1
fi
tar -xzf "$task_archive" -C "$task_destination"
task_extension_platform="${task_asset//-/_}"
curl --fail --location --retry 3 --output "$task_destination/spatial.duckdb_extension.gz" "https://extensions.duckdb.org/v2.0.0/$task_extension_platform/spatial.duckdb_extension.gz"
gzip --decompress --force "$task_destination/spatial.duckdb_extension.gz"
# DuckDB additionally verifies the official extension signature and ABI on LOAD.
echo "DuckDB 2.0.0 and signed spatial extension installed in $task_destination"
