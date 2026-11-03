---
# gstack: design-md-format=spec
name: Stavsboard
description: A quiet, crafted instrument for one machine. Calm stone surfaces, green when healthy, amber and red only when something needs you.
colors:
  ground: "#E3E7E1"
  ink: "#1E2422"
  text-muted: "#5F6963"
  text-muted-on-wash: "#4F5853"
  track: "#CDD3CC"
  rule: "#D3D9D2"
  good: "#1F8A4C"
  good-soft: "#9CCBAE"
  good-text: "#17703D"
  warning: "#C98A00"
  warning-text: "#8A5A00"
  warning-wash: "#F1E2B8"
  error: "#C2361F"
  error-text: "#B4301B"
  error-wash: "#F4D5CB"
  dark-ground: "#181C1E"
  dark-ink: "#E3E6E1"
  dark-text-muted: "#8D9691"
  dark-text-muted-on-wash: "#A3ABA6"
  dark-track: "#2E3539"
  dark-rule: "#272D31"
  dark-good: "#4CC38A"
  dark-good-soft: "#2C5E45"
  dark-warning: "#E8B23A"
  dark-warning-wash: "#3A2E12"
  dark-error: "#FF6A4D"
  dark-error-text: "#FF7A5E"
  dark-error-wash: "#3D1A14"
typography:
  display:
    fontFamily: Instrument Serif
    fontWeight: 400
    fontSize: clamp(1.75rem, 1.4rem + 1.2vw, 2.125rem)
    letterSpacing: 0em
  number:
    fontFamily: Schibsted Grotesk
    fontWeight: 500
    fontSize: 4.5rem
    letterSpacing: -0.02em
    fontFeature: tnum
  body:
    fontFamily: Schibsted Grotesk
    fontSize: 0.875rem
    lineHeight: 1.5
  label:
    fontFamily: Schibsted Grotesk
    fontWeight: 500
    fontSize: 0.8125rem
    letterSpacing: 0em
rounded:
  sm: 3px
  md: 6px
  lg: 10px
  app: 12px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 40px
---

# Stavsboard

## Overview

**Creative North Star:** a quiet instrument on your desk. It reads like a well-made object,
not a server console, because the user asked for "beautiful, not techy".
**Product context:** a self-hosted, single-machine system monitor (Windows + Linux). It's
viewed in a half-width browser tab or on a phone over the LAN. Peers: Glances, Beszel,
Netdata, Homepage, Homarr.
**Mode per surface:** Now tab = Operate (glance). Trends tab = Read (short history).
**Reference sites:** beszel.dev, netdata.cloud, gethomepage.dev, homarr.dev (2026-11-03).
**Key characteristics:**
- One serif sentence says how the machine is doing before any number.
- Green graphics when healthy; amber or red graphics plus a soft wash when not.
- No card boxes, gauges-in-tiles, glows or gradients. Sections sit on one surface.
- Numbers never jitter: tabular figures, instant swaps.

## Colors

**Strategy:** restrained, with semantic status. Neutrals carry the layout. `good` green
marks healthy state (the status dot, CPU arc, memory ring, per-core bars, running
containers). `warning` amber and `error` red appear only for trouble. The contrast between
good and bad is a hue jump (green to amber/red) plus a background wash on the affected
section, so state reads from across a room.
**Light or dark:** both. The default follows the OS (`prefers-color-scheme`), with a
manual toggle. Daytime desk use favors light; checking a phone at night favors dark.
Dark surfaces keep the same hierarchy: ground, then washes, with ink lightened rather than
simply inverted. Green and red are brightened in dark mode to hold contrast.
Text-on-color uses the `*-text` tokens (e.g. `warning-text`), not the mark colors, to meet
4.5:1 on the ground. Inside a washed section, secondary text uses `text-muted-on-wash`
(light 5.72:1 / 5.34:1, dark 5.66:1 / 6.59:1 on amber / red washes); plain `text-muted` fails
there (4.13-4.42:1).

## Typography

- **Instrument Serif 400, upright** is used only for the status sentence ("All calm.",
  "Memory is high: chrome.exe is using 6.1 GB."). It's static text, so its proportional
  digits don't matter there. Never italic.
