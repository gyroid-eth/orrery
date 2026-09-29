# Roster findability design memo

> Japanese is the source of truth: [日本語版](../DESIGN_roster_findability.md)

> Status: discussion draft (design only; implementation decisions are not final)  
> Scope: the left-pane roster in `bridge/cockpit.html`  
> Investigated: 2026-08-06

## Conclusion

The problem to solve is not merely whether the description line should show `live` or `task`. **The real issue is that there is no source of truth for what an agent is "currently doing," and display, search, and spawn/registration each adopt different information.**

In the short term, the display descriptor and the search target should be built from the same function. In the medium term, every path, including app spawn, should carry `task_summary`, `role`, `parent`, and `origin`, moving to a contract in which the current work no longer has to be guessed from the latest inbox subject or the pane title. `observed_active` helps in looking for "recently touched agents," but it is not a substitute for identity.

## Re-measurement

### Method and constraints

- Target commit: `d452712`
- Telemetry snapshot: 2026-08-06 15:33:09 JST (`curl http://127.0.0.1:8791/telemetry/agents`)
- 36 agents were extracted under the same condition as the roster, `(running || category === 'agent') && category !== 'warmup'`.
- `GLYPH_STRIP`, the description-line selection in `paintTile()`, and the hay of `rosterNameMatches()` were copied from the source as is into a Node aggregation script and applied to the same snapshot.
- Headless Chrome could not be started, and the in-app Browser could not obtain permission to access localhost. So the values below are not counts taken from screenshots but a **source-aligned replay**: the current display and search functions applied to real data.

The population and the time differ from the 37 agents at the time of the request, so absolute numbers do not match. We prioritized being able to re-measure over copying fixed values.

Afterwards, CuriousCopernicus re-checked the same 36 agents using the real DOM `.statetext` and the real `rosterNameMatches()`. `displayIndexParity 3/36`, `collisionExposure 22/36`, `maxGroup 13`, and `claude-agent-stack: displayed 7 / hits 1 / overlap 0` all matched. Below, the source-aligned replay is treated as a baseline verified against the real UI.

### Results

| Aspect | This time | Judgment |
| --- | ---: | --- |
| Roster targets | 36 agents | Changed from 37 at the time of the request |
| `task` non-empty | 36/36 | The problem is not the absence of a task but how it is used and its content quality |
| Valid `live` non-empty | 34/36 | For 34 agents, `live` occupies the description line |
| `task` shown on the description line | 2/36 | Only CuriousCopernicus and SnowyDirac, whose `live` was empty |
| role non-empty | 17/36 | 19/36 (52.8%) are empty |
| instruction subject non-empty | 33/36 | Coverage is high, but it is the latest mail and not necessarily the current assignment |
| Distinct description-line strings | 17 kinds across 36 agents | Only 14/36 (38.9%) are individually unique |
| Agents belonging to a duplicated string | 22/36 (61.1%) | The largest duplicate group has 13 agents |
| Searching for the displayed description line by exact match returns oneself | 3/36 (8.3%) | The display and search contracts are separate |

The top duplicates were as follows.

| Description line | Agents displaying it | Hits in current search | Of those, agents actually displaying it |
| --- | ---: | ---: | ---: |
| `<vault-directory>` | 13 | 1 | 1 (WhiteFermi) |
| `claude-agent-stack` | 7 | 1 | **0** |
| `Claude Code` | 2 | 0 | 0 |

The search hit for `claude-agent-stack` was ProOpus. That is because the word is in ProOpus's task; none of the 7 agents whose description line shows the word remain in the search results. It is not simply "7 displayed, 1 found": **even that one agent is a different set from the one a user would see and search for.** Of the 22 agents in the top three duplicate groups, only WhiteFermi (1 agent, 4.5%) could be correctly recovered from the displayed word.

### Checking the five points of the request

