# Moving ORRERY instructions to the user scope

[日本語](../instruction-migration.md)

<a id="what-changes"></a>
## What changes

Claude uses `$CLAUDE_CONFIG_DIR/CLAUDE.md`, defaulting to `~/.claude/CLAUDE.md`. Codex keeps `$CODEX_HOME/AGENTS.md`, defaulting to `~/.codex/AGENTS.md`. Mail remains in legacy mode with activation=false. There is no additional participation flag.

Follow the block only when ORRERY Mail tools exist. Participation uses an already resolved identity or session-bound runtime binding. A bare session without one skips Mail registration and notifications. Editing guards remain independent: `AGENTSTACK_UNMANAGED_SESSION_POLICY` still defaults to block and supports explicit warn-open. A registration flag without a binding, or a Desktop registration in progress/retry/degraded state, is unresolved rather than unrelated. Recover the same identity; never create an alias.

| Before | Now |
|---|---|
| Claude defaults to project CLAUDE.md | User CLAUDE.md; explicit project/both returns `INSTRUCTION_SCOPE_REQUIRES_MIGRATION` |
| Bare model performs raw route 5 registration | Start through `agent-start <workdir>` or `agent-start-codex <workdir>`; replace personal pending-* launchers with these |
| CLAUDE_HOME selects output | Actual provider input CLAUDE_CONFIG_DIR; a different CLAUDE_HOME returns `INSTRUCTION_HOME_CONFLICT`; launch environments are not rewritten |
| awk reconstructs the whole file | Only marker spans change; outside bytes, BOM and line endings survive |
| Write through hardlinks | Migration targets/sources with nlink>1 return `INSTRUCTION_HARDLINK_REQUIRES_MANUAL_COPY`; symlinks retain their pinned chain and same-owner referent |

Normal launchers resolve an existing identity before execution. If both candidate selection and registration fail to return a name, launch stops with `LAUNCH_IDENTITY_UNAVAILABLE`. Desktop lifecycle hooks keep saving their existing binding before registration. A cockpit split creates a shell, not an agent identity. Personal shell configuration and external warm-pool implementations are not automatically changed.

<a id="legacy-blocks"></a>
## Legacy blocks

Different versions loaded together can contradict each other. Detection walks only cwd and its parents for CLAUDE.md/AGENTS.md, never siblings or all of HOME. Doctor reports counts, files, hashes and cleanup commands. SessionStart emits only a count and an operator-facing doctor hint. A later UI change will link directly to both language versions of this page.

On update, the previous project key from `env.sh` and the current project folder are also candidates. New instructions use the current key; each old-block proof records the actual matched render key. There is no saved inventory of every past folder and no broad scan. Run doctor in those working folders or select an explicit `--path`.

```sh
agentstack-claude-setup --check
agentstack-codex-setup --check
agentstack-claude-setup --plan --json
```

Plan creates no file or lock. Its `apply_argv` carries the same source selection and plan ID; another process recomputes and compares them. An ID alone cannot reconstruct source selection.

<a id="consent"></a>

## Consent

The installer has up to four approval sites: settings merge, MCP entry, and the Codex and Claude blocks. Settings/MCP changes require typed `yes`. Block confirmation follows the single contract below. A non-interactive installer without advance approval skips these setup steps with warnings. Direct setup CLI creation needs no confirmation as described below. Reusing a running Mail needs no extra approval.

Creating a new user file without changing existing files needs no confirmation. Rewriting an existing file or removing a source block requires confirmation.

One interactive prompt asks whether to move instructions and remove known source blocks (`[Y/n]`; Enter removes), explaining shared-repository effects and full-file backup retention. Explicit `--assume-yes` removes only known untracked sources; tracked or unknown Git status remains with a warning. Edited, unknown or malformed blocks stay for a local diff and manual marker-only cleanup. There is no force override. The user target is verified before any source removal.

Review the plan and run the command shown in `apply_argv` in your terminal. If you append `--json`, a completed migration reports the stage and target file.

```json
{"stage": "complete", "target_path": "<user-config>/CLAUDE.md"}
```

```sh
agentstack-claude-setup --remove-legacy-block --path /work/repo/CLAUDE.md --dry-run
agentstack-claude-setup --remove-legacy-block --path /work/repo/CLAUDE.md
```

Ancestor AGENTS.md files are detect-only unless selected explicitly by `--path`. Symlink chain and referent are rechecked. For hardlinks, back up all aliases yourself, review their uses, replace the chosen target with an independent regular copy, then re-plan. The engine neither discovers aliases nor severs links.

