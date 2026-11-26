// Source: orrery-telemetry/dashboard/local_model_makers.js. The cockpit
// bundles an identical copy for standalone use. Each maker key names its SVG
// in the HTTP allowlists as well as in the browser.
window.OrreryLocalModelMakers = {
  "deepseek": {"label": "DeepSeek", "aspect": 1.3587945413191813, "model": "deepseek"},
  "qwen": {"label": "Qwen", "aspect": 1, "model": "qwen"},
  "glm": {"label": "GLM", "aspect": 1, "model": "(?:^|[^a-z0-9])glm"},
  "thinking-machines": {"label": "Thinking Machines Lab", "aspect": 1, "model": "(?:^|/)inkling[-_ ]?2[-_ ]?mini(?=$|[-_. ])"}
};

window.orreryLocalModelMaker = (() => {
  const matches = Object.entries(window.OrreryLocalModelMakers)
    .map(([maker, entry]) => [maker, new RegExp(entry.model, 'i')]);
  return (model, allowed = () => true) => {
    for (const [maker, pattern] of matches) {
      if (allowed(maker) && pattern.test(model)) return maker;
    }
    return '';
  };
})();