1. **Hiding of the task by `live` was reproduced.** This time `live` took priority for 34/36 agents. So "the task never appears" is not an invariant that always holds; this time the task appeared for 2 agents. The underlying priority problem remains, however. The top three strings alone accounted for 22/36 agents (61.1%).
2. **The mismatch between visible words and search targets was reproduced, and was worse than expected.** The hay is name/model/provider/cmd/role/task and does not include `live`. Exact-match search of the displayed description line recovered the agent itself for only 3/36.
3. **The problem of task content quality was also reproduced.** Judging a task as transport-only when "it does not include the work target, deliverable, or decision content, and only states the session's location or the canonical/inbox handoff" gave 13/36 agents (36.1%). The judged agents are CrispOstwald, WhiteFermi, WildDirac, SnowyDirac, SnugGalileo, SpryVesalius, RedLovelace, SandyPlanck, SleekMendeleev, SmartGauss, PureLovelace, PolarBell, and CyanArrhenius. This is a manual classification that includes borderline cases, so the figure of 13 is open to dispute, and the judging vocabulary must be fixed and measured continuously.
4. **Missing role was reproduced.** This time 19/36 agents (52.8%) were empty. The count of individuals differs from 21/37 at the time of the request, but the trend of about half is the same.
5. **The disappearance of non-matches was confirmed in code.** With `.agent.filtered-out { display:none }` and `classList.toggle('filtered-out', !visible)`, a query with zero results hides 36/36 agents. However, this is not an independent root cause. That a filter hides non-matches is normal behavior; the problems are that false negatives from (2) hide even the intended target, and that the reason for zero results and the means of recovery are weak. Leaving all non-matches faintly visible would bring back the scanning load at a scale of 37 agents.

### Follow-up check on the parent cue

In CuriousCopernicus's graph follow-up, of the 13 agents in the cwd-collision group, 7 have a spawn parent, and 4 of those 7 were concentrated on GrandLamarr. Also, `parent` is not in each row of `/telemetry/agents`; a join with the spawn edges of `/telemetry/graph` was needed.

So parent is a useful search cue but cannot serve alone as a secondary fallback.

- Coverage stays at 7 of 13 agents.
- It does not distinguish sibling spawns under the same parent.
- It cannot be rendered from the roster payload alone, so a design that degrades on graph fetch failure or update lag is needed.

Parent is not shown all the time; it is used in `parent:` queries and in hover/detail. The secondary fallback should be a composite of role, origin, an identifiable cwd, and the like.

## Redefining the problem

The left pane needs three kinds of findability.

1. **Recognition:** scan the list and tell "this agent is on that job."
2. **Recall:** type a fragment you remember, such as the task, role, parent, or project, and narrow down to the target.
3. **Recovery by recency:** when you remember neither the name nor the job, return to the most recently active agent.

Today these are separate contracts: the scientist name is the stable identity, the pane title is the primary description, task/role are search keys, and `observed_active` is the ordering. In particular the pane title is "a short line currently visible in the terminal" or the cwd, and is not an assignment identity. The task is free text entered at registration, so transport-only text gets mixed in. The instruction is the latest inbox subject, and completion reports and reservation releases also come in, so it cannot be the source of truth for current work.

So comparing `task || live` with `live || task` alone does not solve it. What is really needed is the following shared contract.

```text
agent identity
  stable: name
  current work: normalized descriptor + provenance + updated_at
  context: role / parent / origin / cwd
  recency: observed_active
  search: the same vocabulary as the rendered fields + explicit structured tokens
```

## Design options

### Option A: fix only the priority and the search hay

Make the description line `task || live || last_active_rel`, and add `live` and `instruction.subject` to the search hay. Also add a zero-results display and a clear action.

Advantages:

- It works with the existing payload and the scope of change is small.
- A displayed task becomes searchable.
- The state where only the cwd is shown for 13 agents in a row is greatly reduced.

Disadvantages:

- The 13 transport-only tasks come to the front.
- `instruction.subject` is not necessarily the current assignment, and completion reports and old requests also hit.
- Adding `live` to the hay alone leaves 13 agents under `<vault-directory>`, so searchability rises but discriminating power does not.
- The structure of editing display and search separately remains, so they will drift again.

This option is reasonable as a hotfix but should not be treated as complete.

Also, Option A should not be released alone ahead of the rest. Unless it is placed in the same release boundary as the quality display described later, transport-only tasks would appear to be "useful descriptions."

### Option B: create a common roster descriptor

Create one view model that both display and search use.

