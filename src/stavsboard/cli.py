"""`stavsboard` command: start the collectors and serve the dashboard."""

from __future__ import annotations

import argparse
import errno
import logging
import socket
import sys

DEFAULT_PORT = 8420
_IN_USE = {errno.EADDRINUSE, 10048, errno.EACCES, 10013}  # incl. Windows WSAEADDRINUSE / WSAEACCES


def bind(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return port


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="stavsboard", description="A calm, read-only dashboard for this machine.")
    p.add_argument("--port", type=_port, default=DEFAULT_PORT, help=f"port to serve on (default {DEFAULT_PORT})")
    p.add_argument("--lan", action="store_true",
                   help="also serve on your local network (no login: anyone on it can view and switch refresh mode)")
    p.add_argument("--mode", choices=("accurate", "low"), default="accurate",
                   help="refresh mode at start: accurate (1s) or low (2s, lighter); change it later in Settings")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    try:
        sock = bind(host, args.port)
    except OSError as exc:
        if exc.errno in _IN_USE or getattr(exc, "winerror", None) in _IN_USE:
            print(f"Port {args.port} is already in use (or blocked). Try: stavsboard --port {args.port + 1}",
                  file=sys.stderr)
            return 1
        raise

    import uvicorn

    from .app import create_app
    from .collect import HostCollector
    from .docker_poll import DockerPoller
    from .store import Store

    logging.basicConfig(level=logging.INFO, format="stavsboard: %(message)s")
    store = Store(mode=args.mode)
    host_collector = HostCollector(store)
    docker_poller = DockerPoller(store)
    host_collector.start()
    docker_poller.start()

    hostname = socket.gethostname()
    app = create_app(store, lan=args.lan, hostname=hostname)
    print(f"Stavsboard is running at http://localhost:{args.port}")
    if args.lan:
        print(f"On your network: http://{hostname}:{args.port} or http://<this machine's IP>:{args.port}")
        print("Note: there is no login. Anyone on your network can see process names and switch refresh mode.")
    print("Press Ctrl+C to stop.")

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    try:
        server.run(sockets=[sock])
    finally:
        host_collector.stop()
        docker_poller.stop()
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