- **Schibsted Grotesk** is used for everything else. Big metric numbers are weight 500 with
  `font-variant-numeric: tabular-nums` (verified on 2026-11-03: "1" and "8" are both
  63.5px at 100px). Tabular figures are used only on numbers that update (big numbers,
  numeric table columns); small prose stays proportional, because tnum looks spaced at
  14px.
- Both are OFL and **self-hosted as woff2** in the app (no CDN; the dashboard may run
  offline on a LAN). Weights: Instrument Serif 400; Schibsted Grotesk 400, 500, 600.
- Scale: status 28-34px · number 52px (compact) / 72px (full) · body 14px · label 13px. Levels differ by size,
  not only by weight.

## Layout

- **Order (top to bottom):** app bar (wordmark, Now/Trends, Settings) → status
  sentence → recent-warnings line → CPU (left) + Memory (right) → Top processes (left) +
  Containers (right).
- **Desktop and half-width tab (>= 700px):** two equal columns, 40px gap, with one 1px
  `rule` between the gauge row and the lists. App padding is 24-28px.
- **Phone (< 700px):** a single column in the same order, 16px gutters, 22px gaps.
- **Gauges size by their column, not the viewport** (CSS container queries): column
  >= 430px = full (240×128 half-dial, 72px number); < 430px = compact (200×108, 52px);
  < 340px = the number stacks above the dial.
- **375px height budget:** app bar 40 · status ~80 (typical; the sentence wraps freely) ·
  warnings 24 · CPU 150 · memory 150 ≈ 520px, so about 4 process rows show above a 667px
  fold. Top 10 and containers continue below.
- Max content width is 1320px, left-aligned.

## Elevation & Depth

Flat. There are no shadows and no borders around sections. Depth comes only from the
status wash (`warning-wash` / `error-wash`) behind a section that's in trouble.

## Shapes

- CPU is a 180° half-dial, stroke 16, round caps (variant B).
- Memory is an 18px capacity bar (radius 9) split used / cached / free with 2px
  `ground`-colored gaps between segments. Swap is a 6px bar.
- Per-core bars use a 3px top radius.
- An alarm wash uses `rounded.lg` (10px). The app frame uses 12px. Nothing else is
  rounded.

## Components

- **Status sentence:** a 12px dot plus the serif sentence. The dot is `good`, `warning` or
  `error`, or a hollow `text-muted` ring when loading, disconnected or stalled. It names
  the worst active warning (error before warning, then newest) plus a muted "· N more".
  It wraps freely; it is never truncated.
- **Warnings line:** every active warning + the latest past item + a "Log · N" text
  button. Ongoing warnings use `warning-text` weight 600; past items are muted, with times
  in ink. When nothing is active, show "No active warnings" in `good-text` (contrast
  4.91:1; the mark color `good` is 3.5:1 and is only for graphics). "Log · N" expands an
  inline list (start, peak, duration, or "ongoing since HH:MM") headed "Watching since
  HH:MM".
- **CPU gauge:** half-dial + big number + a "16 cores" sub-line + per-core bars along the
  base, height = load. At most 32 bars: one per core up to 32 (3px gap, 1px above 16
  cores, min width 2px); above 32 cores, adjacent cores are grouped and each bar shows the
  busiest core ("64 cores · grouped"). Hot cores turn `warning`. It must never look like a
  grid of equal tiles.
