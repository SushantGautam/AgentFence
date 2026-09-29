# AGENTS.md

Instructions for AI coding agents working in this repository.

## What this repository is

AgentFence is configuration that constrains AI coding agents on shared Linux
hosts, written for an HPC cluster and meant to suit any multi-user machine. It
ships no application code beyond a build helper. Every file here lands on a
shared node as root, so a mistake affects everyone with an account at once.

Read `README.md` before changing anything. In particular the **Threat model**
section: this project deliberately does *not* defend against a user who wants
to bypass it, and changes that argue otherwise have been considered and
rejected.

## Hard rules

1. **Never run `git add -A`, `git add .`, or `git commit -a` here.** This
   directory lives inside the user's home-directory git repository. Stage
   explicit paths only.
2. **Do not widen the deny list in `policy/managed-settings.json` without a
   stated reason.** Over-blocking is a documented failure mode: users hit the
   wall, install an unmanaged client in `$HOME`, and the policy loses the
   visibility it existed for. The list is 11 entries and should stay short.
3. **Do not write a new sandbox.** Bubblewrap wrappers, seccomp filters,
   AppArmor profiles and exec-interception schemes are all out of scope and
   were rejected with reasons in `README.md`. Use Claude Code's built-in
   sandbox and `navikt/cplt`. Before adding any mechanism, check whether the
   upstream tool already exposes it — `CPLT_CONFIG` replaced a hand-rolled
   `/etc/skel` seed here, and cplt's own docs are the source of truth:
   `https://github.com/navikt/cplt/tree/main/docs`.
4. **Do not add `pam_slurm_adopt` to this installer.** Editing `/etc/pam.d/sshd`
   can lock every user, root included, out of a node. It is a by-hand change,
   documented in `README.md`, and it stays out of anything automated.
5. **Do not make the installer chmod users' home directories.** Reporting that
   they are world-readable is fine; changing them behind an admin's back is not.
6. **Never put a real hostname or filesystem path in this repository.** It is
   public. Site layout is configuration — `AGENTFENCE_SHARED_*`, recorded in
   `/etc/agentfence/site.env` — and examples use placeholders. This rule
   exists because real paths were committed once and had to be removed.
7. **Do not build the policy JSON with `sed`.** Deleting the last element of a
   JSON array leaves a trailing comma, the file stops parsing, and an
   unparseable `managed-settings.json` is ignored *silently* — the node looks
   configured and enforces nothing. Use `engine/render-settings.py`.
8. **Do not call `die` inside `$(...)`.** It exits only the subshell, so the
   run carries on with an empty value. Fail before the substitution.
9. **Do not add compute-node resource limits.** Slurm's `cgroup.conf` owns
   those. Anything here would be a second source of truth for the same numbers.
   Login nodes are the exception, and only when the probe finds no existing
   limiter — never unconditionally.

## Before you claim a change works

`tools/validate.sh` must pass. Run it after every edit to
`policy/managed-settings.json` or `engine/installer-template.sh`:

```bash
./tools/validate.sh
```

It catches the four failure modes that produce *silently empty* policy:

- JSON that does not parse (a `#` comment kills the whole file)
- single-slash paths in permission rules — `/etc/**` means "relative to the
  settings file", absolute needs `//etc/**`
- `$VAR` or bash extglob `!( )` in rules, neither of which expands
- missing `sandbox.failIfUnavailable`, `allowUnsandboxedCommands: false`,
  `disableBypassPermissionsMode`, `allowManagedPermissionRulesOnly` or
  `requiredMinimumVersion`

`validate.sh` also parses the installer template, both shipped shell files
(POSIX `sh`, not bash) and the TOML, so it covers every file in the repo. It
additionally runs `engine/render-settings.py` with no site paths, with a full
set, and with input that must be refused — that renderer builds JSON on the
node, where `validate.sh` never runs, so it is exercised here instead.

None of this proves behaviour on a node. CI goes one step further and applies
the installer on a disposable Ubuntu runner, so convergence, drift repair and
uninstall are covered. Neither proves enforcement: no runner has `bwrap` or
`cplt` installed, no runner has other users. Do not report a change as verified
against a real multi-user host on the strength of either — say plainly what was
run and what was not.

## Settings-schema changes

`policy/managed-settings.json` is validated against
`https://json.schemastore.org/claude-code-settings.json`. Keys are added and
renamed over time, and **an unknown key is ignored with no error**, so a typo
is indistinguishable from a working setting at runtime. Before adding a key,
confirm it exists in the live schema:

