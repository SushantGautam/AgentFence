"""Build hook: generate the installer and bundle it in the wheel.

policy/ and engine/ are the single source of truth. Rather than commit a copy of the built
installer into the Python package, this runs the same build the Makefile runs,
so a wheel can never carry a stale policy.
"""

import os
import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = self.root
        subprocess.run(
            ["bash", os.path.join(root, "tools", "build-installer.sh")],
            cwd=root,
            check=True,
        )
        built = os.path.join(root, "dist", "agentfence")
        if not os.path.exists(built):
            raise RuntimeError("build-installer.sh produced no dist/agentfence")
        build_data["force_include"][built] = "agentfence/agentfence"
        build_data["artifacts"].append("agentfence/agentfence")