```text
descriptor.primary    the current concrete work (one line)
descriptor.secondary  role · parent, or an identifiable cwd
descriptor.recency    relative time of observed_active
descriptor.tokens     the words actually rendered in primary/secondary + the stable name
descriptor.provenance explicit-assignment | task | instruction | live | fallback
descriptor.quality    specific | generic | missing
```

Candidates are chosen not by a fixed priority of fields but by provenance and quality.

1. If an explicit current assignment is specific, make it the primary.
2. If the existing task is specific, use it.
3. Use the instruction only when it is a task-like subject and can be confirmed to be the current assignment. The mere latest inbox is not used.
4. Use live only when it looks like work content, excluding generic values such as the cwd basename, the agent name, and `Claude Code`.
5. If there is no specific primary, explicitly show `Needs description` and do not make a generic task look useful.

For the secondary, prefer role; if there is none, parent/origin; and lastly the cwd. For the cwd, compute not just the basename but the shortest difference after removing the common prefix, and do not show it if there is no difference. `observed_active` is not material for the primary; it is used for tertiary information such as `active 3m ago` and for ordering.

Parent becomes a candidate only when the graph join succeeds and a value exists. When it is missing, do not fill it with `—`, root, the current time, or other guesses.

The filter can in principle stay `display:none`. However, the displayed primary/secondary must always be in the tokens, and when there are zero results, show `0/36 · Clear · searched: task, role, parent, cwd`. If needed, add structured queries such as `parent:Name`, `role:critic`, `cwd:orrery`, and `active:<10m`.

Advantages:

- The structure guarantees that "visible words are searchable."
- It degrades according to information quality rather than a task-or-live choice.
- The provenance/quality of the descriptor can be counted in telemetry.
- The same contract can later be reused for the palette and Split cells.

Disadvantages:

- If the quality judgment starts with heuristics only, it will misjudge by language, proper nouns, and short but useful tasks.
- If the primary switches automatically too often, the position in the list and the label will not settle.
- As long as the current assignment is not in the payload, the ceiling on guessing remains.

### Option C: create identifying information at app spawn / registration

Introduce a current-assignment contract in the spawn path.

Required or automatically validated items:

| field | Meaning |
| --- | --- |
| `task_summary` | A short current work that includes the target or deliverable. Warns on transport-only text such as `Read inbox` |
| `role` | The role within the same task. Even where empty is allowed, missing is made visible |
| `parent` | The spawn parent. Tied to the lineage of the existing graph |
| `origin` | delegate / app / CLI / warm-pool claim, and so on |
| `assignment_id`, `updated_at` | Separate the latest mail from the current assignment |

The user does not need to type long text on the app side. The seed of the summary is built from the spawn prompt, the parent's request subject, and the selected project. The owner of the source of truth for `task_summary` is the agent itself, which updates it once right after reading the inbox. So that an old summary is not made to look fresh, `updated_at` is required, and an unset value is not filled with the current time or `0`. A descriptor older than the assignment's update is made explicitly stale by a faint text style and a display such as `updated 3h ago`.

Advantages:

- The transport-only layer, which display-side guessing cannot fix, is reduced at its source.
- With parent/origin, an agent can be found from its spawn context even without remembering its name.
- The history of assignments can be distinguished from the current value.

Disadvantages:

- Changes are needed across multiple paths: app, delegate, CLI, Agent Mail registration.
- Strongly required input slows spawn and increases low-quality strings that merely fill in the format.
- Existing agents need a backfill, and old and new mix during a staged migration.

## Measuring the `descriptor.quality` heuristic

To see the cost-effectiveness of Option B, a measurement judge was applied to the `task` of the same 36-agent snapshot. The canonical judge lives in [`tools/descriptor_quality_probe.py`](../../tools/descriptor_quality_probe.py). It is a read-only probe using only the standard library, not the main implementation.

```bash
# Measure the current :8791 under the same conditions as the cockpit roster
python3 tools/descriptor_quality_probe.py --list generic

# Measure a fixed snapshot and the non-running holdout
python3 tools/descriptor_quality_probe.py --json agents.json --population roster
python3 tools/descriptor_quality_probe.py --json agents.json --population non-running --list specific
```

### Judging rules

