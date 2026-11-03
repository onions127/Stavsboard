# TODOS

## Design polish left by /design-review (2026-11-03)
- **What (all low impact):**
  - Screen readers can't hear the non-calm dot on the "Now" tab; add hidden "(warning)" text and an `aria-label` like "Warning log, 4 entries" on "Log · N".
  - Motion: washes fade out with ease-out (DESIGN.md says exits use ease-in); the 150ms Now/Trends crossfade isn't implemented; the drawer closes without an exit slide.
  - The underline control is styled three ways (tabs 400 weight / 3px offset, `.seg` 500 / 1px); merge into one rule.
  - Off-scale details: 2px radius on swatches and on focused elements (use 3px or none), tabular figures on static log times, a 13px Settings button next to 14px tabs.
  - The cached memory segment still uses `good-soft` (1.45:1 on light ground); it has a legend, so lower priority than the core bars were.
- **Why:** None blocks a task; together they are the last 10% of polish.
- **Priority:** P3

## ~~Overlapping poll loops after a tab switch (QA ISSUE-002)~~
- **Fixed by /review on main, 2026-11-03:** only the newest poll paints and schedules the next one.
- **What:** Guard `poll()` in `static/app.js` so a call while a fetch is in flight doesn't start a second timer.
- **Why:** Switching tabs, waking the page or changing the refresh mode mid-fetch can briefly double the request rate.
- **Severity / category:** Low / Functional. Loops converge on the next tick; data is never wrong.
- **Repro:** Open the page, switch Now ↔ Trends quickly several times, watch `/api/snapshot` requests in DevTools.
- **Context:** Found by /qa on 2026-11-03 (main); deferred under the Standard fix tier.
- **Priority:** P3

## Fan speeds (sensors, remainder)
- **What:** Show fan speeds next to the CPU temperature.
- **Why:** Answers "why is the fan loud?" more directly on Linux.
- **Pros:** Completes the sensors picture on the Linux server.
- **Cons:** psutil `sensors_fans()` is Linux-only and often empty on servers; Windows needs admin.
- **Context:** D2 deferred all sensors in /plan-ceo-review. On 2026-11-03 /plan-eng-review (D17-B)
  brought CPU temperature into v1 once the monitored machine turned out to be a Linux server.
  Fans stay deferred. Start with `psutil.sensors_fans()` behind the same feature check as
  `cpu.temp_c`; hide where unsupported.
- **Effort:** human S / CC S
- **Priority:** P3
- **Depends on:** v1 shipped.

## PWA manifest
- **What:** Web app manifest + icons so Stavsboard installs to a phone home screen.
- **Why:** Makes "check from afar" feel like an app.
- **Pros:** Nicer phone experience.
- **Cons:** The install prompt needs HTTPS, which plain-HTTP LAN access doesn't have; a bookmark
  covers most of the value.
- **Context:** Deferred in /plan-ceo-review on 2026-11-03 (decision D6).
- **Effort:** human S / CC S
- **Priority:** P3
- **Depends on:** a decision on HTTPS for `--lan`.

## Live-test Docker on Windows (Docker Desktop named pipe)
- **What:** Run the container section against a real Docker Desktop on Windows.
- **Why:** v1 tests the Windows Docker path only with a fake client (D18-A); the docker SDK talks
  to Docker Desktop over a named pipe through pywin32, which differs from the Linux socket.
- **Pros:** Proves containers work when Stavsboard watches a Windows machine.
- **Cons:** Needs Docker Desktop (admin/UAC install, WSL2).
- **Context:** Added in /plan-eng-review on 2026-11-03 (D22-A). Start with
  `docker.from_env()` on Windows, then the D13 sparse-list + inspect flow and the 3s timeouts.
- **Effort:** human S / CC S
- **Priority:** P3
- **Depends on:** a Windows host with Docker Desktop that someone wants to monitor.
