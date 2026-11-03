# TODOS

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
