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
2. **Do not widen the deny list in `files/managed-settings.json` without a
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
   configured and enforces nothing. Use `files/render-settings.py`.
8. **Do not call `die` inside `$(...)`.** It exits only the subshell, so the
   run carries on with an empty value. Fail before the substitution.
9. **Do not add compute-node resource limits.** Slurm's `cgroup.conf` owns
   those. Anything here would be a second source of truth for the same numbers.
   Login nodes are the exception, and only when the probe finds no existing
   limiter — never unconditionally.

## Before you claim a change works

`scripts/validate.sh` must pass. Run it after every edit to
`files/managed-settings.json` or `scripts/installer-template.sh`:

```bash
./scripts/validate.sh
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
additionally runs `files/render-settings.py` with no site paths, with a full
set, and with input that must be refused — that renderer builds JSON on the
node, where `validate.sh` never runs, so it is exercised here instead.

None of this proves behaviour on a node. Only running `agentfence` on
it on a real node does. Do not report a change as verified on the strength of
the offline checks alone — say plainly that it has not been run.

## Settings-schema changes

`files/managed-settings.json` is validated against
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

## Layout and where a change belongs

| Change | File |
|---|---|
| Claude Code policy | `files/managed-settings.json` |
| CPU/RAM/PID caps | `files/50-agentfence-user-limits.conf`, values from `AGENTFENCE_*` env vars |
| Which agents get a cplt shim | `SHIM_AGENTS` in `scripts/installer-template.sh` |
| Site-wide cplt policy | `files/cplt-config.toml`, delivered as `$CPLT_CONFIG` |
| Shim behaviour | `files/bin/agentfence-shim` |
| Audit rules | `files/50-agentfence-audit.rules` |
| Installer behaviour | `scripts/installer-template.sh`, built by `make dist` |
| How site paths enter the policy | `files/render-settings.py` |
| uvx entry point | `pyproject.toml`, `python/` |
| CI and releases | `.github/workflows/` |

No site's real hostnames or filesystem paths belong in this repository. They
are settings — `AGENTFENCE_SHARED_HOMES`, `AGENTFENCE_SHARED_APPS`,
`AGENTFENCE_SHARED_WORKSPACES` — recorded per node in
`/etc/agentfence/site.env`. Examples use placeholders (`/shared/home`,
`login1`, `node01`). Do not replace a placeholder with a real path.

## How the installer is put together

`files/` is canonical. `dist/agentfence` is a build artefact produced by
`make dist`, which embeds `files/` as a base64 payload appended after a
`__PAYLOAD__` marker. **Never edit `dist/agentfence`** — edit `files/`
or `scripts/installer-template.sh` and rebuild. `make dist` runs `validate.sh`
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
