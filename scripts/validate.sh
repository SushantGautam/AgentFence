#!/usr/bin/env bash
# Offline checks. Run before every deploy. No cluster access needed.
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
note() { printf '  %s\n' "$*"; }
ok()   { printf 'OK   %s\n' "$*"; }
bad()  { printf 'FAIL %s\n' "$*"; fail=1; }

f=files/managed-settings.json

# 1. Valid JSON. JSON has no comments; a '#' comment silently kills the whole
#    policy and Claude Code falls back to defaults with no warning.
if python3 -c "import json;json.load(open('$f'))" 2>/dev/null; then
  ok "$f parses as JSON"
else
  bad "$f is not valid JSON"
fi

# 2. Absolute paths in permission rules need a DOUBLE slash. '/etc/**' means
#    'relative to the settings file', i.e. /etc/claude-code/etc/** - a no-op.
if grep -nE '"(Read|Write|Edit)\(/[^/]' "$f"; then
  bad "single-slash path rule above: use //abs/path, not /abs/path"
else
  ok "all path rules use // for absolute paths"
fi

# 3. Permission rules cannot expand shell variables or bash extglob.
if grep -nE '\$[A-Z_]+|!\(' "$f"; then
  bad "\$VAR or extglob !() above: not expanded, the rule matches nothing"
else
  ok "no \$VAR / extglob in rules"
fi

# 4. Sandbox must hard-fail, not silently skip, when bwrap is missing.
python3 - "$f" <<'PY' || fail=1
import json,sys
s=json.load(open(sys.argv[1]))
sb=s.get("sandbox",{})
checks={
 "sandbox.enabled": sb.get("enabled") is True,
 "sandbox.failIfUnavailable": sb.get("failIfUnavailable") is True,
 "sandbox.allowUnsandboxedCommands is false": sb.get("allowUnsandboxedCommands") is False,
 "permissions.disableBypassPermissionsMode": s.get("permissions",{}).get("disableBypassPermissionsMode")=="disable",
 "allowManagedPermissionRulesOnly": s.get("allowManagedPermissionRulesOnly") is True,
 "requiredMinimumVersion set": bool(s.get("requiredMinimumVersion")),
}
bad=False
for k,v in checks.items():
    print(("OK   " if v else "FAIL ")+k); bad|=not v
sys.exit(1 if bad else 0)
PY

# 5. The installer must at least parse.
bash -n scripts/installer-template.sh 2>/dev/null \
  && ok "installer template parses" || bad "installer template has a syntax error"

for shipped in files/bin/agentfence-shim files/profile.d-agentfence.sh; do
  sh -n "$shipped" 2>/dev/null && ok "$shipped parses" || bad "$shipped has a syntax error"
done

python3 -c "import tomllib;tomllib.load(open('files/cplt-config.toml','rb'))" 2>/dev/null \
  && ok "files/cplt-config.toml parses as TOML" || bad "files/cplt-config.toml is not valid TOML"

# 6. The site-path renderer. This is the one step that builds JSON at install
#    time on a node, where validate.sh never runs, so it is exercised here
#    with the cases that would produce a silently empty policy: no site paths
#    at all, a full set, and input that must be refused outright.
r=files/render-settings.py
settings=files/managed-settings.json

if env -u AGENTFENCE_SHARED_HOMES -u AGENTFENCE_SHARED_APPS \
       -u AGENTFENCE_SHARED_WORKSPACES -u AGENTFENCE_SITE_NAME \
       python3 "$r" "$settings" | python3 -c 'import json,sys;json.load(sys.stdin)' 2>/dev/null; then
  ok "renders to valid JSON with no site paths set"
else
  bad "renders to invalid JSON with no site paths set"
fi

rendered=$(AGENTFENCE_SITE_NAME="Test site" \
           AGENTFENCE_SHARED_HOMES="/shared/home /export/home" \
           AGENTFENCE_SHARED_APPS="/shared/apps" \
           AGENTFENCE_SHARED_WORKSPACES="/shared/projects" \
           python3 "$r" "$settings" 2>/dev/null) || rendered=""

if [ -n "$rendered" ] && printf '%s' "$rendered" | python3 -c 'import json,sys;json.load(sys.stdin)' 2>/dev/null; then
  ok "renders to valid JSON with site paths set"
else
  bad "renders to invalid JSON with site paths set"
fi

# Same two traps as rules 2 and 3, but on the rendered output.
if printf '%s' "$rendered" | grep -qE '"(Read|Write|Edit)\(/[^/]'; then
  bad "rendered output has a single-slash path rule"
else
  ok "rendered path rules use // for absolute paths"
fi

if printf '%s' "$rendered" | grep -qE '"//?"'; then
  bad "rendered output contains a bare / or //, which would cover everything"
else
  ok "rendered output has no whole-filesystem entry"
fi

for bogus in "relative/path" "/" "/has/*/wildcard" "/has/../dots"; do
  if AGENTFENCE_SHARED_HOMES="$bogus" python3 "$r" "$settings" >/dev/null 2>&1; then
    bad "renderer accepted $bogus as a site path"
  else
    ok "renderer refuses $bogus"
  fi
done

exit $fail