Cooperative engines in one installation serialize on the pinned referent path mutex. Non-cooperative writes under the same UID can race between the last comparison and rename. Detected changes stop the operation and retain backups.

<a id="interrupted-migration"></a>
## Interrupted migration

The single receipt is `<install>/backups/instruction-migration/<provider>/<target hash>/receipt.json`; install-state stores only its reference. Originals use `backups/<plan ID>/<resolved path hash>.before`, so multiple sources cannot overwrite one backup.

| Stage | Recovery |
|---|---|
| Plan / before consent | Nothing saved; plan again |
| planned / backed_up | `--resume --plan-id ID`; reuse only matching backups |
| writing / after rename | Accept matching before/after bytes and metadata; refuse unknown changes |
| target_verified / sources_pending | Recheck target before each remaining source |
| complete | Same content is a no-op; a new template gets a new plan/history |
| Unknown bytes / changed HOME | Restore environment or explicitly re-plan |

`--replan --expected-plan-id OLD --json` is read-only. Apply its `--apply --plan-id NEW --supersede-plan-id OLD ...` with the same selection and human consent. Assume-yes cannot replace pending work. Previous receipts/backups remain in history. Outside edits do not prevent the next template generation or uninstall.

<a id="custom-provider-home"></a>
## Child and dedicated provider HOME

Legacy Codex children read the existing AGENTS symlink without writing through it. Global fixed provider HOME instructions are generated by explicit operator configure using the common renderer. Normal launch is read-only and refuses missing/stale instructions with `INSTRUCTION_PROVIDER_CONFIG_REQUIRED`.

```sh
agentstack-runtime-client instruction-configure operator claude
agentstack-runtime-client instruction-configure operator codex
```

These generated files have no user-migration receipt. Claude settings and Codex trust retain their existing explicit configuration flows; this command cannot approve Codex trust. Pending work under a changed HOME returns `INSTRUCTION_HOME_CHANGED`; restore the recorded HOME before resume.

<a id="uninstall"></a>
## Uninstall and backups

Setup `--uninstall` and normal uninstall remove only recorded marker spans. Edited blocks remain with a warning. User files are never owned_files. Private full-file backups, receipts and history remain.

Before deleting anything, `agentstack-uninstall --purge-data` checks pending work, edited blocks and retained sources. Any unresolved item returns `INSTRUCTION_BACKUP_PURGE_BLOCKED`. Manually removed retained spans can be resolved by checking their present absence. Only after everything is resolved does purge remove the fixed ledger and full-file backups. There is no automatic backup GC.

`--remove-legacy-block --path X` cleans up X only. If the current user block is missing or changed, `INSTRUCTION_TARGET_REQUIRES_SETUP` directs the user to setup first. Other sources and the user target remain unchanged. Edited or unknown sources get local-diff/manual marker-only review guidance instead of an ineffective cleanup command.

Purge checks sources recorded in all current and history receipts, keeping backups while an older marker remains. Normal uninstall keeps unsafe files (including changed symlinks or hardlinks), warns, and continues with the remaining files. Purge stops on these conditions.

Automatically discovered files without markers are not migration sources; hardlinked files of this kind remain untouched and are skipped. Targets, explicit `--path` files, and sources containing markers retain strict hardlink refusal.

Purge uses the same receipt reader for current/history schema, kind, and canonical plan hash validation. A mismatch returns `INSTRUCTION_PLAN_CHANGED` before deletion and keeps the ledger/backups. Restore a verified receipt before retrying; do not bypass the check by manually changing its hash.

The isolated global dashboard uses this same detector and finding definition. Unknown fixed provider HOME or session cwd is shown as unknown, never inferred from the dashboard operator’s HOME. Session start records only candidate paths, block hashes and versions. A session whose earlier candidates changed still gets a restart notice when disk cleanup is complete. This does not prove effective instruction loading. See [screen inspection and Dismiss](dashboard.md#global-mail-view).

Emitted cleanup commands include `env HOME=... CLAUDE_CONFIG_DIR=... CODEX_HOME=... AGENTSTACK_HOME=...` and related detection settings, retaining the same target and ledger even in another terminal. Keep these assignments. A missing current block in the detected provider HOME yields `INSTRUCTION_TARGET_REQUIRES_SETUP`; a block in another HOME cannot substitute for it.
