# ORRERY Orbit icon

`orrery.svg` and `orrery-light.svg` are the approved dark/light sources.
Their geometry is identical. The light palette follows the existing warm-paper
theme. Do not redraw either export when updating the header or application icons.

From `app/`, use the installed Tauri CLI without changing dependencies:

```sh
node node_modules/@tauri-apps/cli/tauri.js icon icons-src/orrery.svg --output src-tauri/icons
node node_modules/@tauri-apps/cli/tauri.js icon icons-src/orrery.svg --output /tmp/orrery-icon-source --png 1024
node node_modules/@tauri-apps/cli/tauri.js icon icons-src/orrery-light.svg --output /tmp/orrery-icon-light --png 512
cp /tmp/orrery-icon-source/1024x1024.png icons-src/orrery-1024.png
cp /tmp/orrery-icon-light/512x512.png src-tauri/icons/icon-light.png
cp icons-src/orrery.svg ../bridge/orbit.svg
cp icons-src/orrery-light.svg ../bridge/orbit-light.svg
```

Use empty output directories for temporary exports. The default icon command
regenerates the existing platform set; it does not build or install the app.
The existing Rust theme switch uses `icon.png` and `icon-light.png` for the
Dock. Header exports are byte copies of the SVG sources. Browser captures
verify the header; they do not verify OS icon caches or every platform bundle.