1. After NFKC normalization and trim, if empty, it is `missing`.
2. Remove absolute paths, known agent names of 4 or more characters, and coordination ticket IDs such as `PR-B0`. Names shorter than 4 characters are not removed, so that a short agent name does not break parts of `execute` or `inbox`.
3. Remove English and Japanese relay vocabulary. Examples: `canonical`, `inbox`, `awaiting`, `read`, `execute`, `task`, `parent`, `正本`, `タスク`, `届く`, `経由`, `委任`, `実行`.
4. If the residue after removing punctuation and whitespace is 4 or more characters, it is `specific`; otherwise `generic`.

The intent is not to enumerate 13 known sentence patterns but to measure **whether a work target or deliverable remains after removing the location, the agent name, and the handoff mechanism.**

### Results

| quality | heuristic | manual classification | Difference |
| --- | ---: | ---: | ---: |
| `specific` | 23/36 (63.9%) | 23/36 | 0 |
| `generic` | 13/36 (36.1%) | 13/36 | 0 |
| `missing` | 0/36 | 0/36 | 0 |

The confusion matrix was: generic true positives 13, false positives 0, false negatives 0, specific true negatives 23. The residue of all 13 generic agents was 0 characters, and the smallest residue among specific was PlumFeynman's `origamidesign`, 13 characters. In this snapshot the distribution does not change even when the threshold is moved within the range of 1 to 13 characters.

### Non-running holdout

After fixing the vocabulary and threshold in the code above, the 298 agents with `running === false` in the same telemetry payload were measured once as a holdout.

| quality | roster, 36 agents | non-running, 298 agents |
| --- | ---: | ---: |
| `specific` | 23 (63.9%) | 220 (73.8%) |
| `generic` | 13 (36.1%) | 73 (24.5%) |
| `missing` | 0 | 5 (1.7%) |

Since the holdout has no ground-truth labels, 73.8% cannot be interpreted as precision. Auditing the output, at least the following clear false `specific` cases remained.

| agent | task | residue |
| --- | --- | --- |
| NimbleLovelace | `Reading assigned inbox task` | `reading` |
| AshLavoisier | `CuriousCopernicus からの正本タスクを inbox で確認して遂行` | `確認して遂行` |
| BalmyTuring | `Codex session in .` | `codexsession` |
| SnowyBoltzmann | `Processing canonical task received via agent-mail inbox` | `processing` |

The causes of failure are the English inflections `reading` / `processing`, the Japanese paraphrase `確認して遂行`, the relative path `.`, paths containing spaces, and placeholders that look concrete, such as `scoped work`. On the other hand, CreamLangmuir's `ProOpus からの inbox 正本タスクを実行`, which CuriousCopernicus gave as an example, became `generic` with a residue of 0 characters under this canonical probe.

So this heuristic **matches the 36 agents it was built from but breaks on the holdout.** Because the relay vocabulary was chosen by looking at this snapshot, this is not generalization performance, and chasing vocabulary additions alone cannot block unknown boilerplate. In production, quality should be a warning rather than a hard gate, and precision/recall should be measured on both a fixed holdout and obvious transport-only fixtures at every change.

13/36 agents fall to `Needs description`, and only 6 of them have a role. Releasing Option B alone would honestly make the gaps visible, but it adds no identifying information for the remaining 7 agents. So the first deployable slice is placed in the same release boundary as not only the quality display but also the minimal path of Option C that lets an agent update `task_summary`.

## Recommended option

We recommend a configuration in which **Option B is the source of truth for display and search, the agent-owned `task_summary` update path from Option C is combined with it from the start, and `parent` and `origin` are supplied in stages.** Option A is adopted only as an internal compatibility layer of Option B and is not released alone.

The reasons are as follows.

1. In the current snapshot, task coverage is 100%, yet self-retrieval of the displayed description line is only 8.3%. First, not the amount of data but sharing the same descriptor between display and search is what is needed.
2. At the same time, 36.1% of tasks are transport-only, so `task || live` alone would bring the quality problem to the front. Quality/provenance must be part of the contract.
3. Instruction coverage is 91.7%, but its content mixes assignments, completions, releases, and so on. Adding all of the latest inbox to search trades precision for recall.
4. About half of the roles are missing, so role alone cannot be the primary identity. Multiple independent cues, including parent/origin, are needed.
5. `observed_active` is effective for recovery by recency, but it does not semantically distinguish the 13 agents in the same cwd. It is clearer to limit it to ordering and auxiliary display rather than identity.

