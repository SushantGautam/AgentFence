#!/usr/bin/env python3
# Managed by agentfence - do not edit on a node.
#
# Injects the site's own filesystem layout into managed-settings.json.
#
# Why a script and not sed: the site paths are lists, and a site may have
# none. Deleting the last element of a JSON array with sed leaves a trailing
# comma, which makes the file unparseable - and an unparseable
# managed-settings.json is ignored silently, so the node would look configured
# and enforce nothing. Building the JSON with a JSON library cannot do that.
#
# Every path is checked before it is used. A relative path, or a bare '/',
# would turn a narrow rule into one that covers the whole filesystem, so those
# are refused rather than written out.

import json
import os
import sys


class BadPath(Exception):
    pass


def paths(var):
    """Read a space-separated list of absolute paths from the environment."""
    out = []
    for raw in os.environ.get(var, "").split():
        p = raw.rstrip("/")
        if not raw.startswith("/"):
            raise BadPath("%s: %r is not an absolute path" % (var, raw))
        if p == "":
            raise BadPath("%s: '/' is the whole filesystem, too broad to use" % var)
        if "*" in p or "?" in p:
            raise BadPath("%s: %r contains a wildcard; give a plain directory" % (var, raw))
        if ".." in p.split("/"):
            raise BadPath("%s: %r contains '..'" % (var, raw))
        if p not in out:
            out.append(p)
    return out


def merge(base, overlay, where=""):
    """Fold a site overlay into the shipped policy.

    Lists are added to, not replaced: a site can append a deny rule without
    restating the eleven that ship, and cannot drop one by omission. Removing
    something that ships requires replacing the whole file in the policy
    directory, which is a deliberate and visible act rather than a quiet
    side effect of an overlay.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for k, v in overlay.items():
            out[k] = merge(base[k], v, "%s.%s" % (where, k)) if k in base else v
        return out
    if isinstance(base, list) and isinstance(overlay, list):
        out = list(base)
        for item in overlay:
            if item not in out:
                out.append(item)
        return out
    if isinstance(base, (dict, list)) != isinstance(overlay, (dict, list)):
        raise BadPath("overlay%s: cannot merge %s into %s"
                      % (where, type(overlay).__name__, type(base).__name__))
    return overlay


# The settings this configuration exists to guarantee. A site overlay may add
# to the policy; it may not quietly switch off the enforcement, because a file
# that looks configured and enforces nothing is the failure this whole
# repository is built to avoid.
INVARIANTS = {
    ("sandbox", "enabled"): True,
    ("sandbox", "failIfUnavailable"): True,
    ("sandbox", "allowUnsandboxedCommands"): False,
    ("allowManagedPermissionRulesOnly",): True,
    ("permissions", "disableBypassPermissionsMode"): "disable",
}


def check_invariants(s):
    for path, want in INVARIANTS.items():
        node = s
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node != want:
            raise BadPath(
                "the overlay sets %s to %r; it must stay %r"
                % (".".join(path), node, want))


def rule(p):
    """Claude Code reads a single leading slash as 'relative to the settings
    file', so an absolute path has to be written with two."""
    return "/" + p


def main():
    args = sys.argv[1:]
    if not 1 <= len(args) <= 2:
        raise BadPath("usage: render-settings.py BASE.json [OVERLAY.json]")
    base = args[0]
    with open(base) as fh:
        s = json.load(fh)

    if len(args) == 2:
        with open(args[1]) as fh:
            try:
                overlay = json.load(fh)
            except ValueError as e:
                raise BadPath("%s is not valid JSON: %s" % (args[1], e))
        s = merge(s, overlay)
        check_invariants(s)

    homes = paths("AGENTFENCE_SHARED_HOMES")
    apps = paths("AGENTFENCE_SHARED_APPS")
    workspaces = paths("AGENTFENCE_SHARED_WORKSPACES")
    site = os.environ.get("AGENTFENCE_SITE_NAME", "").strip() or "This shared machine"

    s["companyAnnouncements"] = [
        a.replace("{{ site_name }}", site) for a in s.get("companyAnnouncements", [])
    ]

    # Other people's home directories, wherever this site keeps them. The deny
    # rule covers the agent asking to read a key; denyRead covers the sandbox.
    deny = s["permissions"]["deny"]
    fs = s["sandbox"]["filesystem"]
    for p in homes:
        r = "Read(%s/**/.ssh/**)" % rule(p)
        if r not in deny:
            deny.append(r)
        if rule(p) not in fs["denyRead"]:
            fs["denyRead"].append(rule(p))

    # Shared software trees: readable, never writable.
    for p in apps:
        if rule(p) not in fs["denyWrite"]:
            fs["denyWrite"].append(rule(p))

    # Shared project space. allowManagedReadPathsOnly is on, so a directory
    # that is not listed here cannot be read at all - without this a site with
    # projects outside $HOME has agents that cannot see their own work.
    for p in workspaces:
        if rule(p) not in fs["allowRead"]:
            fs["allowRead"].append(rule(p))

    json.dump(s, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except BadPath as e:
        sys.stderr.write("agentfence: %s\n" % e)
        sys.exit(2)
