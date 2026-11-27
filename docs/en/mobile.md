# Read Telemetry on your phone

![Choose an agent on your phone, read its work, and send a prompt](../images/guides/mobile.gif)

Pair your phone to read agent activity and Mail from the list in your browser.

> 日本語: [mobile.md](../mobile.md)

[README](../../README.en.md) · [Installation](telemetry-install.md)

The mobile reader shows agents needing attention, a Mail timeline and NETWORK in English with a dark theme. **It is off by default.** Normal installation and updates start neither a listener nor Tailscale Serve. It reads legacy Telemetry on the same computer, using API 30 or later. Global mode is not supported.

With the ORRERY cockpit you can turn it on and off from **Settings → Phone** ([next section](#turn-it-on-from-cockpit-settings)). The table after it and [Enable manually](#enable-manually) are for setting it up by hand without the cockpit.

For Windows with WSL2, follow [Use Phone access on WSL2](#use-phone-access-on-wsl2) for the Serve step and service checks.

## Phone notifications (optional, Android Chrome)

Notifications are off by default. Complete Phone access's owner and policy review, then prepare the optional dependencies through the regular installer. Review `bash scripts/install.sh --with-mobile-push --dry-run`, then use `--with-mobile-push` for the same installation with its normal approval steps. Ordinary installation does not install these dependencies. Do not pip-install into production Python by hand.

For an existing phone job, reapply its settings with `printf '%s\n' '{"access":true}' | agentstack-mobile apply`. The job then selects the managed notification Python. Preparing dependencies creates no browser permission or subscription. A manually launched relay needs that optional Python, `--enable-push`, and reviewed history settings.

Tap the **bell** in an agent's Reader, then **Enable on this phone** and allow Chrome's notification prompt. Only that explicit action requests permission. Settings belong to this phone:

- **Reply needed** covers every agent's question or approval wait, using the Reader's existing ask/question observations.
- **Work finished** covers this agent only: new work followed by waiting and a new recorded assistant reply marks the end of a turn. It does not establish completion of an entire task or process exit. Selected agents have a marked bell.
- **Message previews** is one setting per phone, off by default. Off sends only the agent and event type. On can include up to 600 characters from a new question or last reply. Code, images, suspected secrets/tokens and text containing absolute paths are hidden. Without a verified new question or approval text, only its type is shown.

Notifications continue in Demo, but message previews are hidden immediately before publication regardless of this phone’s setting. Names follow the phone display’s host-name and extra-word masking rules. The bell still allows enabling and changing alert types; **Message previews** is temporarily shown off and disabled. Its saved value is retained and restored when Demo is off. Switching Demo on or off does not reset baselines or pending alerts.

**Disable on this phone** removes the server subscription before unsubscribing the browser. Use the bell to enable it again. After a denied permission, allow ORRERY notifications in Chrome's site settings. This version targets Android Chrome; iOS/Safari is outside its scope.

The Mac publishes over outbound HTTPS to Google's Push service using standard Web Push payload encryption. Google still receives delivery metadata and the configured owner's login email as the VAPID contact (an email-form login is required). No Funnel or public inbound endpoint is added. Clicking a notification opens the same origin and waits for Reader startup and a fresh roster before opening that agent. Fresh also passes the roster’s Mail identity to the input target. Receipt does not fetch conversation history through Tailscale; reading still needs Tailscale and an awake Mac.

Keys, subscriptions and sent markers live in `~/.agentstack/runtime/mobile-push/` with directory mode 0700 and file mode 0600. The VAPID key is created once on enable; endpoints and keys are not logged. Unknown or unsupported Demo status, disconnected and unknown agent states do not publish. Startup and recovery after a gap longer than 30 seconds only establish a baseline. An interruption longer than 30 seconds during a read or publication also discards that observation and its unsent notifications. No new notifications are sent while the Mac sleeps. History reads are limited to eight per pass. Work-start baselines, completion checks and question previews share one oldest-attempt-first order, updated even on failed reads. Uncollected baselines carry over while work continues. The relay observes every five seconds even with the page closed; short work between observations and turns without readable records may be missed.

Two observations settle a reply-needed transition, and an unchanged state does not repeatedly alert. Limits are eight phones, 128 selected agents per phone, 64 pending items, four publications per pass, three attempts and a 120-second expiry. Turning alerts off cannot recall an already accepted notification. HTTP acceptance is not proof of phone display; OS power and notification settings can delay or omit delivery. Exactly-once delivery is not guaranteed.

## Turn it on from cockpit Settings

The cockpit's **Settings** has a **Phone** section with two switches:

- **Phone access**: everything the phone can read (the agent list, Graph, Mail and conversation records, and file and image previews). There is no separate switch for conversations.
- **Send from phone**: send one confirmed line to a pane ([Terminal](#inspect-a-pane-and-send-input-from-your-phone)). It is on by default but does nothing until step 4 below.

**It cannot be set up in demo mode.** Demo mode does not put the login and the address on the page, so step 2 shows no fields. Turn off **Demo mode** in Settings once and go through step 4 below (`?demo=0` in the URL affects only that page; reloading brings demo mode back). After that you can go back to demo mode ([In demo mode](#in-demo-mode)).

### Before you start (you, once)

Two things cannot be changed from the cockpit. They are the same as steps 2 and 4 in the table under [Ask your agent to set it up](#ask-your-agent-to-set-it-up).

- **Install Tailscale on the phone and sign in with the same account as the computer.** Check: the computer is listed in the phone's Tailscale app (and the phone shows up in `tailscale status` on the computer).
- **Enable MagicDNS and HTTPS Certificates on the DNS page of the Tailscale admin console.** Serve (HTTPS) in step 3 needs them. Check: both are on in the admin console's DNS page, or `CertDomains` in `tailscale status --json` on the computer is not empty.

### The first screen

The badge next to **Phone** says **OFF**. Press the **Phone access** switch.

### Steps 1 and 2: Tailscale, owner and address (you, once)

The first press **leaves the switch off**. Right under the switch it says "Not on yet: check the owner and address in step 2 below, then press Confirm and turn on.", the **Setup** steps open below, and the cursor moves to step 2.

- Step 1 reads whether Tailscale is signed in. With a ✓ there is nothing to do. Without one, the line under the switch says "sign in to Tailscale" (or "Tailscale was not found" when it is not installed): install Tailscale on this computer and sign in, then press **Phone access** again.
- In step 2, **Owner (Tailscale login)** is the only login the reader lets in, and **Address on the phone** is the address the phone opens (`https://<this computer's Tailscale name>:9443`). Both are filled in from `tailscale status`; check them and press **Confirm and turn on**. This is what turns Phone access on.
- **Check:** the badge says **SETUP** and step 2 has a ✓.

### Step 3: Serve 9443 → reader (you, terminal)

On macOS, **Copy** the `tailscale serve --https=9443 http://127.0.0.1:8781` shown in step 3, run it once in a terminal, then press **Check again**. On WSL2, use [Telemetry Settings](#use-phone-access-on-wsl2) to preview and confirm the change.

**Check:** **Check again** puts a ✓ on step 3. If it does not, read the output of `tailscale serve`. With HTTPS Certificates off, it asks you to enable them here ([Before you start](#before-you-start-you-once)).

### Step 4: Who can reach it (you, admin console)

When step 3 has a ✓, check in the Tailscale admin console who and which devices can reach tcp:9443 (for example with the [device restriction below](#restrict-the-account-and-the-phone-separately)). Then press **I reviewed the policy**. Only the date you pressed it is kept; ORRERY cannot check the policy.

**Until step 4, conversations and Send stay off.** The phone can read the agent list, Graph and Mail only (the reader answers `policy_not_reviewed`). Meanwhile the line right under the switch says "On, but Conversation and Send from phone stay off until step 4 below".

**Check:** ORRERY cannot check the policy, so check it yourself. In every case, see in the admin console that only the people and devices you mean to allow can reach tcp:9443. If you restricted devices, also check that an excluded device cannot open it, as in [Verify on real devices](#verify-on-real-devices).

### When it is on

The badge says **ON** and the setup steps are gone. **Check it yourself:** all four Status lines are green (reader, Serve, Funnel off, policy). To change the login or the address, use **Change owner or address**.

### Follow the work on your phone

Claude and Codex records show the same **Agent steps** as the desktop Reader. Messages, Mail, and system notices separate adjacent runs of operations into different cards. Completed operations appear one at a time, with **Working…** and elapsed time during work. On completion the card folds into **Worked for … · N steps**; tap to expand it. Historical turns start collapsed. Only explicit failure is **Failed**; an operation without a recorded outcome is **Observed**. Codex inner operations appear after their completion record arrives; execution in progress is not inferred. Target summaries use one ellipsized line.

With the legacy dashboard and current cockpit, Claude Code, Codex CLI, dsh and Hermes show **Compacting context…** while the active terminal shows compaction. The timer appears when the terminal supplies one. When the history catches up, **Context compacted** stays in the record as a single line.

Replaced tool labels do not repeat, while files, images, Mail and unsupported tool groups stay available. An unmatched Claude result asks to load earlier requests. The phone receives only bounded tool names, existing target summaries, times, status, opaque IDs and turn markers; no new raw arguments, output, paths or cockpit reference IDs. Page and byte limits stay the same. Demo continues to work and masks targets by the same existing rules as other text. Backgrounding pauses motion and the clock; Close clears them. OS reduced motion is respected. Motion reuses the desktop adaptation of [kokonutUI AI Loading](https://kokonutui.com/) (MIT), retaining its license in source.

On the phone, open the **Address on the phone** from step 2 (`https://…:9443/`) and open an agent. The first HTTPS request can take a few seconds while the certificate is issued. When the **Conversation** tab appears, you can [follow the agent’s work in Reader](#follow-an-agents-work-in-reader).


### In demo mode

Enabling **Demo mode** in an updated cockpit also masks user names, host names and the extra words on the phone. A connected foreground page follows within about four seconds without reloading or losing its draft and pictures. Turning the desktop Settings switch off unmasks the phone. Closing the desktop keeps the last state; URL `?demo=0` alone does not unmask the phone. Copying and sending still use the original values.

The phone checks Demo state before its first display. Communication errors hide the screen and show **Retry**. While that browser retains its Demo state, stopping the cockpit or switching to an older version does not reveal names. If no cockpit is running or the version is unsupported, and the phone has never received Demo mode, ordinary viewing still works. Update both components and reload the active Demo desktop and phone once.

If you press **Phone access** in demo mode before the login and address are set, the line right under the switch says "Turn off demo mode to set up phone access (once). After that you can switch it on and off in demo mode." **Turn off demo mode** turns demo mode off and reloads the page. Settings closes, so open **Settings** again, press **Phone access**, and go through the steps above.

Once it is set up, you can go back to demo mode and the switch keeps working. The login and the address read "hidden in demo mode" and are not put on the page. Turn demo mode off only to change them.

### What runs behind it

Behind it runs Telemetry's `~/.agentstack/bin/agentstack-mobile`. The cockpit only calls that command and never writes Telemetry's files itself.

- Settings live in `~/.agentstack/mobile.json` (mode 0600): `access`, `send`, `owner_login`, `public_origin`, `policy_reviewed_at` and three ports. It holds no keys or tokens.
- The reader runs `mobile_relay.py --config ~/.agentstack/mobile.json`. On macOS the launchd job is `org.agentstack.mobile-relay`, with logs in `~/.agentstack/logs/mobile-relay.log`. On WSL2 it is the user unit `org.agentstack.mobile-relay.service`, with logs in the journal. Settings changes reload the service. Turning Phone access off or uninstalling stops and removes the managed service. Installation only places the command.
- While a reader you started by hand holds 8781, the badge says **MANUAL** and Status says **A reader not started from Settings is running on 127.0.0.1:8781**. The phone can still read that reader. Settings cannot control it, so its switches are disabled, and `agentstack-mobile apply` answers `port_in_use` and changes nothing. To move to Settings, stop that reader in the terminal that started it (Ctrl-C), then turn **Phone access** on. The hand flags map like this: `--enable-terminal` is **Send from phone**, `--phone-policy-reviewed` is **I reviewed the policy** in step 4, and History is part of **Phone access**.
- **Send from phone** also switches the cockpit side at once and saves it as `enable_mobile_terminal` in `~/.orrery/config.json`; no backend restart is needed. A change made in a terminal (`agentstack-mobile off`) is picked up the next time Settings is opened. While a reader started by hand is running, and until Settings has been used once, `enable_mobile_terminal` is left as it is.
- Changing the login or the address withdraws the step 4 review; conversations and Send stop until you review again. To withdraw it yourself, run `echo '{"policy_reviewed": false}' | agentstack-mobile apply`.
- If launchd cannot start the reader, Phone access goes back off and neither the job nor its plist is left behind (so nothing starts by itself at the next login).
- The job runs the reader with the Python that was in use when you turned it on. If that Python goes away (a venv, or an older Homebrew version), Status says **The Python this reader was set up with is gone**. Turn Phone access off and on to rebuild the job with the current one.
- In cockpit demo mode the Phone section does not put the login, the address or the Serve URL on the page (demo mode itself hides only user and host names). Turn demo mode off to set them up or change them ([In demo mode](#in-demo-mode)).
- The Phone switches read Serve and Funnel status. The WSL2 Serve controls are separate. Access policy and Funnel settings are managed in Tailscale.

Without the cockpit, use `agentstack-mobile status` to see the state, `echo '{"access": true, "owner_login": "owner@example.com", "public_origin": "https://computer.example.ts.net:9443", "policy_reviewed": true}' | agentstack-mobile apply` to turn it on, and `agentstack-mobile off` to turn it off.

## Use Phone access on WSL2

Use an updated WSL2 distro with systemd enabled and a running user manager. Check `systemctl --user show-environment` inside the distro. Keep the distro running while the phone needs it. A systemd service alone does not keep WSL awake or start the distro at Windows sign-in. [Microsoft WSL systemd guide](https://learn.microsoft.com/windows/wsl/systemd)

1. Sign in to Tailscale and enable MagicDNS and HTTPS Certificates as above. Telemetry uses `tailscale` in WSL when installed. Otherwise it uses Windows `tailscale.exe` from PATH or the standard Tailscale installation under Windows Program Files. With Windows Tailscale, WSL interop and Windows-to-WSL localhost forwarding must work. Check `agentstack-mobile status` for the sign-in and suggested address. [Microsoft WSL interop](https://learn.microsoft.com/windows/wsl/filesystems#run-windows-tools-from-linux), [Microsoft WSL networking](https://learn.microsoft.com/windows/wsl/networking)
2. In Cockpit, go to **Settings → Phone**, check the suggested owner and address, and press **Confirm and turn on**. In WSL, check `systemctl --user status org.agentstack.mobile-relay.service` and `journalctl --user -u org.agentstack.mobile-relay.service`. When using Windows Tailscale, run `curl.exe -i http://127.0.0.1:8781/` in Windows PowerShell. A `403` with `request_denied` confirms the relay is reachable and requires the Serve identity.
3. Save the current Serve configuration with `tailscale.exe serve status --json` in Windows PowerShell (or `tailscale serve status --json` when using Linux Tailscale). Open Telemetry directly at its local dashboard address, select **Network → Settings → Phone access → Review Serve**, and check the preview for **HTTPS 9443 → http://127.0.0.1:8781**. Press **Add Serve** to apply it. Use **Cancel** to leave the preview. HTTPS 9443 must be free for this action. The other listeners, including 443 and 8443, are outside the operation. Avoid editing Tailscale's port 9443 in another window while confirming.
4. Return to Cockpit and press **Check again**. Finish reviewing the tailnet policy in step 4 above, then open the suggested address on the phone. If Tailscale refuses the change, check its Serve status, HTTPS settings and local CLI permissions before trying again. [Tailscale Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve)

To undo, open **Review Serve** again, check the preview, and press **Remove Serve**. The dashboard can remove the dedicated entry it created while that entry still matches. Compare the remaining Serve configuration with the saved output. Turn **Phone access** off in Cockpit or run `agentstack-mobile off` and verify the systemd unit is gone. Off and uninstall stop the relay. Use the separate confirmation to remove its Serve entry.

## Ask your agent to set it up

You can hand this page to the Claude Code or Codex agent on the computer that runs Telemetry. For example:

> Read docs/mobile.en.md and set up the mobile reader for my phone. Do the commands yourself, stop at the steps marked "you", and tell me exactly what to do there.

At steps marked **you**, use the Tailscale admin console or the phone itself. The agent can handle the other steps. To use Terminal too, continue with the [separate opt-in steps](#inspect-a-pane-and-send-input-from-your-phone) after setting up viewing.

| Step | Who | What |
|---|---|---|
| 1 | agent | Confirm `curl -s http://127.0.0.1:8770/api/version` reports API 30 or later |
| 2 | **you** | Install Tailscale on the phone and sign in with the same account as the computer |
| 3 | agent | Find the values: computer Serve name and IP from `tailscale status --json` (`Self.DNSName` without the trailing dot, `Self.TailscaleIPs[0]`), owner login from `User[Self.UserID].LoginName`, phone IP from `tailscale status`. `tailscale whois <phone IP>` confirms the phone belongs to that login |
| 4 | **you** | In the admin console, DNS page: enable MagicDNS and HTTPS Certificates if they are off. `CertDomains` in `tailscale status --json` is empty until then |
| 5 | **you** | Review who can connect. Restricting access to your operating devices is recommended; multiple personal phones and tablets are fine. If you choose this restriction, adjust the grant and broader existing permissions as described below |
| 6 | agent | Run steps 2–5 of [Enable manually](#enable-manually) |
| 7 | **you** | Open `https://<Serve name>:9443/` on the phone. The first HTTPS request can take a few seconds while the certificate is issued |
| 8 | agent + **you** | Check each intended device. If you chose device restrictions, also check that excluded devices are refused (see [Verify on real devices](#verify-on-real-devices)) |

On macOS the CLI is usually `/Applications/Tailscale.app/Contents/MacOS/Tailscale` when `tailscale` is not on `PATH`. A reader started by hand runs in the foreground. To keep it running, use cockpit Settings (or `agentstack-mobile apply`), which runs it as a launchd job.

## Install on the home screen

With Tailscale connected, open this reader's HTTPS Serve address in Android Chrome. Choose **Install app** from Chrome's menu (some versions put it under **Add to Home screen**), then confirm installation. Delete an older browser shortcut and install again. Launch **ORRERY** from its new icon to open it without the browser's URL bar; opening the address in a normal browser tab still shows that bar. On iOS, use Safari's **Add to Home Screen**.

Add each computer from its own Serve address. The app name is **ORRERY · computer name**, and the home screen may use the shorter computer label.

Installation keeps the same owner admission and live connection requirements. It does not add offline records or a service worker. Android Chrome's menu installation no longer requires a service worker ([Chrome's installation criteria](https://developer.chrome.com/blog/update-install-criteria)). The app keeps controls inside the device's safe areas. After updating, verify installation and background/foreground behavior on the actual phone.

Regenerate the committed icons from `dashboard/assets/orbit.svg` with `python3 scripts/mobile_pwa_icons.py` (development tool: `rsvg-convert`).

## Reading the screen

Graph shows working and waiting counts in its upper-left corner. Tap a count to see the matching agents and their portraits, then choose an agent to open Reading View. When agents need attention, the working icon shows a dot and its list starts with review requests (`!`) and questions (`?`). The information icon opens the observation time, range, and status. On a phone, agents needing attention sit below Graph. Tap the list icon in that panel to open Activity. On a wide screen such as an iPad, Graph and the attention and activity panel appear side by side. The Activity information icon also shows observation warnings.

Select multiple agents with the selection icon in Graph, the panes icon in the header, or the add icon in Reading View. Drag the divider between Graph and the panes to resize them. Release at an edge to show only one side, and use the header to return to the split. On a phone, the home divider between Graph and the attention list also resizes those areas.

Each pane opens in Reading View. The pencil opens a wider composer when several panes are open, and each pane keeps its own draft as you switch views. Use the attachment menu to choose JPEG, PNG, or WebP photos or browse files of any format.

Dark is the default. Use the sun or moon icon in the upper-right corner to switch between light and dark. The browser remembers the choice.

- **Activity** lists sender, recipient, and time. To/Cc is included in the action label and Mail detail. Tap one Mail event to open its subject and body. Tasks and private paths are not separately fetched, but anything written in a Mail body is visible. Status records changes observed after this reader starts, rather than claiming to know when each change actually happened.
- **Graph** defaults to agents with observed activity in the last 24 hours. Focus shows the selected agent and up to five strongest peers within that period; All shows every agent in that period. Use the **Find an agent** magnifying glass to search by name or Role. Tap a result name to open its Reader; the adjacent **Focus** button centers the graph on that agent. In Focus, tap a surrounding agent to make it the center and fit the graph; tap the center agent to open its Reader. In All, tapping any agent opens its Reader. Enter and Space follow the same rules. A short Role from its existing annotation appears beneath the name; missing roles are not inferred. Pinch to zoom or drag the background to pan. Drag an agent to move its node and highlight its connections. Large graphs do not guarantee that every name is readable at once.
- Close a Reader opened from a Graph agent or search-result name with **×** or **Back** to focus and fit the last agent you read, with up to five strongest peers. Readers opened from Activity or elsewhere return to the previous view.
- In both Focus and All, zoom levels of 75% or more show every agent’s name below its portrait and its existing Role below the name. The selected name keeps its previous size; other names are smaller. Below 75%, names and Roles are hidden.
- Line width and arrow size follow Mail counts in the selected period. Counts are **recipient rows** by direction and To/Cc, rather than unread counts or unique sent messages. Dashed parent–child lines are separate from Mail.
- Context arcs and working motion use the PC renderer. Unknown context has no arc, and its sampling time remains unknown. Account usage is Unavailable; this reader never refreshes it.
- **Tune graph** and Activity filters only change this browser's display. Conversation history needs the policy review below. Terminal viewing and input also need their own switch.
- **New agent** is available above Graph when **Send from phone** is enabled. Enter a task and choose the model and a configured launch directory from the compact control row. Open the model chip, select a provider icon, then search its model list. Local models show their connection. After selecting a model, choose a harness if several are available, set a supported Effort level with the slider, and set Role in legacy mode. The marks on the model chip reflect the selected Effort. In legacy mode, choose Off, View, or Control from the Computer use icon beside the directory. View allows inspection and Control also allows interaction. Tap the Browser icon to choose Off, Temporary Chrome, or My Chrome. Where available, My Chrome is the default. Temporary Chrome uses a temporary profile. My Chrome uses your usual Chrome. If Chrome asks for permission on the first connection, browser actions wait until you respond on the Mac. **Review launch** confirms the exact directory path, task, model, and settings before launch. If the launch fails, the form suggests a next step. Check Graph if a launch outcome is unknown. The reader never repeats the launch automatically.

The reader polls about every ten seconds in the foreground and stops polling in the background. Failed observations retain the last known values, visibly marked as such; failure is never a healthy zero or a waiting agent. Snapshot time is the HTTP observation time. Mail shows up to 200 recipient events per page; **Older / Newer** replaces the page. Graph polling continues while you read an older page, without moving it back to the latest page. Status appears on the latest page only. Graph aggregation has a separate 10,000-link limit. Truncation is shown explicitly. The browser saves the theme and six graph settings. Session storage keeps the open agent name and Conversation/Terminal tab, plus the selected Mail instance/agent IDs when available. No record or draft is stored for offline use, and no service worker is used.

Tap a Graph Mail edge to open metadata between those two agents in the selected period. **Both** directions is the default; the sender→recipient buttons filter the direction. Parent–child lines do not open Mail. Tap one event for its content, **Back** for the list, and **Done** for Graph. Selection and zoom are retained.

While Graph is in the foreground, a rise in Mail link counts between snapshots (about every 10 seconds) sends a light from sender to recipient with a **+N** label. To/Cc rows for the same directed pair are combined. Tap the light for the existing pair list; subjects and bodies are fetched only when you choose one message. Initial load, period changes, returning from the background and interrupted observations do not replay older activity. Links outside the displayed graph are omitted; snapshots with truncated link counts do not produce lights. At most 12 lights appear at once. This is a difference in period counts: older Mail leaving a rolling window can offset new arrivals. With reduced motion enabled, a stationary mark appears at the link midpoint instead.

Context, state and Role changes update the affected node without restarting layout, preserving positions, manual zoom and other portraits. Roster, link and Focus changes still recompute layout. The existing logo, fonts and graph renderer are retained.

Use **Expand** at the top right of Graph to fill the screen. If the browser's fullscreen API is unavailable or refused, Graph fills the page instead. Find, Focus/All, Fit, pinch, drag, Mail-pair lists and the Terminal sheet remain available. **Close** restores the normal view. Back or Escape closes the foreground sheet first, then exits the expanded Graph. If the OS or browser exits fullscreen, the normal view returns and open sheets close. The layout follows orientation changes and retains your selection and manual zoom. Fullscreen, back gestures and keyboard behavior on an actual phone require separate acceptance.

<img src="../images/telemetry/images/mobile-graph-to-terminal.gif" width="300" alt="On a phone, select an agent from All, switch to Focus, check Terminal and Conversation, and send an input line">

Subjects are limited to 512 characters and bodies to 64 KiB of UTF-8, with explicit truncation notices. HTML and Markdown remain literal text; links, images and attachments do not execute. No read receipt, ACK or reply is sent. Closing, choosing another message, changing the period or view, and moving to the background clear the displayed content. Late responses cannot restore it. Unavailable, deleted, changed or expired events show an error, never the previous message's body.

<img src="../images/telemetry/images/mobile-mail.png" width="300" alt="Open a Mail message on a phone to read its subject, sender, recipient, and body">

After an owner-authenticated snapshot request, the Mac reader prepares a fixed last 24 h in memory: up to 2000 distinct messages and 32 MiB of serialized content plus metadata. This is a logical JSON byte budget, not an RSS guarantee. Multiple To/Cc recipients share one body. Capacity, time or read failures are shown as **partial / unavailable**, rather than complete coverage. Every tap rechecks the current delivery and revision, including cache hits. Older displayed events remain readable one at a time and are not cached. Stopping the reader clears all caches. Subjects and bodies are never bulk-sent to the phone.

Page positions expire after 10 minutes, with at most 256 on the host and 2000 issued events. The browser keeps at most 20 navigation positions. Expiry produces an explicit error rather than silently returning to the latest page. Changing the period resets pages and content.

The small time control at the bottom of Graph, or in the phone Activity view, opens **Time range**. Its slider covers 15 minutes to 30 days in 15-minute increments. It starts at 24 hours; **All history** is a separate explicit choice, distinct from Graph's All mode. Changes apply about 200ms after the last input. The period filters agent activity, Mail events and counts, and the observation time of Status changes. Status retains the latest 200 changes after reader start, then shows those matching the period and displayed agents.

Activity uses canonical last-active and Mail timestamps. Recently active retired agents remain included; merely running does not turn old activity into current activity. Agents with unknown activity times are excluded from finite periods with an explicit count, and included in All history. Observation and projection have limits; the host's large all-history reads are not guaranteed to finish within the deadline.

Special agent icons use the PC's existing portrait configuration, with a scientific portrait and then initials as fallbacks. The private map and file paths are never sent to the phone. Portraits require the same owner authentication, accept bounded PNG images, and fall back to initials on fetch or decode failure.

## Restrict the account and the phone separately

Use **Tailscale Serve inside your tailnet**, with neither Funnel nor direct sharing of the full dashboard or cockpit. The relay listens only on `127.0.0.1` and checks the outer HTTPS Host and exact owner login. [Serve replaces incoming identity headers with its own user information](https://tailscale.com/docs/features/tailscale-serve). Another process on the same computer can forge these headers; this is not protection from untrusted local processes.

**Matching the account does not restrict which devices can connect.** We recommend allowing only devices you use to operate the terminal; multiple personal phones and tablets are fine. Strongly consider excluding always-on, public-facing servers on the same account: they could also reach the terminal, increasing the impact if compromised. This is a recommendation, not a product requirement to use one device, and the product does not automatically verify the policy.

If you choose this restriction, have the administrator allow your operating devices' Tailscale IPs to the dedicated HTTPS port. Merge the following example into the existing policy, remove unused devices from `src`, and replace the placeholders. Do not overwrite the whole policy with it.

```json
{
  "grants": [{
    "src": ["<PHONE_TAILSCALE_IP>", "<TABLET_TAILSCALE_IP>"],
    "dst": ["<SERVER_TAILSCALE_IP>"],
    "ip": ["tcp:9443"]
  }]
}
```

[Grants and selectors are additive](https://tailscale.com/docs/reference/syntax/grants). A broader existing allow rule covering this port must also be narrowed; adding a phone-specific grant cannot subtract access. Listing the user and phone IP together in `src` is OR, not AND. See [IP selectors](https://tailscale.com/docs/reference/targets-and-selectors). Device names and browser User-Agent strings are not authentication. Do not substitute a tag on the user's phone: tagging changes its user identity.

Review **every grant and ACL** applying from excluded devices to this host, so no other broad permission still allows `tcp:9443`. For example, the following `ip` values remove only TCP 9443 from a broad grant while allowing the other TCP ports, UDP and ICMP:

```json
["tcp:1-9442", "tcp:9444-65535", "udp:*", "icmp:*"]
```

This illustrates [protocol and port syntax](https://tailscale.com/docs/reference/syntax/grants#network-layer-capabilities). It is not a replacement policy or a universal substitute for `["*"]`. Preserve any needed permissions for other protocols and destinations, and have the administrator review the changes. The agent does not rewrite policy automatically.

## Enable manually

**Before you update:** a reader you start by hand with `--phone-policy-reviewed` and without `--enable-history` shows conversation history and file and image previews on the phone after the first restart. To keep them off, add `--disable-history` before restarting. The reader also says so in one line when it starts.

1. Update Telemetry to API 30 or later and confirm that its normal local dashboard has observations. Keep the existing services and provider configuration.
2. Review current access. If you choose the recommended device restriction, complete that policy change above. Save the current `tailscale serve status --json` output and confirm that the example HTTPS port `9443` is unused and is not a Funnel listener. Do not reuse a port with existing configuration.
3. Check the options below. Replace `owner@example.com` with the exact Serve login and `computer.example.ts.net` with this computer's actual Serve name. Omit a trailing slash from the origin. Replace the script path for a custom installation. Python 3.11 or later is required.

```sh
python3 "$HOME/.agentstack/dashboard/mobile_relay.py" --check \
  --owner-login 'owner@example.com' \
  --public-origin 'https://computer.example.ts.net:9443' \
  --listen-port 8781 --upstream-port 8770
```

`--check` validates option syntax only. It makes no connections, starts no listener and changes no policy. It does not verify the phone restriction. Resolve missing options before continuing.

4. Keep the reader running in one terminal.

```sh
python3 "$HOME/.agentstack/dashboard/mobile_relay.py" --enable \
  --owner-login 'owner@example.com' \
  --public-origin 'https://computer.example.ts.net:9443' \
  --listen-port 8781 --upstream-port 8770
```

5. In another terminal, connect the dedicated Serve port to this reader. Do not point it at 8770 or cockpit.

```sh
tailscale serve --https=9443 http://127.0.0.1:8781
```

This uses the [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve) in the foreground and does not reset existing entries. Add `--bg` to keep the Serve entry after the terminal closes; remove it with the command in [Disable and restore](#disable-and-restore). A direct relay request without the owner header should return 403. If Host or Origin is rejected, check the actual Serve name, port and Tailscale version rather than relaxing the guard.

## Verify on real devices

Open `https://computer.example.ts.net:9443/` on each intended phone or tablet and confirm that the owner can load the page and snapshot. Also check that another account is refused. If you chose device restrictions, separately verify refusal from **excluded devices on the same account**. Owner-header authentication and device policy are separate checks. Do not report access as restricted to operating devices if the excluded-device checks are incomplete.

Repository tests use isolated HTTP and synthetic screens. They do not establish acceptance of the installed Tailscale version, real policy or actual phone. The operator performs that deployment verification separately.

## Inspect a pane and send input from your phone

**Terminal is a separate opt-in. For a reader started by hand, capture and input are off by default.** Starting the viewing reader alone does not enable it. In cockpit Settings this is **Send from phone**, on by default but inactive until the policy is reviewed. Device restrictions are the optional recommendation above; you can allow several operating devices. The existing `--phone-policy-reviewed` declaration is still required to acknowledge that the operator reviewed current access. It does not verify policy or enforce a single phone.

You can also give this section to your agent. It should stop at your steps and preserve existing settings.

| Step | Who | What |
|---|---|---|
| 1 | agent | Confirm Telemetry API 31 or later for legacy, a matching API34 version for fresh, the ORRERY pane adapter, and the current backend's launch method and manager |
| 2 | **you** | Review access. If you chose device restrictions, check allowed operating devices and refusal from excluded ones. Agree to the temporary disconnection during restart |
| 3 | agent | Add or update only the JSON field below in the existing `~/.orrery/config.json`, preserving other fields. File mode `0600` is recommended |
| 4 | agent | Explicitly stop and restart the backend through the identified launch procedure. Reusing a running process does not apply the setting. Do not start a duplicate or use blanket kills; stop and report an unknown manager |
| 5 | agent | Use the capability check below to confirm `api:31` for legacy or `api:34` for fresh, and `enabled:true` after human opt-in. It captures no pane and sends no input |
| 6 | agent | Add `--enable-terminal --phone-policy-reviewed --cockpit-port 8791` to the reader's existing launch example. Run `--check` with the same flags first, then restart the existing reader through its current manager |
| 7 | **you** | Open Terminal on your phone or tablet, check the selected pane and display, and review the exact text before every test send |

Add this field to the shared settings; the example does not replace the whole file.

```json
{"enable_mobile_terminal": true}
```

New backends started by `scripts/start-cockpit.sh`, setup reached through `get.sh`, or ORRERY.app read the same setting. Custom backend commands can still use `--enable-mobile-terminal`. **Closing ORRERY.app leaves the backend running.** If reopening the app does not apply the setting, restart the backend through its original manager.

The following check sends no input. Replace `owner@example.com` with the reader's owner login, and change the first path for a custom installation.

```sh
python3 - "$HOME/.agentstack/dashboard" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from mobile_input import InputClient
capability = InputClient(8791, 'owner@example.com').call('capability')
print({key: capability[key] for key in ('api', 'enabled')})
raise SystemExit(0 if capability['enabled'] else 1)
PY
```

Do not treat `enabled:false` or an error as successful activation; check the version, settings and process manager. Reader `--check` validates syntax, not policy or device acceptance. Missing opt-ins, incompatible versions, existing target protection or unavailable OS identity checks leave Terminal unavailable.

Tap a Graph agent or a search result name to open the same sheet. The Reader icons on Status rows, attention rows, and Mail-detail From/To entries open the same sheet. There is no separate selected-agent card below Graph. Mail-detail actions remain. Choose a pane when several exist; an unknown mapping is never guessed from the label. In legacy, only panes already handled by the PC manager on the same transport and admitted by its protection are eligible. Agent type and the displayed time period are not authorization. No other socket or global target is used as a fallback. A pane's session may be outside the current metadata project. For fresh, use the explicit I/A procedure below.

The selected pane shows its last 120 lines, limited to 12 KiB of UTF-8. With Conversation enabled, Terminal fills the reading surface and aligns short output at the bottom. Long lines wrap and continuation lines retain their original indentation (limited to 40% of the screen width for deeply nested output). Divider-only lines stay on one line and are clipped to the width. The frame is removed. Limits, update timing and Shown time appear in one small row below the text. Truncation, removed control sequences and paused reading appear below only when needed. A small dot marks activity, while paused reading and failures stay visible. Only that open, foreground pane updates about every three seconds; failures back off to 6, 12 and at most 24 seconds. Removed control sequences and shortened text are marked. Images, HTML and links never execute. Full recorder/restored history is not forwarded; the separate [Conversation in Reader](#follow-an-agents-work-in-reader) shows only verified conversation records. **Terminal text can contain keys or private writing.** Check it before sharing the screen.

Expanded terminal previews require `X-ORRERY-Mobile-Preview: 120/12288` on the loopback request. If either side is older, previews keep the 40-line/6-KiB limits; the newer reader validates text against the declared limits. Expanded responses still fit within 16 KiB of serialized JSON, shortening the tail further when quote escaping requires it. The relay sends UTF-8 without expanding non-ASCII characters into `\uXXXX`.

Swipe clearly left over Conversation text to open Terminal, or right over Terminal text to return. Gestures starting within 24 px of either screen edge are left to the OS. Vertical scrolling, text selection and horizontally scrollable tables or code keep their own behavior. Swiping does not switch tabs while input has focus, a draft exists, Review is shown, or a send is pending. An empty unfocused input does not block swipes over the body. The buttons in the top bar remain available.

While you scroll up to read, the text, **Shown** time and shortening/control-removal notes stay on the same snapshot; fetching continues. **New output · paused** means a newer tail is waiting. Scroll to the bottom to switch to the latest tail and resume following. This does not accumulate all output: if more than 120 lines or 12 KiB arrive while paused, output between the old display and the latest tail may be missing. On your phone, open a pane with flowing output, scroll up and wait more than three seconds: the line being read and its Shown time should stay fixed. Return to the bottom and verify that the latest tail appears. Also check that opening/closing the keyboard or rotating the screen keeps a following view at the bottom and retains the text when reading earlier output.

A successfully fetched empty snapshot is also held while reading; returning to the bottom switches to the empty display. A fetch failure is an exception: text, Shown and notes are cleared, and recovery starts at the latest tail. A size change that clamps the view to the bottom does not release the pause; scroll toward the bottom again to switch to the latest tail.

When an operation changes direction, its latest movement decides whether to resume. Reversing upward, using two fingers or cancelling a touch keeps output paused. Moving downward again can resume once the view is at the bottom.

Use a dedicated pane that is safe to test. Check that changing panes and reopening after Close start at the new tail, and that **Review input** → **Edit** retains the input and shows the correct pane and text. To test sending, use only a known recipient pane explicitly set up to accept a short test input without side effects. Verify the target, exact text and Enter, press **Send once** once, then check the response and receipt. Do not send test text to a working agent or an unfamiliar shell. Also check that backgrounding stops requests while preserving the open agent, tab, reading position and in-memory draft. Returning rechecks the pane revision; a changed or missing pane requires choosing and reviewing again. An expired confirmation returns to editing. A send whose result is unknown retains **Check receipt** without sending again.

Conversation and Terminal share a rounded input at the bottom. The Reader header shows the recipient’s portrait and name. In a workspace with multiple Readers, the input sheet shows the same heading when opened. Write one line of at most 4 KiB UTF-8 and press **↑ (Review input)** to turn that same area into confirmation. Check the agent, not-yet-sent notice, exact text and following Enter, then press **Send once** once. **Edit** returns to the draft without losing it. Confirmation expires after 30 seconds. Output refreshes do not replace its text, target or expiry. One missed terminal preview keeps the last verified view and lets you continue. If previews keep failing, the Reader reconnects and verifies the pane again. A changed connection or pane can require a new review. Keep the sheet open in the foreground to see the pane's response after sending. The cockpit checks that the pane’s editor is empty, pastes the text, then sends Enter once it sees the matching draft. **Received by terminal** appears once the editor clears the draft after Enter or opens the requested command view. **Outcome unknown** can mean that only part arrived; there is no automatic retry. **Check receipt** only queries its receipt.

Trailing CR/LF line endings are removed from the payload, so Review and sending use the same single line. Internal line breaks, input above 4096 bytes and unsupported characters show a reason beside the input.

**Attach images:** when the selected pane has a verified working folder and the bridge has Pillow, tap the paperclip and then the photo icon. Choose any number of JPEG, PNG or static WebP images within the 10-attachment limit for this input. Each image may be up to 10 MiB and 24 megapixels. The thumbnail list scrolls within a bounded height. Each **×** removes only that image and excludes its path from the text prepared for confirmation. HEIC and animated images are not supported. Images upload one at a time in selection order without sending any input. If a save fails, the remaining uploads stop and the successfully attached images and your draft remain. Check the attachment list before sending. The bridge corrects orientation and writes fresh pixels without EXIF/GPS or other original metadata to `.orrery-input-images/<random>.jpg|png` inside that agent's working folder. The editing field keeps your words and the thumbnail list. Pressing ↑ combines your words with each image’s `[image: '<absolute path>']` for the ordinary Review input and Send once confirmation; Edit keeps your words and attachments. The byte count and 4 KiB limit include the complete line and all image paths. The agent then opens the path with its native image tool; its model must support images. There is no new dashboard API or change to text-only sending.

To **attach a file**, tap the paperclip and then the file icon. Each uploaded file may be up to 50 MiB, and images use their own 10 MiB limit. You can attach up to 10 items per input, including images. The bridge saves the original file bytes under a random name in `.orrery-input-files` inside the verified workspace. The original filename appears in the composer and in **Review input**. Check the destination and the line containing the `[file: '<absolute path>']` reference, then tap **Send once**. Use **Edit** to return to the composer and **×** to remove a reference from the draft. The workspace keeps up to 50 saved files and clears files older than seven days on the next file upload.

The dedicated folder contains a `.gitignore` with `*`. Saving another image removes generated image files older than seven days; at most 50 current images fit in one folder. Removing a thumbnail, cancelling or closing does not delete the saved file immediately, and a path in an older conversation may stop working after cleanup. Folder synchronization and backups still follow the working folder's policy. On macOS and Windows **WSL2**, the relay, bridge and local harness use the same Linux/POSIX path and implementation. Prefer a WSL Linux working folder; `/mnt/c/...` also keeps its WSL path, and Windows ACLs/DrvFS settings can override requested `0700`/`0600` modes. Those modes do not make a Windows-shared folder private. Native Windows processes or remote/container harnesses that cannot read the same path are not covered. If Pillow, a usable working folder or the updated bridge is unavailable, ＋ stays hidden and text-only sending remains available.


This is a terminal operation you confirm by inspecting the pane. Changes of program or a return to a shell within the same pane are not guaranteed to be detected. Text may be interpreted by that shell, combined with existing input or another writer, or sent after the screen changes. The feature does not clear input buffers or interrupt the pane before sending.

Close, pane changes and leaving the page stop polling and clear the display, draft and unsent confirmation. Late responses cannot restore them. Moving to the background only pauses requests: the view and draft stay in memory, and returning rechecks the pane before input is enabled. Confirmations still expire after 30 seconds. Reloading after Android discards the page restores the agent name and tab from sessionStorage, with a fresh record and empty draft. If Mail instance/agent IDs were saved, they must match the current roster regardless of whether phone sending is on, off or using a legacy pane; a missing or different identity leaves the agent list open for a new selection. A legacy selection without saved IDs still restores by name. Content is not placed in URLs, logs, browser storage or a server preview cache. This does not erase existing PC recorder output or OS recording/screenshots. Actual Android keyboard behavior, Serve/phone policy and real panes need separate acceptance; isolated HTTP/CDP checks do not establish them.

To disable only Terminal, set the shared field to `false` or remove it, also remove any explicit `--enable-mobile-terminal` from custom backend arguments, and remove those three reader flags. Restart both processes through their existing procedures; leaving them running does not disable the feature. Viewing settings and unrelated Serve entries can remain.

<a id="read-an-agents-conversation-history-on-your-phone"></a>

## Follow an agent's work in Reader

Open **Conversation** to follow the agent’s work. Reader organizes messages, tool activity, and results such as tables into a view you can follow on a phone. Tool operations appear in collapsible groups, and file chips open previews. Use **Show older** to look back when needed.

Speaker headings show a portrait (initials when unavailable), a small provider logo, the agent name and the time. Mail uses the same portraits and logos, preserving the sender's name first. Multiple recipients show all portraits and names when they fit, switching to overlapping portraits and a remaining-recipient count `+N` when space is short. All recipient names remain in the title and accessible label. A peer outside the roster gets only a name, or counts toward `+N` in the portrait-only row. Decorative portraits and initials stay out of selections across messages. High and urgent use a small dot before the subject. Compaction summaries remain short activity lines, separate from human messages.

**History is part of Phone access and is on by default once the policy is reviewed (`--phone-policy-reviewed`, or I reviewed the policy in Settings).** **Before you update:** a reader you start by hand with `--phone-policy-reviewed` and without `--enable-history` shows conversation history and file and image previews on the phone after the first restart. To keep them off, add `--disable-history` before restarting. The reader also says so in one line when it starts. Without the review the reader still starts with History off, and `/view/history` answers `policy_not_reviewed`. It shows the read-only conversation record (Codex, Claude Code, dsh, Hermes) that cockpit has verified as the agent's own, and is an exception to "full history is not forwarded" only while History is on. To keep it off, add `--disable-history` to a reader started by hand. Settings has no conversation-only switch; turn Phone access off instead. With History on, the phone can also open the current contents of files that tool calls mention inside the agent's working folder and images embedded in the conversation (preview below). There is no separate switch for this. **Nothing is hidden by name or masked:** what to show is the owner's call (see below). The agent can do the steps below; review access first.

| Step | Who | What |
|---|---|---|
| 1 | agent | Confirm Telemetry API 35 or later and that the ORRERY cockpit backend is running on the same computer (default port 8791). Cockpit reads the record; the reader does not |
| 2 | **you** | Review who can open the reader, as for Terminal. With History on, every device that can open the reader can read back through past conversations, not only a 120-line terminal tail, and open the current contents of files and images inside the agent's working folder that those conversations mention. Conversation text, file text and images reach the phone as they are, so they can contain keys or private writing |
| 3 | agent | Check that the reader's launch command has `--phone-policy-reviewed` (and `--cockpit-port` if it is not 8791). Run `--check` with the same flags first (it prints `conversation history and previews are on`), then restart the reader through its current manager. An existing `--enable-history` still works |
| 4 | **you** | Open an agent on the phone and check the **Conversation** tab. Tap a file chip ending in **›** and check that a preview opens and **Close** removes it |

When enabled, the header says **History enabled** (or **History · Terminal**) and the entry buttons become **History**. Opening an agent shows **Conversation full screen**, with a thin bar for portrait, name, state, Conversation/Terminal and **×**. Every bar button has a touch target at least 44 px square. When Terminal is enabled, the input stays at the bottom. Opening the view does not focus input or open the keyboard. This guide holds the explanations; unverified records, disconnections and send failures remain visible. Until a pane is verified, input and ↑ are disabled. Use **Refresh panes** to check again. **×** closes the view; Back/Escape first closes a preview, then leaves focused input, and otherwise closes the view. The persistent input alone does not trap Back. **Working** adds the recorded turn duration only when available, such as **Working · 2m05s**; otherwise it says only **Working**. A short red row marks a reply needed.


- The phone sends only an agent name from the displayed roster and, for **Show older**, a page token the reader issued (valid for 10 minutes and renewed while the latest page is polled), and, to open a file, a reference ID the reader issued on the same terms. The phone sends no file path. Transcript cursors and cockpit reference IDs stay on the PC. The reader calls one fixed loopback cockpit route, `GET /telemetry/conversation`. Cockpit resolves the dashboard's bound record itself and rechecks it after reading. Content is not masked (see below).
- Only a **bound** record is shown. Unbound, stale or unconfirmed agents show only a short explanation and a reason code such as `binding_missing`, with no record text.
- One page holds at most 40 entries and 512 KiB. Each message is cut at 16 KiB, each Mail body at 16 KiB, and shortening is marked. When a page is full, the entries that did not fit come with the next **Show older** instead of being skipped. A single entry too large for a page is cut further and marked as shortened. If something still cannot be shown, **Some messages are omitted here** marks the place. Tool calls appear as one-line names; tool output is not sent. Files and images appear as name chips (preview below). Jumping from a message to the terminal line is not available on the phone.
- Edit and Write steps for Claude Code and Codex can show added and removed line counts. Tap one to read its recorded diff inline. The page initially carries the counts only. A tapped diff is limited to 400 lines and 64 KiB and rendered as plain text. Demo mode masks the path and lines with the same rules as the Reader.
- Tap a Claude Code Bash or Codex Shell step to open its recorded command and output inline. A known nonzero exit code appears before the step is opened. The phone fetches the command and output for that step on tap. Commands are capped at 8 KiB and output at 400 lines or 64 KiB, whichever comes first. The first eight output lines appear initially, with **Show N more lines** to expand them. Terminal controls are removed and Demo mode applies the same masking rules as the Reader.
- A chip that can be opened is shown as a button (ending in **›**); tapping it shows a preview over the conversation. The reader calls the fixed loopback cockpit route `GET /telemetry/conversation/preview`. On every read, cockpit checks that the record and binding are unchanged, that the file is inside the agent's working folder (or a root set on the PC), that the path is canonical and not a symlink, its type, size and pixel count. A file is never refused for its name. The preview shows the first 32 KiB of a text file and displays **Showing the start of the file** when truncated. The conversation renderer displays Markdown, and wide tables scroll horizontally. Use the source icon to edit the Markdown. Raw HTML and SVG display as text. Cockpit resizes images as needed for the phone and redraws them as pixels-only PNG. The reader checks the result (only IHDR, IDAT and IEND chunks; at most 8192 px a side, 8 Mpx and 4 MiB). Files above the source read limits, unsupported types and files outside the roots show only the reason. The preview shows the **current file**, which may differ from what was recorded, and says so below it. Once a preview is shown, **Save** downloads the available text, any edits to Markdown source, or the re-drawn PNG to the device without reading the file again. HTML, SVG and XML are saved as text, with `.txt` added to the name. On Android and iOS it is a normal browser download into Downloads or Files; on iOS, long-press the image to put it in Photos instead. Saved files stay on the device; Close does not remove them. Ordinary file chips use references taken from tool calls. Cockpit attaches no reference to a file that is outside the roots or of a type it does not preview, so that chip shows only the name and cannot be tapped.
- Assistant messages render bold, headings, lists, tables and code, with **COPY** for code and tables. Raw HTML stays text. HTTP(S)/mailto links can open a separate tab. `!` records group into **SHELL** commands and output, each with copy; long output folds open. Generated notifications show only a short activity summary; system details such as task IDs and output paths are not forwarded. Recorded ORRERY Mail cards open their body without reading, acknowledging or replying to Mail. See the [bundled source and sync check](https://github.com/gyroid-eth/orrery-telemetry/blob/master/dashboard/mobile/MARKDOWN_SOURCE.md).
- When the computer is busy, cockpit can take several seconds to check the record and binding, so **Loading the record…** may stay for a few seconds before the first page. The reader waits up to 15 seconds; if cockpit still has not answered, **Taking longer than usual** and **Retry** appear. Waiting or tapping it reads again, and messages already shown stay.
- While the tab is in the foreground, the latest page updates about every 5 seconds. New entries do not move the view while you read earlier text; following pauses while you read, and resumes at the bottom. Up to 200 entries are kept; **Show older** stops at that limit. An expired page token reloads the latest page.
- Sending keeps the existing Terminal path. With Terminal enabled and a pane chosen, use the persistent input shared by both tabs and the same **↑ (Review input) → Send once** confirmation, limits and receipts. Review replaces the input in place on the current tab and shows the destination, exact text and following Enter, without a terminal tail inside confirmation. With a legacy connection and multiple tmux panes for the same agent, the picker still shows window and pane numbers. Choosing another pane discards the previous confirmation and draft. A missed preview leaves the draft and last verified terminal view in place. If previews keep failing, the Reader reconnects and rechecks the pane. If the Reader reports **Pane changed**, use **Refresh panes** and review again. Even when input starts from Terminal, sending returns to Conversation with the sent bubble at the tail. A successful receipt clears after about three seconds. Check receipt queries an unknown outcome without sending again. While preparing, sending, or awaiting an unknown receipt, changing panes or starting new input cannot discard that receipt. After **Received by terminal**, a local pending row disappears when the same text arrives in a subsequent record, with **Dismiss**, or after at most 3 minutes. `!` matches its SHELL record. This row exists only on this screen and does not prove agent receipt.
- **Reply with reference:** Long-press and select text to show the button below the selection. Only the body of one message can be referenced; a selection across messages is not offered. Tapping it adds a speaker, time and quotation card above input. **×** removes the reference while retaining the reply. Selection prevents tab swipes and survives ordinary history polls. Review shows one line: `Reference: <agent> · <role> · <ts> | Recorded message: <id> | Quote: "<quotation>" | Reply: <reply>`. JSON escapes preserve line breaks in the quote. The Reader shows a reference card for recorded replies in both the one-line mobile format and the multiline desktop format. The 4096-byte limit includes the reference, reply and image paths; over-limit input shows a reason and disables Review without silently cutting the quote. A reference is blocked if the selected agent or pane, or the Reader mount/reset, changes; remove it and select again. A Claude user body consisting only of one same-id `pasted_content` envelope is unwrapped for display and matching; mismatched IDs and mixed text stay literal.
- Markdown images in assistant messages and recorded Mail appear inline when cockpit issues a reference. Tap an image for the full preview. PNG, JPEG, GIF and WebP targets can use absolute or home-relative paths, including paths outside the working folder. Cockpit opens the resolved path without following symlinks at read time, enforces size and pixel limits, and redraws images as PNG. When a preview is unavailable, the Reader shows the description and path. HTTP(S) images are links that open only when tapped.
- When an assistant puts an absolute PNG, JPEG, GIF or WebP path on a line by itself, cockpit can issue a reference under the same image rules. Tap the path to fetch and open the preview.
- Close, switching agents and leaving the page stop updates and clear the record, page tokens, reference IDs, any open preview (including image data) and pending rows from the phone. Late responses cannot restore them. Backgrounding pauses requests while keeping the view and position in memory. A preview interrupted while loading is fetched again from the same reference on return; a completed preview stays open. Only the agent name, tab and available Mail identity IDs enter sessionStorage for reload; record text, drafts and previews do not enter URLs, logs or browser storage. Tokens the reader already issued stay in the reader until they expire; they carry no text and work only for the same agent.

**Nothing is masked.** Files are not hidden by name and content is not redacted: what is shown is the record and the file as they are, and the owner decides what may be shown. Keys, secrets pasted into a prompt and private writing in conversation text, Mail bodies, file text and images reach the phone as written. Files with secret-looking names (such as `credentials.yaml` or `api_key.md`) open too if they are inside the working folder and of a previewable type and size (files of types it does not preview, such as an extensionless `.env` or key files, still do not open). Tool output is not sent, but anything an agent repeated from it is. Turn History on only for agents and devices where that is acceptable.

To disable History only, add `--disable-history` to a reader started by hand (removing `--enable-history` if present) and restart it through its existing procedure. Terminal and viewing settings remain.

## Disable and restore

For the WSL2 Settings workflow, follow [the undo steps above](#use-phone-access-on-wsl2). On macOS, turn **Phone access** off in cockpit Settings (or run `agentstack-mobile off`) to remove the launchd job and its plist. If you started the reader by hand, press Ctrl-C in its terminal. For a Serve listener you added by hand, remove that entry with the matching command.

```sh
tailscale serve --https=9443 off
```

If you used additional flags, [repeat the original flags with off](https://tailscale.com/docs/reference/tailscale-cli/serve). Do not use `serve reset`, which removes unrelated entries. Compare the remaining Serve configuration with the saved output and confirm that only the dedicated entry was removed. If a policy rollback is needed, have the administrator revert only this change. Stopping the reader clears its in-memory snapshot and observed status history; it does not stop Telemetry or Mail.

See the [API contract](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/api.en.md#mobile-reader-api-30) for authentication, routes and projected fields.

### Explicit fresh use

Follow the [fresh guide](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/fresh-global-update.en.md) to verify the same host/UID/context and new I. Start the dashboard before the matching Cockpit backend. Ordinary service/Finder startup uses the shared loader for saved fresh references, while real-environment startup/display acceptance remains separate; API34 alone does not authorize production cutover. Human opt-in stays off by default.

Fresh resolves the selected I/A to its current native/socket/pane and uses only the same bridge already managed by the PC manager. It never falls back through a display name, last pane or old project/DB. Choice, preview, confirmation, one send and status retain the same I/A and target. Preview waits at most three seconds and confirmed submission five seconds; timeout/unknown is not automatically resent. The normal 30-second confirmation, 4 KiB body limit and read/ACK separation remain. Real phone/provider/trust and installation acceptance are separate.
