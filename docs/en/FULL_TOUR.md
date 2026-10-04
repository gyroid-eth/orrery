# Full tour

[日本語](../FULL_TOUR.md) · [Documentation index](README.md)

Open **Settings → Getting started → Full tour** for the extended workshop
checklist. Your first flight remains a separate seven-step introduction with
its own saved progress. Full tour has sixteen steps and takes about ten
minutes, depending on agent startup and the game.

1. Spawn an agent with NEW AGENT.
2. Choose it in the agent list.
3. Send a prompt below the terminal.
4. Use the workshop prompt to delegate one child and play shiritori through
   ORRERY Mail. A fresh Mail round trip between parent and child completes this
   step; let the three-round game finish before exiting the child.
5. Modifier-click the parent and child to split their terminals.
6. Drag a split label to swap panes, a pane tab to float it, or a floating
   pane's header to move it.
7. Open PLANETARIUM.
8. Open LEFT and read the remaining allowance. Unavailable data is labelled;
   this observation can also be acknowledged with “I’ve seen it”.
9. Open TELEMETRY for the crew's status and history.
10. Confirm EXIT on the finished game's child from Deck.
11. Open Network and read the Mail edge between parent and child.
12. Select several agents.
13. Start Replay, then close it.
14. RESUME the exited child. Reopen TELEMETRY after the handoff.
15. Change a Network Settings slider.
16. Choose an agent in Telemetry and OPEN IN COCKPIT, returning to its terminal.

Only the current step advances. Failed requests, cancelled drags, a single
selected node, a ready message, and opening an already-running agent do not
complete the corresponding operation. Shiritori requires fresh, observed
Mail with distinct IDs between the selected parent and the same actual child,
with the child's response ID after the parent's move ID. The live API uses
whole-second timestamps and body excerpts: the starting second and the
last observed ID form the game boundary. Ready-only bodies or excerpts,
unrelated peers and earlier games do not count. Subjects may be absent,
Japanese, or prefixed by a reply tool; they do not decide completion.

The workshop prompt is inserted into an empty composer, preserving an existing
draft. It is not sent automatically. Its wording matches
`orrery-workshop/play/shiritori.md`: use the installed /delegate skill and
ORRERY Mail, three round trips, actual message evidence, no native subagent.
An authenticated CLI is needed for the real game.

The printed checklist shares folding, dragging, frosted glass and pop-out
behavior with Your first flight. Its separate window uses
`tour.html?tour=full-tour`, presents the same steps and progress, and can copy
the workshop prompt; it runs no agent or terminal operations. Progress is
saved for this browser and synchronized with the main window. Restart clears
only Full tour and its game observation, leaving first-flight progress intact.

Embedded Telemetry must support `orrery-tour-action` version 1
(orrery-telemetry PR #191). The host checks the exact origin and owned iframe,
then accepts only the current step's successful action. Returning additionally
requires the selected terminal to become focused after Telemetry closes,
including its floating pane or own window. Native focus waits for success;
channel fallback requires an acknowledgement from the registered window
instance for that particular request. Its tour-only focus event does not
move pending drafts into the main composer.
