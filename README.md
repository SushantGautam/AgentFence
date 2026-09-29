# AgentFence

Guardrails for AI coding agents on shared Linux hosts — an HPC cluster, a lab
server, a jump host, anywhere several people share one machine.

Stops an agent doing damage by accident: deleting the wrong files, reading
other people's home directories, cancelling other people's jobs, or taking a
login node down with it.

It writes no sandbox of its own. It switches on and standardises the ones the
agents already ship, and puts ordinary OS limits underneath them.

```bash
sudo ./agentfence          # what would change. Changes nothing.
sudo ./agentfence apply    # make it so. Asks first.
```

That is the whole interface. `apply` writes only what is missing or has been
edited, so it covers first install, upgrades and repairing a node someone has
poked at. Run it as often as you like.

---

## Install

`agentfence` is one self-contained file — bash, coreutils and python3, no
network at run time. Copy it to a node and run it.

**A release artefact**, verified before it runs as root:

```bash
curl -fsSLO https://github.com/SushantGautam/AgentFence/releases/latest/download/agentfence
curl -fsSLO https://github.com/SushantGautam/AgentFence/releases/latest/download/agentfence.sha256
sha256sum -c agentfence.sha256
chmod +x agentfence && sudo ./agentfence apply
```

**From source:**

```bash
make dist && scp dist/agentfence login1:
```

## Use it

```bash
agentfence                 # status: what differs. Exit 0 match, 1 drift, 2 error.
agentfence apply           # make the node match
agentfence config          # the settings in effect, and where each came from
agentfence doctor          # checks, which shims resolve, and cplt doctor
agentfence init            # write out templates you can edit
agentfence uninstall       # remove everything it installed
```

Flags: `--config FILE`, `--policy-dir DIR`, `--nodes "a b c"` (over ssh),
`--yes`, `--role login|compute`, `--no-packages`.

The exit codes make `agentfence || alert` work from cron:

```bash
agentfence --nodes "$(cat nodes.txt)" || mail -s "agent policy drift" you@example.org
```

`doctor` is the one to run when something is not behaving. It repeats the
status checks, then reports which shimmed agents are actually installed on this
machine, then hands over to `cplt doctor` for what only cplt can answer —
Landlock ABI, kernel version, how it resolves each agent.

```console
$ agentfence doctor
Shims
  = copilot  -> /usr/local/bin/copilot
  - goose    not installed here; the shim will say so if run
```

Run it **as the user having the problem**, not under `sudo`: `cplt doctor`
inspects the calling user's `PATH` and `$HOME`, so as root it reports root's
environment rather than theirs. It says so when you do.

## Tell it about your site

Where your shared filesystems live differs per machine, so it is a setting, not
something to edit in a file. `init` writes you a commented template:

```bash
./agentfence init --config ./site.conf
$EDITOR ./site.conf
sudo ./agentfence apply --config ./site.conf
```

| Setting | What it does | Default |
|---|---|---|
| `AGENTFENCE_SITE_NAME` | Named in the banner users see | `This shared machine` |
| `AGENTFENCE_SHARED_HOMES` | Other people's homes: unreadable, `.ssh` denied | none |
| `AGENTFENCE_SHARED_APPS` | Shared software: readable, never writable | none |
| `AGENTFENCE_SHARED_WORKSPACES` | Shared project space agents may read | none |
| `AGENTFENCE_MEMORY_HIGH` / `_MAX` | Memory caps, login nodes only | `8G` / `16G` |
| `AGENTFENCE_CPU_QUOTA` / `_TASKS_MAX` | CPU and PID caps, login nodes only | `400%` / `4096` |
| `AGENTFENCE_SHIM_AGENTS` | Agents that get a cplt shim | `copilot opencode antigravity agy pi goose` |

Each takes a space-separated list, and paths must be absolute. A relative path,
a bare `/`, a wildcard or a `..` is refused before anything is written — each
would widen a narrow rule to cover the whole filesystem.

