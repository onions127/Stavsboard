# TODOS

## Sensors card (temps / fans)
- **What:** Show CPU temperature and fan speed.
- **Why:** Glances shows them, and overheating is a common "why is my fan loud" answer.
- **Pros:** Answers thermal questions at a glance on Linux.
- **Cons:** psutil has no Windows support. Every known Windows method (WMI, LibreHardwareMonitor)
  needs admin, which Stavsboard never uses, so the card is blank on the main Windows dev machine.
- **Context:** Deferred in /plan-ceo-review on 2026-11-03 (decision D2). Start with
  `psutil.sensors_temperatures()` / `sensors_fans()` behind a feature check; hide the card where
  unsupported.
- **Effort:** human M / CC S
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
