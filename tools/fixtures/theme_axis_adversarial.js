(() => {
  const root = document.documentElement;
  const pick = (selector, property, pseudo = null) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    const computed = getComputedStyle(element, pseudo);
    return computed.getPropertyValue(property).trim();
  };
  const snapshot = () => ({
    active: activeThemeAxis(),
    attr: root.getAttribute('data-theme-axis'),
    smallAttr: root.getAttribute('data-theme-small-text'),
    trackingAttr: root.getAttribute('data-theme-tracking'),
    runtimeStyle: Boolean(document.getElementById(THEME_AXIS_RUNTIME_STYLE_ID)),
    dimColor: pick('.colhead .tag', 'color'),
    bgColor: pick('body', 'background-color'),
    smallFontSize: pick('.settings-help', 'font-size'),
    smallFontWeight: pick('.settings-help', 'font-weight'),
    trackingSpacing: pick('.settings-section-title', 'letter-spacing'),
    glowShadow: pick('.layout-picker', 'box-shadow'),
    amberGlow: getComputedStyle(root).getPropertyValue('--amber-glow').trim(),
  });

  if (activeThemeAxis()) setThemeAxis(activeThemeAxis(), null);
  const baseline = snapshot();
  const normal = [];
  for (const axis of THEME_AXIS_IDS) {
    for (const value of [.25, .5, .75, 1]) {
      const ok = setThemeAxis(axis, value);
      const after = snapshot();
      setThemeAxis(axis, null);
      const restored = snapshot();
      normal.push({ axis, value, ok, after, restored });
    }
  }
  const zero = THEME_AXIS_IDS.map(axis => {
    const ok = setThemeAxis(axis, 0);
    return { axis, ok, active: activeThemeAxis(), attr: root.getAttribute('data-theme-axis') };
  });
  return {
    baseline,
    normal,
    zero,
    final: {
      active: activeThemeAxis(),
      runtimeStyle: Boolean(document.getElementById(THEME_AXIS_RUNTIME_STYLE_ID)),
    },
  };
})()