`AGENTFENCE_SHIM_AGENTS` accepts only names [cplt](https://github.com/navikt/cplt)
can launch — `copilot opencode antigravity agy pi goose dsh` — because the shim
ends in `cplt --agent <name>`. Anything else is refused at install time rather
than failing at a user's prompt. Two notable absences from the default:
`claude`, because Claude Code sandboxes itself and must not be stacked with
cplt, and `dsh`, because that name is also distributed shell on many clusters;
add `dsh` if yours has no such command.

Set `AGENTFENCE_SHARED_WORKSPACES` if your projects live outside `$HOME`.
Anything not listed there cannot be read at all, so without it agents cannot
see their own work.

The same names work as environment variables, with `sudo -E`. **Precedence**,
highest first: `--config`, the environment, `/etc/agentfence/site.env`, the
defaults. `apply` records what you used, so a later bare `agentfence` from cron
compares against the same settings rather than reporting drift against itself.

```console
$ agentfence config
AGENTFENCE_SHARED_HOMES   /shared/home    ./site.conf
AGENTFENCE_MEMORY_MAX     64G             environment
AGENTFENCE_CPU_QUOTA      400%            default
```

## Change the policy

You do not edit this repository and you do not rebuild anything. Point at a
directory of your own:

```bash
./agentfence init --policy-dir ./policy
$EDITOR ./policy/...
sudo ./agentfence apply --policy-dir ./policy --config ./site.conf
```

`init` drops in every shipped file as `<name>.shipped` for reference, plus an
empty overlay and a README. Nothing there is read until you create a real file
next to it:

| To | Create | Effect |
|---|---|---|
| Add audit rules, `PATH` lines, anything line-based | `50-agentfence-audit.rules.append` | Shipped content kept, yours appended |
| Add Claude Code rules | `managed-settings.overlay.json` | Merged into the shipped policy |
| Replace a file outright | `50-agentfence-audit.rules` | Yours wins |
| Install files of your own | `desired-state` | `src:/abs/dest:0644:login,compute:always` per line |

Prefer `.append` and the overlay — a replaced file stops tracking the shipped
one, including later fixes to it.

Two deliberate limits on overlays. They **add but never subtract**: leaving a
shipped rule out does not remove it, because removal should be a visible act
rather than a side effect of a short overlay. And they **cannot switch off
enforcement** — `sandbox.enabled`, `failIfUnavailable`,
`allowUnsandboxedCommands`, `allowManagedPermissionRulesOnly` and
`disableBypassPermissionsMode` are refused before anything is written:

```
agentfence: the overlay sets sandbox.failIfUnavailable to False; it must stay True
```

`agentfence config --policy-dir ./policy` shows which files are shipped,
replaced, appended to or merged.

A `--config` or `--policy-dir` that does not exist is an error, never a silent
fall back to defaults — a typo in a filename must not quietly install a weaker
policy than you asked for.

## What it puts on a node

- A policy file for Claude Code, so an agent cannot read `~/.ssh`, write to
  `/etc` or run `sudo`, and its shell commands run in a sandbox.
- The same for other agents (Copilot, OpenCode, Antigravity, Pi, goose), via
  [cplt](https://github.com/navikt/cplt).
- Per-user memory and CPU caps on **login nodes only**, and only if nothing
  else is already doing that job.
- Audit rules recording any edit to the policy files themselves.

It adds nothing to compute nodes' resource limits — Slurm owns those.

| Lands as | From |
|---|---|
| `/etc/claude-code/managed-settings.json` | `policy/managed-settings.json` |
| `/etc/agentfence/cplt.toml` | `policy/cplt-config.toml` |
| `/etc/agentfence/site.env` | your settings |
| `/etc/audit/rules.d/50-agentfence-audit.rules` | `policy/50-agentfence-audit.rules` |
| `/etc/profile.d/10-agentfence.sh` | `policy/profile.d-agentfence.sh` |
| `/opt/agentfence/bin/` | `policy/bin/agentfence-shim` plus symlinks |
| `/etc/systemd/system/user-.slice.d/` | `policy/50-agentfence-user-limits.conf` |

Undo all of it:

```bash
sudo ./agentfence uninstall
```

bubblewrap and cplt are left installed; removing packages is not this script's
business.

## How far this is tested

CI installs it on a throwaway Ubuntu runner on every push and checks that the
policy that lands is valid and carries your paths, that a second `apply` is a
no-op, that tampering is detected and repaired, and that `uninstall` leaves
nothing behind.

It has **not** run on a real multi-user machine — no real users, no shared
filesystem, no Slurm, and CI installs neither `bwrap` nor `cplt`. The
convergence logic is exercised; the enforcement is not. Treat a first `apply`
on a real node as untested: one node, watched.

## Layout

```
engine/      the code: plan / diff / apply, and the policy renderer
policy/      the base policy - all of this lands on a node
templates/   what `agentfence init` writes out
tools/       build and validate; never shipped
docs/        design notes
```

`engine/` and `policy/` are the source of truth; `dist/agentfence` is a build
artefact and is never edited by hand. The payload inside it is flat, so the
names you use in a `--policy-dir` stay stable however this repository is
rearranged.

## More

- [docs/design.md](docs/design.md) — threat model, architecture, what was
  rejected and why, known limits, and why `pam_slurm_adopt` is not installed
  here.
- [AGENTS.md](AGENTS.md) — rules for anyone, human or agent, changing this
  repository.

## Licence

MIT. See [LICENSE](LICENSE).
