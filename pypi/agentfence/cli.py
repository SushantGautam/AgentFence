"""Hand off to the bundled shell installer.

This module deliberately contains no policy. Everything agentfence does lives
in the shell installer next to this file; keeping the Python side to an exec
means there is one implementation to audit, not two.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.join(HERE, "agentfence")


def main():
    if not os.path.exists(INSTALLER):
        sys.exit("agentfence: the bundled installer is missing from this wheel")

    if sys.platform != "linux":
        sys.stderr.write(
            "agentfence: this configures a Linux host; on %s it can only "
            "report, not apply\n" % sys.platform
        )

    bash = shutil.which("bash") or "/bin/bash"
    os.chmod(INSTALLER, 0o755)
    os.execv(bash, [bash, INSTALLER] + sys.argv[1:])
