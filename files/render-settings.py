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


def rule(p):
    """Claude Code reads a single leading slash as 'relative to the settings
    file', so an absolute path has to be written with two."""
    return "/" + p


def main():
    base, = sys.argv[1:]
    with open(base) as fh:
        s = json.load(fh)

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
