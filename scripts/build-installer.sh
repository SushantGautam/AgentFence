#!/usr/bin/env bash
# Generate dist/agentfence: the template plus files/ as a base64 payload.
# files/ stays the single source of truth; the installer is a build artefact.
set -euo pipefail
cd "$(dirname "$0")/.."

out=dist/agentfence
version="$(git describe --tags --always --dirty 2>/dev/null || date +%Y.%m.%d)"
built="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

./scripts/validate.sh >/dev/null || { echo "validate.sh failed; not building" >&2; exit 1; }

mkdir -p dist
sed -e "s|@@VERSION@@|$version|" -e "s|@@BUILT@@|$built|" scripts/installer-template.sh > "$out"
printf '__PAYLOAD__\n' >> "$out"
# -h so the payload contains files, not the symlinks; deterministic ordering.
tar -czf - -C files . 2>/dev/null | base64 >> "$out"
chmod +x "$out"

bash -n "$out" || { echo "generated script has a syntax error" >&2; exit 1; }

# Published next to the installer. This file runs as root on a shared node, so
# whoever downloads it needs a way to check it arrived intact before running.
if command -v sha256sum >/dev/null 2>&1; then
    (cd dist && sha256sum agentfence > agentfence.sha256)
else
    (cd dist && shasum -a 256 agentfence > agentfence.sha256)
fi

printf 'built %s  (%s, %s bytes)\n' "$out" "$version" "$(wc -c < "$out" | tr -d ' ')"
