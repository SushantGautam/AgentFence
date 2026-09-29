#!/usr/bin/env bash
# Generate dist/agentfence: the engine plus the payload as base64.
#
# The payload is what a node needs at install time: the base policy, the
# settings template, and the one engine script that runs during an install.
# policy/ and engine/ stay the single source of truth; dist/ is an artefact.
set -euo pipefail
cd "$(dirname "$0")/.."

out=dist/agentfence
version="$(git describe --tags --always --dirty 2>/dev/null || date +%Y.%m.%d)"
built="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

./tools/validate.sh >/dev/null || { echo "validate.sh failed; not building" >&2; exit 1; }

mkdir -p dist

# The payload is assembled flat, whatever the repository layout is. Those flat
# names are the interface an admin uses in a --policy-dir: a site override is
# `50-agentfence-audit.rules.append`, never `policy/50-...`. Keeping the
# payload flat means the repository can be reorganised without changing what
# admins type.
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R policy/. "$stage/"
cp engine/render-settings.py "$stage/"
cp templates/agentfence.conf.example "$stage/"

sed -e "s|@@VERSION@@|$version|" -e "s|@@BUILT@@|$built|" engine/installer-template.sh > "$out"
printf '__PAYLOAD__\n' >> "$out"
# -h so the payload contains files, not the symlinks; deterministic ordering.
tar -czhf - -C "$stage" . 2>/dev/null | base64 >> "$out"
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
