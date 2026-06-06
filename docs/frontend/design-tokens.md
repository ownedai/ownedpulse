# Frontend Design Tokens

## CSS Variables (`:root`)

```css
--shell-bg:           #0F172A;
--shell-surface:      #1E293B;
--shell-border:       #334155;
--shell-muted-text:   #94A3B8;
--shell-accent:       #60A5FA;

--panel-bg:           #F8FAFC;   /* light theme default */
--panel-surface:      #FFFFFF;
--panel-text:         #0F172A;
--panel-text-secondary: #64748B;
--panel-accent:       #2563EB;
--panel-accent-hover: #1D4ED8;
--panel-accent-bg:    #DBEAFE;

--success: #10B981;
--warning: #F59E0B;
--error:   #EF4444;

/* Status tokens for new pages */
--status-ok:      #22c55e;
--status-error:   #ef4444;
--status-warn:    #f59e0b;
--status-info:    #3b82f6;
--status-running: #3b82f6;  /* use with pulse animation */
```

Pulse animation for running status:
```css
@keyframes status-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.status-running { animation: status-pulse 1.5s ease-in-out infinite; }
```

## Dark Theme (`[data-theme="dark"]`)

```css
--panel-bg:           #1E293B;
--panel-surface:      #0F172A;
--panel-text:         #F8FAFC;
--panel-text-secondary: #94A3B8;
```

Shell always dark. Toggle affects panel only.

## Typography

Fonts:
- `@fontsource/inter` — body text
- `@fontsource/jetbrains-mono` — chunk text (REQUIRED)

Hierarchy:
- Answer: Inter 16px / line-height 1.75 / 400 / primary text
- Disclaimer: Inter 13px / italic / secondary text
- Citation section heading: Inter 13px uppercase / secondary
- Citation card title: Inter 14px / 500
- Citation metadata: Inter 12px / secondary
- Chunk text in Zone 4: JetBrains Mono 12px / 1.6

Logo: outlined square + filled circle, inline SVG (Logo.jsx).

## Theme Toggle

- Button top right of top nav bar
- Icon: sun (light active) / moon (dark active)
- Click toggles `data-theme="dark"` on document root
- CSS uses `[data-theme="dark"] :root { ... }` to override panel variables
- Persisted in localStorage as `regpulse-theme`
- Tooltip: "Switch to light mode" / "Switch to dark mode"