```bash
curl -sfL https://json.schemastore.org/claude-code-settings.json \
  | jq '.properties.sandbox.properties | keys'
```

If a new key requires a newer client, raise `requiredMinimumVersion` in the
same change, or older clients silently ignore it.

## Vocabulary

Use these words consistently — in docs, comments and error messages.

| Term | Means |
|---|---|
| **engine** | The installer logic: plan, diff, apply. Site-independent. `engine/` |
| **base policy** | The files AgentFence ships that land on a node. `policy/` |
| **site policy** | An admin's `--policy-dir`, layered over the base policy |
| **settings** | The `AGENTFENCE_*` values |
| **site config** | A `--config` file, or `/etc/agentfence/site.env` on a node |
| **payload** | The base64 tar appended to the installer after `__PAYLOAD__` |

`policy/` here and `--policy-dir` on a node are deliberately the same word:
one is the base, the other is laid over it.

## Layout and where a change belongs

```
engine/      the code: plan/diff/apply, and the policy renderer
policy/      the base policy - exactly what lands on a node, nothing else
templates/   what `agentfence init` hands an admin
tools/       build and validate; never shipped
```

Nothing but base policy goes in `policy/`. It used to also hold the renderer
and the settings template, which made "everything here lands on a node" false
and hid two very different kinds of file among the policy.


| Change | File |
|---|---|
| Claude Code policy | `policy/managed-settings.json` |
| CPU/RAM/PID caps | `policy/50-agentfence-user-limits.conf`, values from settings |
| A new site setting | `SETTINGS` in `engine/installer-template.sh`, plus `templates/agentfence.conf.example` and the README table |
| Which agents get a cplt shim | `AGENTFENCE_SHIM_AGENTS`, a setting |
| Site-wide cplt policy | `policy/cplt-config.toml`, delivered as `$CPLT_CONFIG` |
| Shim behaviour | `policy/bin/agentfence-shim` |
| Audit rules | `policy/50-agentfence-audit.rules` |
| Installer behaviour | `engine/installer-template.sh`, built by `make dist` |
| How site paths enter the policy | `engine/render-settings.py` |
| CI and releases | `.github/workflows/` |

No site's real hostnames or filesystem paths belong in this repository. They
are settings — `AGENTFENCE_SHARED_HOMES`, `AGENTFENCE_SHARED_APPS`,
`AGENTFENCE_SHARED_WORKSPACES` — recorded per node in
`/etc/agentfence/site.env`. Examples use placeholders (`/shared/home`,
`login1`, `node01`). Do not replace a placeholder with a real path.

## How the installer is put together

`policy/` and `engine/` are canonical. `dist/agentfence` is a build artefact
produced by `make dist`, which stages the payload and appends it base64-encoded
after a `__PAYLOAD__` marker. **Never edit `dist/agentfence`** — edit the
source and rebuild.

The payload is assembled **flat**, whatever the repository layout is. Those
flat names are a public interface: a site override is
`50-agentfence-audit.rules.append`, never `policy/50-…`. Reorganising the
repository must not change what an admin types, so if you move something in
`policy/`, keep its basename. `make dist` runs `validate.sh`
first and refuses to build if it fails.

The installer is convergent, in three steps that share one data structure:

- `build_plan` diffs the `DESIRED_STATE` table against the node into `PLAN`
- `print_plan` renders `PLAN`
- `execute_plan` carries out `PLAN`

So what the user is shown is exactly what runs. Adding a file means adding a
row to `DESIRED_STATE`, not a new branch. A file that is only wanted under some
condition names a predicate function in the last column (`always`,
`no_existing_limiter`).

There are two verbs — bare (status) and `apply` — because applying an unchanged
node is already a no-op, so one verb covers first install, upgrade and drift
repair. Do not reintroduce a separate sync, force or reinstall command; new
behaviour belongs in the plan.

Exit codes are part of the interface: 0 matches, 1 drifted, 2 failed. `status`
is what someone runs from cron, so do not make it exit 0 on drift.

## Style

Terse. Comments in the config files explain *why*, since a sysadmin reading
`/etc/claude-code/managed-settings.json` on a node has no access to this
README. Every file that gets deployed carries a
`# Managed by agentfence` header so nobody edits it in place.

State limitations rather than hiding them — `README.md` has a "Known limits"
section and new gaps belong there, not in a commit message.
