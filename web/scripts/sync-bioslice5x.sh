#!/usr/bin/env bash
# Sync the vendored bioslice5x package from the repo's src/ into web/api/lib/.
#
# Why vendored: Vercel Python serverless functions deploy from web/ only;
# files outside that scope are not uploaded. Vendoring keeps the deploy
# self-contained without needing to publish to PyPI or push to GitHub
# before every web deploy. Run this script after any change to the
# bioslice5x source that the web API needs to pick up.
#
# Usage:
#   bash web/scripts/sync-bioslice5x.sh     # from repo root
#   ./scripts/sync-bioslice5x.sh            # from web/

set -euo pipefail

# Resolve the repo root from the script's location, so this works from
# any CWD.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
web_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${web_dir}/.." && pwd)"

src="${repo_root}/src/bioslice5x"
dst="${web_dir}/api/lib/bioslice5x"

if [[ ! -d "${src}" ]]; then
  echo "ERROR: bioslice5x source not found at ${src}" >&2
  exit 1
fi

echo "Syncing bioslice5x: ${src} -> ${dst}"
rm -rf "${dst}"
cp -r "${src}" "${dst}"
# Drop bytecode caches.
find "${dst}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
echo "Done. $(find "${dst}" -name '*.py' | wc -l | tr -d ' ') Python files, $(find "${dst}" -name '*.yaml' | wc -l | tr -d ' ') YAML files."
