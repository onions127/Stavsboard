import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from stavsboard import cli

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_port_in_use_exits_1_with_hint(capsys):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert cli.main(["--port", str(port)]) == 1
    err = capsys.readouterr().err
    assert f"Port {port} is already in use" in err and f"--port {port + 1}" in err


def test_flags():
    args = cli.parse_args(["--lan", "--mode", "low", "--port", "9000"])
    assert args.lan and args.mode == "low" and args.port == 9000
    assert cli.parse_args([]).port == cli.DEFAULT_PORT
    with pytest.raises(SystemExit):
        cli.parse_args(["--mode", "turbo"])


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_wheel_installs_and_serves_page_and_font(tmp_path):
    """C2: the installed wheel (what uvx runs) must carry the static files."""
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=ROOT, check=True,
                   capture_output=True)
    wheel = next(dist.glob("stavsboard-*.whl"))
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "--python", "3.12", str(venv)], check=True, capture_output=True)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(py), str(wheel)], check=True, capture_output=True)
    exe = venv / ("Scripts/stavsboard.exe" if os.name == "nt" else "bin/stavsboard")
    port = free_port()
    proc = subprocess.Popen([str(exe), "--port", str(port)], cwd=tmp_path, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                page = urllib.request.urlopen(base + "/", timeout=2).read().decode()
                break
            except OSError:
                if time.monotonic() > deadline or proc.poll() is not None:
                    raise
                time.sleep(0.3)
        assert "Stavsboard" in page
        font = urllib.request.urlopen(base + "/static/fonts/instrument-serif-400.woff2", timeout=5).read()
        assert font[:4] == b"wOF2"
        snap = urllib.request.urlopen(base + "/api/snapshot", timeout=5).read()
        assert b'"status"' in snap
    finally:
        proc.terminate()
        proc.wait(10)