- **Memory gauge:** big number + "x of y GB" + the capacity bar + a legend ("Used 4.5 GB ·
  Cached 3.2 GB · Free 8.3 GB") + the swap bar with "Swap x of y GB". Windows has no
  cached figure: used / free only, with a 2-item legend.
- **Trends tab:** one column of rows (CPU, Memory, Swap, then each running container's
  CPU). Row = label + current value (20px, tabular) + a full-width 40px sparkline, fixed
  0-100% scale, no axes, `good` line with over-threshold spans in the alarm hue. Muted
  caption "Last 60 seconds". A status dot beside the "Now" tab label shows non-calm state.
- **Settings panel:** a "Settings" text button in the app bar opens an inline panel (no
  modal, no card) with two rows using the underline pattern: Theme "Auto · Light · Dark"
  (default Auto, kept per device, applied before first paint) and Refresh "Accurate · Low
  impact" (server-wide; Low impact = 2s host refresh). Editable from any allowed viewer.
- **CPU temperature:** when the machine reports it (Linux), appended to the CPU sub-line
  ("16 cores · 54°C"); it takes the alarm hue when hot. Hidden where unsupported.
- **Alarm state (any gauge):** the graphic, number and sub-bar switch to `warning` or
  `error`, and a wash appears behind the gauge. The state switch fades in over 400ms.
- **Lists (processes, containers):** plain rows divided by `rule`. Numbers are
  right-aligned and tabular. The CPU/RAM toggle is text with a 2px ink underline on the
  active option. Container dots are `good` when running and `error` when exited; an
  exited container also shows red "exit N" text. Names are one line with an end
  ellipsis (full name in `title`); numeric columns are a fixed 72px. Rows reorder
  instantly; a row newly entering fades in over 150ms. Unavailable cells show a muted "—".
- **Stale / disconnected:** numbers in `text-muted` plus a muted sentence ("Disconnected,
  data 12s old"). This is never shown as calm green. Loading shows "—" and "Connecting…".
- **Tab title:** "Stavsboard" · "● RAM 91% · Stavsboard" · "○ Disconnected · Stavsboard".
- **Focus-visible:** a 2px ink outline with a 2px offset on every interactive element.
- **Hit areas:** at least 44×44px on every control, through padding.

## Do's and Don'ts

- Do: keep green on graphics and status marks, not on body text.
- Do: show trouble with a hue change plus a wash, both together.
- Do: update numbers instantly with tabular figures.
- Do: keep the status sentence short by template (condition, culprit, amount); it wraps
  rather than truncates.
- Don't: wrap sections in cards, add shadows, or nest containers.
- Don't: use a grid of equal tiles (pegboard) for cores, or any glowing edges or
  gradients.
- Don't: pulse or blink alarms.
- Don't: use the serif for numbers or the italic serif anywhere.

## Motion

- **Approach:** minimal-functional.
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** state wash 400ms · tab crossfade 150ms · arc/ring length 250ms ease-out
  (geometry only; numbers never tween).
- **The one authored moment:** when everything returns to normal, the wash fades out and
  the dot turns green.
- Respect `prefers-reduced-motion`: there are no transitions in that mode.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-11-03 | Initial design system created | Created by /design-consultation from the office-hours/CEO plan, research on 4 homelab dashboards, and an independent subagent direction |
| 2026-11-03 | Added green for healthy, high contrast vs amber/red | User request: "good colors like green" while staying calm |
| 2026-11-03 | Removed card boxes; new CPU arc + per-core bars and memory ring | User: "too blocky and cardy", "doesn't look like a pegboard" |
| 2026-11-03 | Layout: warnings top, CPU left, Memory right, lists below | User-specified layout |
| 2026-11-03 | Instrument Serif only for the status sentence | Measured: no tabular figures, so live numbers would jitter |
| 2026-11-03 | Now screen = variant B "Horizon bands" (/design-shotgun) | Wide CPU half-dial (72px number, per-core bars along base); memory used/cached/free bar + legend + swap bar. Cached segment Linux-only (psutil has none on Windows). Reference: docs/design/now-variants.html, section B |
| 2026-11-03 | /plan-design-review DR1-DR17 applied | Half-dial + capacity bar geometry, container-query gauge sizes (52/72px), 375px budget, max-32 per-core bars, `text-muted-on-wash` (old muted failed AA on washes), segment gaps, Log · N, Trends rows, Auto/Light/Dark, tab titles, 44px hit areas. See docs/designs/stavsboard-v1.md "Design Review Amendments" |
| 2026-11-03 | /plan-eng-review: Settings panel (Theme + Refresh mode), CPU temperature in the CPU sub-line | User asked for a low-impact/accurate refresh setting (D6/D7/D16); the monitored machine is a Linux server, so CPU temperature joined v1 (D17-B) |
