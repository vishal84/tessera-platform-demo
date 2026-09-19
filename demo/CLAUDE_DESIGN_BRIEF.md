# Claude Design brief — Tessera Console

Paste the block below into Claude Design. The variable names are the contract
the UI expects (`web/src/styles/tokens.css`); replace values, never names, and
the whole console restyles without touching a component.

---

Design a light and dark theme for "Tessera Console", an internal payments-platform operations console used live on stage in a 50-minute demo, viewed on a projector at 1080p. Tone: calm, dense, engineering-grade (an SRE dashboard, not a marketing site). Output the result as CSS custom properties with exactly these names, with values for `:root` (light) and `[data-theme="dark"]`:

Surfaces and text: `--color-bg`, `--color-surface`, `--color-surface-2`, `--color-border`, `--color-text`, `--color-text-2`, `--color-text-muted`, `--color-accent`, `--color-accent-contrast`, `--color-focus`.
Status (fixed meaning; an icon and label always accompany them): `--status-good`, `--status-warning`, `--status-serious`, `--status-critical`, `--status-info`, `--status-neutral`.
Personas: `--persona-sre`, `--persona-swe`, `--persona-ds`, `--persona-claude` — four distinct hues usable as chips and as timeline node colours, distinguishable from the status colours.
Chart series, fixed order, never cycled: `--series-1` … `--series-4` (fraud-model rps, cache hit rate, p99 latency, auth success rate — each in its own panel), plus `--chart-grid`, `--chart-axis`, `--chart-marker-deploy`, `--chart-marker-alert`, `--chart-cursor`.
Typography: `--font-sans`, `--font-mono` (a monospace with tabular figures for metrics), `--text-xs`, `--text-sm`, `--text-base`, `--text-lg`, `--text-xl`, `--text-2xl`, `--text-3xl` (hero numbers), `--leading-tight`, `--leading-normal`.
Spacing and shape: `--space-1` … `--space-8` (4 px base), `--radius-sm`, `--radius-md`, `--radius-lg`, `--shadow-1`, `--shadow-2`.

Constraints: all text/surface pairs meet WCAG AA; adjacent chart series stay distinguishable under deuteranopia and protanopia; status colours are never reused as series colours; the dark theme is a selected palette, not an inversion. Also give guidance for these components: metric tile (label, hero value, delta, status pill), status pill, persona chip, agent activity row (tool name, target path in mono, elapsed time, allow/deny badge), PR card (title, branch in mono, commit list, diff stat), incident timeline (vertical rail, persona-coloured nodes, handoff arrows), code/diff block (mono, added/removed line backgrounds), gate card (PASS / BLOCKED / NOT IMPLEMENTED states), and a full-width "RECORDING" banner unmistakable from the back of a room. Return the CSS block first, then the component notes.

---

## Applying the output

1. Replace the values in `web/src/styles/tokens.css` (keep both blocks: `:root` and `[data-theme="dark"]`).
2. If it names web fonts, add the `<link>` in `web/index.html`; the fallbacks already cover a machine without them.
3. `npm --prefix web run build` (or just `./demo/up.sh`, which rebuilds when sources change).
