/* Light-mode receiver for the embedded telemetry dashboard.
 *
 * The cockpit has posted `orrery-color-theme` at its iframe since light mode
 * landed, and waits for `orrery-color-theme-ready` / `-result` in return.  The
 * dashboard served at :8770 has no such receiver — it is a separate clone with
 * no theme system at all — so the message went nowhere and NETWORK stayed dark
 * inside an otherwise light cockpit.
 *
 * This file supplies the missing half.  The backend injects it into the relayed
 * HTML rather than the dashboard shipping it, which means it applies to
 * whichever clone happens to be behind the proxy, and stops applying by itself
 * once a clone brings its own receiver (the injector checks for one first).
 *
 * The palette is not duplicated here.  The cockpit sends the same derived
 * variables it uses on itself, so the two surfaces cannot drift apart.
 */
(() => {
  'use strict';
  if (window.__orreryTelemetryLight) return;
  window.__orreryTelemetryLight = true;
  if (window.parent === window) return; /* opened directly, not embedded */

  const root = document.documentElement;
  /* Remembered so dark can be restored by removing exactly what was added,
     rather than by writing a second palette that would then need maintaining. */
  let applied = [];

  /* Three variables the dashboard defines that the cockpit's theme does not.
     Two are glows, which light mode suppresses everywhere else; the third is
     the scrollbar's deeper amber, which becomes the light accent itself. */
  const EXTRA = {
    '--amber-deep': 'rgb(var(--theme-accent-rgb))',
    '--glow-a': 'none',
    '--glow-ink': 'none',
    /* The cockpit sets this to transparent, because light mode drops glows.
       The dashboard also uses it as a hover wash, so transparent there costs
       the button its only press feedback.  A faint tint is a wash, not a glow. */
    '--amber-glow': 'rgb(var(--theme-accent-rgb) / .14)',
  };

  /* The dashboard spells its accent out by hand in a hundred and fifty places —
     rgba(242,182,90,α), the same colour again as rgba(255,176,46,α), and a
     handful of #f2b65a.  On paper that amber sits at almost exactly the
     luminance of the page, so every one of them renders as nothing: the NEW
     AGENT button lost its border, chips lost their edges, and the whole surface
     read as having no accent at all.
     Listing them in a stylesheet is not maintainable at that count and would
     rot against a clone this repo does not own, so they are rewritten in place
     instead.  Only the accent family is treated this way.  The near-black
     literals are left to telemetry_light.css by hand, because those need a
     judgement a substitution cannot make: some mean "chrome" and some mean
     "recessed", and recessed points the opposite way in the two themes. */
  const ACCENT_LITERALS = [
    /rgba\(\s*242\s*,\s*182\s*,\s*90\s*,/g,
    /rgba\(\s*255\s*,\s*176\s*,\s*46\s*,/g,
  ];
  const ACCENT_HEX = /#f2b65a\b/gi;
  /* Restored verbatim on the way back to dark. */
  let rewritten = [];

  function accentChannels(variables) {
    const raw = variables['--theme-accent-rgb'];
    return typeof raw === 'string' && /^\s*\d+\s+\d+\s+\d+\s*$/.test(raw)
      ? raw.trim().split(/\s+/).join(',')
      : null;
  }

  function substitute(value, channels, hexValue) {
    let out = value;
    ACCENT_LITERALS.forEach(pattern => {
      out = out.replace(pattern, 'rgba(' + channels + ',');
    });
    if (hexValue) out = out.replace(ACCENT_HEX, hexValue);
    return out;
  }

  function rewriteAccentLiterals(variables) {
    const channels = accentChannels(variables);
    if (!channels) return 0;
    const hexValue = variables['--amber'];
    let count = 0;
    Array.prototype.forEach.call(document.styleSheets, sheet => {
      /* Our own sheet is already written against the variables. */
      if (sheet.href && sheet.href.indexOf('telemetry_light.css') !== -1) return;
      let rules;
      /* Cross-origin sheets throw on access; there should be none, but a
         thrown exception here would abort the whole theme apply. */
      try { rules = sheet.cssRules; } catch (_) { return; }
      if (!rules) return;
      Array.prototype.forEach.call(rules, rule => {
        const style = rule.style;
        if (!style) return;
        for (let i = 0; i < style.length; i += 1) {
          const prop = style[i];
          const value = style.getPropertyValue(prop);
          if (value.indexOf('242, 182, 90') === -1 && value.indexOf('242,182,90') === -1 &&
              value.indexOf('255, 176, 46') === -1 && value.indexOf('255,176,46') === -1 &&
              !ACCENT_HEX.test(value)) { ACCENT_HEX.lastIndex = 0; continue; }
          ACCENT_HEX.lastIndex = 0;
          const next = substitute(value, channels, hexValue);
          if (next === value) continue;
          rewritten.push([style, prop, value, style.getPropertyPriority(prop)]);
          style.setProperty(prop, next, style.getPropertyPriority(prop));
          count += 1;
        }
      });
    });
    return count;
  }

  function restoreAccentLiterals() {
    rewritten.forEach(entry => entry[0].setProperty(entry[1], entry[2], entry[3]));
    rewritten = [];
  }

  function clear() {
    restoreAccentLiterals();
    applied.forEach(name => root.style.removeProperty(name));
    applied = [];
    root.removeAttribute('data-color-theme');
  }

  function applyLight(variables) {
    clear();
    const merged = Object.assign({}, variables, EXTRA);
    Object.keys(merged).forEach(name => {
      root.style.setProperty(name, merged[name]);
      applied.push(name);
    });
    root.setAttribute('data-color-theme', 'light');
    rewriteAccentLiterals(variables);
  }

  function apply(data) {
    /* A light message with no variables would silently produce a half-themed
       page, which is the failure this file exists to remove.  Refuse it and say
       so in the result, so the cockpit's recovery path can see it. */
    if (data.resolved === 'light' && !data.variables) {
      return { ok: false, reason: 'light requested without variables' };
    }
    if (data.resolved === 'light') applyLight(data.variables);
    else clear();
    return { ok: true, resolved: data.resolved, count: applied.length };
  }

  function post(message) {
    try { window.parent.postMessage(message, window.location.origin); }
    catch (_) { /* parent went away; nothing to report to */ }
  }

  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.type !== 'orrery-color-theme' || data.version !== 1) return;
    const result = apply(data);
    post({ type: 'orrery-color-theme-result', version: 1, themeId: data.themeId, ...result });
  });

  /* The cockpit only sends the theme in response to this, so a reload of the
     iframe re-synchronises rather than coming back dark. */
  post({ type: 'orrery-color-theme-ready', version: 1 });
})();
