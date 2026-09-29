# Design notes

Why AgentFence is built the way it is, and what was considered and rejected.
For how to use it, see [README.md](../README.md).

## Threat model

Two different threats got merged in the original thread. Separating them is
what makes a small solution possible.

| | Threat | Design response |
|---|---|---|
| **1** | An agent does something destructive **under the user's own authority**: `rm -rf ~/data`, `scancel` someone else's job, `make -j128` on a login node, reads `~/.ssh/id_rsa` into a prompt. | This is the real risk. It is defeated by ordinary OS controls plus the agents' own sandboxes. |
| **2** | A user **deliberately** weaponises an agent. | Not addressed, on purpose. The user already has a shell; the agent adds no capability. Designing for this produces an unmaintainable AppArmor/exec-interception arms race, which is where the original thread was heading. |

Consequence: "can a user bypass it?" stops being the deciding question for the
agent-level layers. The user is not the attacker. The agent is the risk, and
the agent cannot write `/etc`.

No configuration is 100% against a motivated user. This one aims only at
threat 1, which is the failure mode actually observed. How well it holds is
not yet measured — see "How far this is tested" in the README.

## Architecture

```
  Layer A   systemd user slices · filesystem perms · pam_slurm_adopt
            mandatory · editor-agnostic · survives any new agent
                              │
  Layer B1  Claude Code  ──► its own bubblewrap sandbox
            /etc/claude-code/managed-settings.json   (maintained by Anthropic)
  Layer B2  every other agent ──► navikt/cplt  (Landlock + seccomp)
            /opt/agentfence/bin shims on PATH              (maintained by NAV)
                              │
  Layer C   auditd watch on the policy files themselves
```

Layer A is the boundary. Layers B1/B2 are ergonomics: they make the safe
invocation the default one. If a user installs their own agent in `$HOME`,
Layer A still holds.

## What we reuse, and what we rejected

