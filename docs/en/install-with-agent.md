# Get help installing ORRERY from your agent

[日本語](../install-with-agent.md) · [Quick start](../../README.en.md#get-started)

If you already use Claude Code or Codex CLI, paste the request below into that conversation. Tell the agent which machine and working folder you want to use.

```text
Help me install the browser cockpit and Telemetry on this machine using the ORRERY README.
First check the OS and prerequisites and show me the install plan and which paths will change.
Wait for my approval before changing files or settings. Hand installer confirmations and sign-ins back to me.
Do not read API keys, tokens, or the contents of my key store.
Tell me the doctor and selftest results, the browser URL, and any steps still pending.
```

1. Review the [one-line install plan](install.md#install-or-update-with-one-line) with your agent. Use `--check` for the plan or `--dry-run` for the detailed settings preview. Confirm the working folder, ports, treatment of any existing Mail service, and the user settings affected.
2. When you are ready, type `yes` yourself in the terminal that shows the installer plan. Review OS permissions and Codex hooks, and sign in to providers yourself. For API access, save keys in the OS key store and give the agent only the references needed for setup.
3. Open the reported URL in your browser and check for **Your first flight**. Use the [feature setup table](install.md#add-the-features-you-use) to prepare the features you want.
