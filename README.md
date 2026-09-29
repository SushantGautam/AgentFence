# AgentFence

Guardrails for AI coding agents on shared Linux hosts — an HPC cluster, a lab
server, a jump host, anywhere several people share one machine.

Stops an agent doing damage by accident: deleting the wrong files, reading
other people's home directories, cancelling other people's jobs, or taking a
login node down with it.

It writes no sandbox of its own. It switches on and standardises the ones the
agents already ship, and puts ordinary OS limits underneath them.

Written for an HPC cluster and generalised from there; hostnames and paths in
the examples are placeholders, so substitute your own. **Not yet run on a
node.** Everything here passes the offline checks in `scripts/validate.sh` and
nothing more — treat a first `apply` as untested, on one node, watched.

## Install

Three ways in. The first is the one to use on a node that matters.

**A release artefact, verified before it runs.** AgentFence runs as root on a
machine shared by many people, so download and verification are deliberately
separate steps from execution:

```bash
curl -fsSLO https://github.com/SushantGautam/AgentFence/releases/latest/download/agentfence
curl -fsSLO https://github.com/SushantGautam/AgentFence/releases/latest/download/agentfence.sha256
sha256sum -c agentfence.sha256       # do this before running anything as root
chmod +x agentfence
sudo ./agentfence                    # shows what would change. Changes nothing.
sudo ./agentfence apply              # makes it so. Asks first.
```

**Built from this repository**, which is the same bytes from the same source:

```bash
make dist                            # one file, plus its .sha256
scp dist/agentfence login1:
ssh login1 'sudo ./agentfence'
```

**With uv**, for a throwaway or test machine:

```bash
uvx --from git+https://github.com/SushantGautam/AgentFence agentfence apply
```

Convenient, and worse in one specific way: uv resolves and fetches from the
network at the moment you run it, and that code then executes as root on the
node. There is no artefact to check first. Use it where a compromise would not
matter, and use the release artefact where it would.

## Run it

Start on one node.

That is the whole thing. Run it with no arguments to see the difference between
what is on the node and what should be; run `apply` to close the gap.

`apply` writes only what is missing or has been edited, leaves everything else
alone, and stops with "nothing to do" if the node already matches. Run it as
often as you like. It is also how you roll out a later change to the policy,
and how you put a file back if someone edits it on the node.

Once you are happy with one node, do the rest:

```bash
sudo ./agentfence apply --nodes "node01 node02 node03" --yes
```

To undo everything: `sudo ./agentfence uninstall`.

### Telling it about your site

Where a site keeps shared home directories, software trees and project space
differs per machine, and there is no sensible default, so these are settings
rather than constants. Pass them once, with `sudo -E` so the variables survive:

```bash
AGENTFENCE_SITE_NAME="Physics cluster" \
AGENTFENCE_SHARED_HOMES="/shared/home" \
AGENTFENCE_SHARED_APPS="/shared/apps" \
AGENTFENCE_SHARED_WORKSPACES="/shared/projects" \
  sudo -E ./agentfence apply
```

| Variable | What it does | Default |
|---|---|---|
| `AGENTFENCE_SITE_NAME` | Named in the banner users see at startup | `This shared machine` |
| `AGENTFENCE_SHARED_HOMES` | Other people's homes: unreadable, and their `.ssh` denied outright | none |
| `AGENTFENCE_SHARED_APPS` | Shared software: readable, never writable | none |
| `AGENTFENCE_SHARED_WORKSPACES` | Shared project space agents are allowed to read | none |
| `AGENTFENCE_MEMORY_HIGH` / `_MAX` | Soft and hard memory caps, login nodes only | `8G` / `16G` |
| `AGENTFENCE_CPU_QUOTA` / `AGENTFENCE_TASKS_MAX` | CPU and PID caps, login nodes only | `400%` / `4096` |

Each takes a space-separated list, and every path must be absolute. A relative
path, a bare `/`, a wildcard or a `..` is refused before anything is written —
those would silently turn a narrow rule into one covering the whole filesystem.

`AGENTFENCE_SHARED_WORKSPACES` matters more than it looks. `allowManagedReadPathsOnly`
is on, so a directory not listed there cannot be read at all: without it,
agents on a site whose projects live outside `$HOME` cannot see their own work.

`apply` records what you passed in `/etc/agentfence/site.env` and reads it back
on later runs, so a bare `agentfence` from cron compares against the same
settings instead of reporting drift against itself. To change a value, re-run
`apply` with the new one in the environment.

Memory and CPU caps work the same way:

```bash
AGENTFENCE_MEMORY_MAX=32G AGENTFENCE_CPU_QUOTA=800% sudo -E ./agentfence apply
```

Run with no arguments from cron to be told when a node drifts — it exits 0 if
the node matches and 1 if it does not:

```bash
agentfence --nodes "$(cat nodes.txt)" || mail -s "agent policy drift" you@example.org
```

### What it puts on a node

- A policy file for Claude Code, so an agent cannot read `~/.ssh`, write to
  `/etc`, or run `sudo`, and its shell commands run inside a sandbox.
- The same for other agents (Copilot, OpenCode, goose), using cplt.
- A cap on how much memory and CPU one person can use on a login node — only
  if nothing is already doing that job.
- Audit rules that record it if someone edits the policy files.

It does not touch compute nodes' resource limits. Slurm already handles those.

---

## Threat model (read this first)

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
not yet measured — see the note at the top.

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
   falls back to defaults. `scripts/validate.sh` checks this.
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

## Layout

```
files/                          what gets installed on a node
  managed-settings.json         -> /etc/claude-code/managed-settings.json
  cplt-config.toml              -> /etc/agentfence/cplt.toml   (read via $CPLT_CONFIG)
  profile.d-agentfence.sh       -> /etc/profile.d/10-agentfence.sh
  bin/agentfence-shim            -> /opt/agentfence/bin/{copilot,opencode,goose}
  50-agentfence-user-limits.conf       -> /etc/systemd/system/user-.slice.d/
  50-agentfence-root-exempt.conf       -> /etc/systemd/system/user-0.slice.d/
  50-agentfence-audit.rules           -> /etc/audit/rules.d/

scripts/
  installer-template.sh         the installer, minus its payload
  build-installer.sh            `make dist` - embeds files/ into the template
  validate.sh                   checks the config files before a build

dist/agentfence          the built installer. Not in git.
```

`files/` is the only source of truth. The installer carries a copy of it as an
embedded payload, so changing a config file and running `make dist` is all
there is to releasing a new version. Never edit `dist/agentfence`.

## Rollback

```bash
sudo ./agentfence uninstall --nodes "node01 node02 node03"
```

It removes every file it installed and reloads systemd and the audit rules.
bubblewrap and cplt are left installed, since removing packages is not this
script's business.

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