| Component | Role | Why |
|---|---|---|
| **Claude Code managed settings + built-in bwrap sandbox** | Claude Code containment | Already ships the exact sandbox the thread was proposing to build. Anthropic maintains the bwrap invocation, the credential masking and the CVE response, not us. |
| **[navikt/cplt](https://github.com/navikt/cplt)** | every other agent | Landlock + seccomp + CONNECT proxy + git/gh guards, apt-installable from NAV's repo, already wraps Copilot CLI, OpenCode, goose, Antigravity. Writing our own bubblewrap wrapper would be strictly worse. |
| **systemd `user-.slice` drop-in** | per-user CPU/RAM/PID caps, **login nodes only** | Stock, and only applied when nothing else is already doing the job — see "Who owns resource limits" below. |
| **`pam_slurm_adopt` + Slurm cgroups** | compute-node containment | SchedMD's own recommendation. Unbypassable. Off by default here — see the warning below. |
| **auditd** | tamper evidence | Stock. Low-volume watches on the policy files, not full `execve` logging. |
| **[OpenAgentLock](https://github.com/openagentlock/OpenAgentLock)** | **rejected** | Checked against its own docs, not dismissed on principle: the daemon is a Docker container bound to `127.0.0.1:7878`/`7879` with a `agentlock-state` volume, `agentlock install` and signer enrolment are per-user commands, and the CLI "owns the long-lived signing key" on the host. OIDC SSO, RBAC and LDAP are listed as *not yet*. That is one daemon, one Docker socket and one TOTP enrolment per account across ~60 users on a shared login node, with no central policy push. Its YAML gate + Merkle ledger is a good idea and the right thing to revisit **if** a multi-user/server mode lands — worth opening an issue upstream. |
| **Per-agent AppArmor profiles** | **rejected** | A coding agent exists to run `gcc`, `python`, `git`, `uv`, `npm`. A profile permissive enough for that permits nearly everything, and breaks on every toolchain update. Fails the "easy to maintain" requirement hardest. |
| **Name-based exec interception** | **rejected** | `cp ~/bin/claude ~/bin/foo` defeats it. |

## Who owns resource limits

**Compute nodes: Slurm, and we add nothing.** `cgroup.conf` with
`ConstrainRAMSpace` / `ConstrainCores` / `ConstrainDevices`, plus
`pam_slurm_adopt`, already caps every process in an allocation. Duplicating any
of that here would be a second source of truth for the same numbers. The only
compute-node task in this repo is `pam_slurm_adopt` itself, and it is gated off.

**Login nodes: Slurm cannot help.** A `vscode-server` or `claude-server` on
a login node is not inside an allocation, so there is no job cgroup to
constrain. This is exactly the population that an audit of logins found
invisible to `who` and `last`: users who only ever connect through a remote
IDE.

Before touching that, the installer looks for an existing limiter — an
`arbiter`/`arbiter2`/`cgroup-warden` unit or binary, `/etc/arbiter*`, or any
other drop-in in `user-.slice.d` — and stands down if it finds one, saying what
it found. Two tools managing the same slice is worse than one.

The caps themselves come from the environment, so there is nothing to edit:
`AGENTFENCE_MEMORY_HIGH` (8G), `AGENTFENCE_MEMORY_MAX` (16G), `AGENTFENCE_CPU_QUOTA` (400%),
`AGENTFENCE_TASKS_MAX` (4096), applied to login nodes only, with root exempt.

### Why not Arbiter2

[Arbiter2](https://github.com/CHPC-UofU/arbiter2) is the HPC-community answer
for login-node policing and would be the obvious thing to reuse. It does not
apply here: its `CGROUPS.md` states it uses **cgroups v1 only**, and the last
release is v2.1.0 from April 2022. On a cgroups v2 node it silently does
nothing, which is worse than no limiter at all.

Its successor [Arbiter3](https://github.com/chpc-uofu/arbiter) does support
cgroups v2 and is actively developed, but it is a Django application plus
Prometheus plus a per-node Go [`cgroup-warden`](https://github.com/chpc-uofu/cgroup-warden)
agent, at v0.0.8. It is a better long-term answer than four systemd keys and a
strictly larger operational commitment: it notifies users and escalates through
penalty tiers instead of silently OOM-killing them. If a site adopts it, this
script will detect it and leave the slices alone on its own.

## Bugs in the draft `managed-settings.json` from the thread

These are worth calling out because each one silently produced *no* policy,
with no error:

1. **`#` comments.** JSON has none. The file fails to parse and Claude Code
   falls back to defaults. `tools/validate.sh` checks this.
2. **`Read(/etc/**)` is not an absolute path.** In permission-rule syntax a
   single `/` means *relative to the settings file*, so that rule resolved to
   `/etc/claude-code/etc/**` and matched nothing. Absolute needs a double
   slash: `Read(//etc/**)`.
3. **`$USER` and `!( )` do not expand.** `Read(/home/!(|$USER)/**)` is bash
   extglob plus a shell variable; the rule matcher does neither. The
   "protect other users' homes" rules were inert. Real protection is
   `chmod 700` (Layer A) and `sandbox.filesystem.denyRead` with an
   `allowRead: ["~/"]` re-allow, which is what we ship.
4. **`"defaultMode": "auto"` together with `"disableAutoMode": "disable"`**
   contradict each other.
5. **Over-blocking.** `Bash(curl *)`, `Bash(sh *)`, `Bash(bash *)`,
   `Bash(docker *)`, `Read(/etc/**)` and `Bash(nvidia-smi *)` break ordinary
   HPC work — `nvidia-smi` is read-only. Users hit the wall, install their own
   client in `$HOME`, and you lose the visibility the policy was for. Our deny
   list is 11 entries, all irreversible or shared-blast-radius.

Two settings do most of the work and were missing entirely:

- `sandbox.failIfUnavailable: true` — without it a missing `bwrap` means the
  sandbox is silently skipped with a warning.
- `requiredMinimumVersion` — an older client ignores unknown keys with no
  error, so the whole policy is a no-op on it.

## `pam_slurm_adopt` is not installed by this script

Adopting SSH sessions into the user's Slurm allocation is the right control for
compute nodes, and it is deliberately left out here. Editing `/etc/pam.d/sshd`
can lock every user, root included, out of a node if Slurm is not already set
up for it — that is a change to make by hand, on one node, with a root session
held open, after setting `PrologFlags=contain` in `slurm.conf`.

## Known limits — stated, not hidden

- The `/opt/agentfence/bin` shims are a default, not a boundary. `/usr/bin/copilot`
  still runs unsandboxed. Deliberate; see the threat model.
- cplt has no `/etc` config path, so the site policy is delivered by exporting
  `CPLT_CONFIG=/etc/agentfence/cplt.toml` from `/etc/profile.d`. This reaches every
  account, not just new ones, and `[deny] paths` merges and tightens
  unconditionally. A user can still `unset CPLT_CONFIG`; cplt prints an
  unsuppressable warning naming the file whenever the site policy is active,
  which makes its absence visible.
- The site cplt policy takes the slot of the user's own
  `~/.config/cplt/config.toml`, which is therefore not read while it is
  active. Someone relying on a personal `allow.read` — a private registry, say
  — loses it and has to move that setting into a per-repo config.
- A per-repo config in `~/.config/cplt/local/` **outranks** the site policy and
  can override its scalar settings, `allow_lifecycle_scripts` among them.
  `deny.paths` cannot be unwound that way, because list values only accumulate.
  This is threat 2 again, and in scope only as something to be honest about.
- cplt does not wrap `cursor-server`, and neither does anything else here.
  Cursor's agent is covered only by Layer A.
- cplt sanitises the child environment by default, which conflicts with
  Claude Code's `CLAUDE_CODE_PROCESS_WRAPPER` launcher contract ("dropping
  inherited variables is not allowed"). That is why Claude Code uses its own
  sandbox here rather than being routed through cplt. Do not stack them.
- Layer B1 covers the official client. A user who runs
  `npx @anthropic-ai/claude-code` from `$HOME` gets a client that still reads
  `/etc/claude-code/managed-settings.json`, but a modified client would not.
  Again: threat 2, out of scope.
- The audit rules are tamper-evidence, not control. Full `execve` logging is
  in the rules file, commented out, with a volume warning.
