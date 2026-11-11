# Stavsboard

A calm, read-only dashboard for one machine. One sentence tells you how it's doing ("All
calm."); green when healthy, amber or red only when something needs you. It shows CPU (with
per-core load and, on Linux, temperature), memory and swap, the top 10 processes, Docker
containers, recent warnings, and a Trends tab with the last 60 samples.

It runs on Linux and Windows, never needs admin rights, and never changes anything on the
machine: it only reads.

## Start it (one command)

You need [uv](https://docs.astral.sh/uv/) and git on your PATH. Then:

```bash
uvx --from git+https://github.com/onions127/Stavsboard stavsboard
```

Open <http://localhost:8420>. Press Ctrl+C to stop.

To update to the latest version later:

```bash
uvx --refresh --from git+https://github.com/onions127/Stavsboard stavsboard
```

### Options

| Flag | What it does |
|---|---|
| `--port 8420` | Port to serve on. If it's taken, Stavsboard says so and exits. |
| `--lan` | Also serve on your local network, so a phone or another PC can open it. |
| `--allow-host NAME` | Also accept requests addressed to `NAME`, e.g. the name of an HTTPS reverse proxy such as Tailscale Serve (`sterver.example.ts.net`). Repeatable, and works without `--lan`. Give a bare name: no `https://`, no port. |
| `--mode accurate` / `--mode low` | Refresh mode at start: Accurate (every second) or Low impact (every 2 seconds, lighter on the machine). You can switch it later under Settings. |

## Watching a server from another device (`--lan`)

Run it on the machine you want to watch:

```bash
uvx --from git+https://github.com/onions127/Stavsboard stavsboard --lan
```

Then open `http://<server-name-or-IP>:8420` from your PC or phone.

**There is no login.** While `--lan` is on, anyone on your network can see process names and
container names, and can switch the refresh mode (nothing else can be changed). Only use it on
a network you trust.

Stavsboard never changes firewall settings. If other devices can't connect:

- **Linux (ufw):** `sudo ufw allow 8420/tcp`
- **Linux (firewalld):** `sudo firewall-cmd --add-port=8420/tcp --permanent && sudo firewall-cmd --reload`
- **Windows:** accept the Windows Defender Firewall prompt the first time, or add an inbound
  rule for TCP port 8420.

### Behind an HTTPS reverse proxy (e.g. Tailscale Serve)

Stavsboard only answers requests addressed to names it knows, to block DNS-rebinding attacks.
A proxy forwards your browser's name (like `sterver.example.ts.net`), so name it with
`--allow-host` and leave `--lan` off, so Stavsboard listens on `127.0.0.1` only and the proxy
is the only way in:

```bash
uvx --from git+https://github.com/onions127/Stavsboard stavsboard --allow-host sterver.example.ts.net
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8420
```

## Containers

If Docker is running and your user may talk to it, a Containers list appears with each
container's CPU (a share of Docker's CPUs) and memory. If Docker isn't running, the list is
hidden. If your user lacks access, it says "No access to Docker"; on Linux, add your user to
the `docker` group. Stavsboard never asks for elevated rights.

## Start it automatically (optional)

Stavsboard doesn't install anything that runs at startup. If you want that:

**Linux (systemd user service)**: save as `~/.config/systemd/user/stavsboard.service`:

```ini
[Unit]
Description=Stavsboard

[Service]
ExecStart=%h/.local/bin/uvx --from git+https://github.com/onions127/Stavsboard stavsboard --lan
Restart=on-failure

[Install]
WantedBy=default.target
```

Then run `systemctl --user enable --now stavsboard`. To keep it running after you log out, also
run `loginctl enable-linger $USER`.

**Windows (Task Scheduler)**: create a task that runs at log on, with the program
`uvx` and the arguments `--from git+https://github.com/onions127/Stavsboard stavsboard`.

Warnings and the log live in memory, so they start fresh each time Stavsboard starts. The log
header shows "Watching since" with that time.

## What the colors mean

| Warning | Amber | Red |
|---|---|---|
| CPU | 90% or more for 10s | (never) |
| Memory | 90% or more for 10s | 97% or more for 10s |
| Swap | 50% or more while memory is 90% or more, for 30s | 80% or more, same rule |
| CPU temperature (Linux) | 85°C or more for 10s | 95°C or more for 10s |
| Container | | It crashed (exited with a non-zero code; `docker stop` does not count, an out-of-memory kill does) or restarted 3 times in 5 minutes |

A warning clears once the value stays 10 points below the amber line for 10s. Red steps back
to amber once it stays 3 points below the red line for 10s.

## Development

```bash
uv sync
uv run pytest
uv run stavsboard
```

`uv run python tests/demo_server.py` serves the real page with scripted data for every visual
state (calm, warnings, errors, 64 cores, no Docker, disconnected, and so on) at
<http://localhost:8421>.

Fonts: Instrument Serif and Schibsted Grotesk, both under the SIL Open Font License (see
`src/stavsboard/static/fonts/`).