The point open to dispute is the cost of the quality judgment in Option B. If transport-only tasks are sufficient in real use and users already remember agent names, Option A wins on cost-effectiveness. That decision should be made by measuring task lookup success and time-to-find in the next section.

The minimal deployable scope treats the following four as inseparable.

1. A common view model equivalent to `deriveRosterDescriptor()`, with `specific / generic / missing / stale`.
2. A path by which the agent updates `task_summary` and `updated_at` after reading the inbox.
3. Search that uses the same tokens as the primary/secondary. The latest inbox subject is not in the default hay and, if needed, is isolated in a `mail:` token.
4. Non-matches stay hidden, while `0/N`, what was searched, and Clear are always shown.

The parent graph join, always-on lineage display, and advanced structured queries can be left out of this minimal scope.

## Measuring the effect

Give the same fixed snapshot to the current UI and the candidate UI, and compare with population changes removed. Use a fixture of at least 30 agents that includes both app spawns and delegate spawns.

### Primary metrics

| Metric | Baseline this time | Recommended pass line |
| --- | ---: | ---: |
| collision exposure: agents belonging to a duplicated primary | 22/36 (61.1%) | 25% or less |
| maximum collision group | 13 agents | 3 agents or fewer |
| display-index parity: searching the full primary text leaves the agent itself | 3/36 (8.3%) | 100% |
| specific current-work coverage | 23/36 (63.9%, manual classification above) | 95% or more |
| role coverage | 17/36 (47.2%) | 95% or more for new app spawns, 80% or more overall |
| rendered-term retrieval failure | 21 of the top 22 agents not correctly recovered | 0% |

`display-index parity` is stricter than the "number of search hits" alone. Even if there is one search result, it is not counted as a success unless it is the agent itself that has the displayed word.

### Task-based metrics

Attach ground-truth "target," "deliverable," "role," and "parent" to each agent in the fixture, and have users find 10 of them.

- median time-to-find: 5 seconds or less
- P90 time-to-find: 12 seconds or less
- wrong jump rate: 5% or less
- Rate at which the correct agent lands in the top 3 from any one of the task/role/parent cues: 90% or more
- Rate at which a new app spawn stays at `Needs description`: 5% or less

### Stability guardrails

- Unless the assignment changes, the primary descriptor does not change with polling or with changes in the spinner/pane title.
- When the primary changes, record the provenance and `updated_at`, and keep unnecessary label churn to 0 per assignment.
- When the filter has zero results, the total, the query, and the clear action are always visible, and the reason the agents disappeared can be explained.
- The rate at which identifying tokens survive truncation at the actual tile width is 95% or more. Put the target or deliverable at the start, not the full long text.

## Issues decided in the follow-up

The following five issues were raised before implementation.

1. Who owns the source of truth for `task_summary`: the spawner, the parent, or the agent itself? If the agent updates it, how is the stale value closed when the assignment completes?
2. Should the quality judgment be only a warning, or should it stop app spawn? I think starting with a warning and making `Needs description` visible is the safe choice.
3. Should the latest inbox subject be included in the search targets? I think it is better to make only subjects tied to the current assignment the default target, and to keep full-text mail search in a separate UI.
4. Should filter non-matches be left faintly visible? I lean toward hiding them by default and making recovery possible through the result count, Clear, and eliminating false-empty results.
5. Should parent/lineage always be shown as text? To protect information density, I lean toward making it a secondary fallback or hover/detail, and usable at all times through the `parent:` query.

In the follow-up with CuriousCopernicus, we agreed on the following.

- The owner of the summary is the agent. The spawn wording stays a seed, and the agent itself updates it after reading the inbox.
- Quality is only a warning and does not stop spawn.
- The latest inbox subject is not put in the default search and is isolated in `mail:`.
- Filter non-matches stay hidden, and false negatives and the explanation for zero results are fixed.
- Parent/lineage is not shown all the time.
