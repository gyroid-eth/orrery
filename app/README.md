# ORRERY desktop app

Tauri v2 shell for the ORRERY cockpit. It opens
`http://127.0.0.1:8791/cockpit.html` by default and shows a bundled retry
screen while the backend is offline.

## macOS

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

## Windows build

Prepare the Windows build environment once. Install Node.js with npm, the
[MSVC C++ Build Tools and Edge WebView2](https://v2.tauri.app/start/prerequisites/#windows),
and the [64-bit Rust MSVC toolchain](https://rust-lang.org/install). If the
build tools are already installed, the Windows Rust installer can be run as
the current user with `rustup-init.exe -y --profile minimal --default-host
x86_64-pc-windows-msvc`. Open a fresh PowerShell after setup and check
`rustc -V` and `npm.cmd -v`.

Open PowerShell in this directory and run the build.

```powershell
npm.cmd ci
npm.cmd run build -- --target x86_64-pc-windows-msvc
```

Run `npm.cmd ci` when preparing a checkout or when its lockfile changes.
The build produces the current-user NSIS installer in
`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`. The installer
expects an existing [ORRERY installation in WSL2](../docs/en/install.md#windows-desktop-app).
