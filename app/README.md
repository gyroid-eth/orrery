# ORRERY desktop app

Tauri v2 shell for the ORRERY cockpit. It opens
`http://127.0.0.1:8791/cockpit.html` and shows a bundled retry screen while the
backend is offline.

From this directory:

```sh
npm install
npm run dev
```

The app tries `Cmd+Shift+O`, `Cmd+Ctrl+O`, `Cmd+Alt+O`, then `Cmd+Shift+F19`
and uses the first available global shortcut to toggle the window.
The selected binding is logged at startup. Registration failure is non-fatal,
and a dev process can temporarily retain a binding that the built `.app` can
claim once that process exits. Verify one hide/show cycle manually with the
binding reported by the built app.
