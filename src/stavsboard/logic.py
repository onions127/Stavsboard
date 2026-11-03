"""Pure warning logic: thresholds, sustain windows, the warning log, status and title.

Nothing here reads the clock or the system. Callers pass monotonic time (`mono`, for
sustain windows) and wall time (`wall`, epoch seconds shown to people).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

NONE, WARNING, ERROR = 0, 1, 2
LEVEL_NAMES = {NONE: "good", WARNING: "warning", ERROR: "error"}

LOG_SIZE = 100  # D3
RESUME_GAP_S = 5.0  # C4: a longer gap between ticks means the machine slept
CULPRIT_SHARE = 0.25  # blame a process group only if it holds >= 25% of the load
RESTART_LOOP_COUNT = 3  # D4: >= 3 restarts ...
RESTART_LOOP_WINDOW_S = 300.0  # ... within 5 minutes


@dataclass(frozen=True)
class Rule:
    """One metric's thresholds (D2, D17, D19, D20). Times in seconds."""

    key: str
    subject: str
    unit: str
    amber: float
    red: float | None
    sustain_s: float
    clear_s: float = 10.0
    clear_below: float = 10.0  # clears this far below the amber line
    step_down_below: float = 3.0  # red steps down to amber this far below the red line
    gate_ram: float | None = None  # swap only counts while RAM is this high (D19)


CPU = Rule("cpu", "CPU", "%", amber=90, red=None, sustain_s=10)
RAM = Rule("ram", "RAM", "%", amber=90, red=97, sustain_s=10)
SWAP = Rule("swap", "Swap", "%", amber=50, red=80, sustain_s=30, gate_ram=90)
TEMP = Rule("temp", "CPU", "°C", amber=85, red=95, sustain_s=10)
RULES = (CPU, RAM, SWAP, TEMP)

# Which Now-tab section washes for which warning kind.
SECTION_OF = {"cpu": "cpu", "temp": "cpu", "ram": "mem", "swap": "mem", "container": "containers"}


def _fmt_value(value: float, unit: str) -> str:
    return f"{round(value)}{unit}"


def _gb(n_bytes: float) -> str:
    gb = n_bytes / 1024**3
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{round(n_bytes / 1024**2)} MB"


@dataclass
class _RuleState:
    level: int = NONE
    since: dict[str, float | None] = field(default_factory=dict)  # condition -> start mono
    entry: dict | None = None


class Engine:
    """Turns host samples and container lists into warnings, a log and a status."""

    def __init__(self, started_wall: float):
        self.started_wall = started_wall
        self.log: deque[dict] = deque(maxlen=LOG_SIZE)
        self.active: dict[str, dict] = {}  # warning id -> log entry
        self._rules = {r.key: _RuleState() for r in RULES}
        self._last_mono: float | None = None
        self._next_id = 1
        self._ctrs: dict[str, dict] = {}  # container id -> tracking state
        self._last_sample: dict | None = None

    # ---- host metrics -------------------------------------------------------------

    def update_host(self, sample: dict, mono: float, wall: float) -> None:
        """sample: {"cpu", "ram", "swap" (None if no swap), "temp" (None if unknown)} in % / °C,
        plus "groups" for blame and "mem_used" / "swap_used" / "swap_total" bytes."""
        if self._last_mono is not None and mono - self._last_mono > RESUME_GAP_S:
            self.reset_sustain()
        self._last_mono = mono
        self._last_sample = sample
        ram = sample.get("ram")
        for rule in RULES:
            value = sample.get(rule.key)
            if value is None:
                continue
            if rule.gate_ram is not None and ram is None:
                continue
            self._step(rule, self._rules[rule.key], value, ram, mono, wall)

    def reset_sustain(self) -> None:
        for st in self._rules.values():
            st.since.clear()

    def _held(self, st: _RuleState, cond: str, ok: bool, mono: float, window: float) -> bool:
        if not ok:
            st.since[cond] = None
            return False
        if st.since.get(cond) is None:
            st.since[cond] = mono
        return mono - st.since[cond] >= window

    def _step(self, rule: Rule, st: _RuleState, v: float, ram: float | None, mono: float, wall: float):
        gate = rule.gate_ram
        gated = gate is None or (ram is not None and ram >= gate)
        amber_on = v >= rule.amber and gated
        red_on = rule.red is not None and v >= rule.red and gated
        clear_on = v < rule.amber - rule.clear_below or (
            gate is not None and ram is not None and ram < gate - rule.clear_below
        )
        step_on = rule.red is not None and (
            v < rule.red - rule.step_down_below
            or (gate is not None and ram is not None and ram < gate - rule.step_down_below)
        )

        red_held = self._held(st, "red", red_on, mono, rule.sustain_s)
        amber_held = self._held(st, "amber", amber_on, mono, rule.sustain_s)
        clear_held = self._held(st, "clear", clear_on, mono, rule.clear_s)
        step_held = self._held(st, "step", step_on and st.level == ERROR, mono, rule.clear_s)

        new = st.level
        if st.level == NONE:
            new = ERROR if red_held else WARNING if amber_held else NONE
        elif st.level == WARNING:
            new = ERROR if red_held else NONE if clear_held else WARNING
        elif st.level == ERROR:
            new = NONE if clear_held else WARNING if step_held else ERROR

        if st.entry is not None:
            st.entry["peak"] = max(st.entry["peak"], v)
            st.entry["peak_text"] = _fmt_value(st.entry["peak"], rule.unit)
            st.entry["value_text"] = _fmt_value(v, rule.unit)
        if new == st.level:
            return
        if new == NONE:
            self._close(st.entry, wall)
            st.entry = None
        elif st.entry is None:
            st.entry = self._open(rule.key, rule.subject, new, wall, peak=v, unit=rule.unit)
        st.level = new
        if st.entry is not None:
            st.entry["level"] = LEVEL_NAMES[new]
            if new > LEVEL_NAMES_INV[st.entry["peak_level"]]:
                st.entry["peak_level"] = LEVEL_NAMES[new]
            st.entry["label"] = _metric_label(rule, new)
        # A level change restarts the way-down windows; a raise in progress keeps counting.
        if new == NONE:
            st.since.clear()
        else:
            st.since.pop("clear", None)
            st.since.pop("step", None)

    # ---- containers ---------------------------------------------------------------

    def update_containers(self, items: list[dict], mono: float, wall: float) -> None:
        """items: [{"id", "name", "state", "exit_code", "restart_count"}] from one successful
        list call. Warns on a seen running -> exited (code != 0) transition or a restart
        loop (D4). Containers already exited when first seen never warn."""
        seen = set()
        for c in items:
            cid = c["id"]
            seen.add(cid)
            tr = self._ctrs.get(cid)
            if tr is None:
                tr = self._ctrs[cid] = {"state": c["state"], "restarts": deque(), "exit_entry": None,
                                        "loop_entry": None, "name": c["name"]}
                self._record_restart(tr, c.get("restart_count"), mono)
                continue
            prev = tr["state"]
            tr["state"] = c["state"]
            tr["name"] = c["name"]
            code = c.get("exit_code")
            crashed = prev == "running" and c["state"] == "exited"
            if crashed and code is None:
                tr["pending_exit"] = True  # exit code not known yet; decide on a later poll
            if c["state"] != "exited":
                tr["pending_exit"] = False
            elif tr.get("pending_exit") and code is not None:
                crashed, tr["pending_exit"] = True, False
            if crashed and code not in (None, 0):
                if tr["exit_entry"] is None:
                    tr["exit_entry"] = self._open(f"exit:{cid}", c["name"], ERROR, wall,
                                                  kind="container", label=f"{c['name']} exited (code {code})")
                    tr["exit_entry"]["exit_code"] = code
            elif c["state"] == "running" and tr["exit_entry"] is not None:
                self._close(tr["exit_entry"], wall)
                tr["exit_entry"] = None
            self._record_restart(tr, c.get("restart_count"), mono)
            looping = self._restarts_in_window(tr, mono) >= RESTART_LOOP_COUNT
            if looping and tr["loop_entry"] is None:
                tr["loop_entry"] = self._open(f"loop:{cid}", c["name"], ERROR, wall,
                                              kind="container", label=f"{c['name']} restarting repeatedly")
            elif not looping and tr["loop_entry"] is not None:
                self._close(tr["loop_entry"], wall)
                tr["loop_entry"] = None
        for cid in list(self._ctrs):
            if cid not in seen:  # removed: clears its warnings
                tr = self._ctrs.pop(cid)
                for key in ("exit_entry", "loop_entry"):
                    if tr[key] is not None:
                        self._close(tr[key], wall)

    def _record_restart(self, tr: dict, count: int | None, mono: float) -> None:
        if count is None:
            return
        hist = tr["restarts"]
        if not hist or hist[-1][1] != count:
            hist.append((mono, count))
        while len(hist) > 1 and mono - hist[1][0] > RESTART_LOOP_WINDOW_S:
            hist.popleft()

    def _restarts_in_window(self, tr: dict, mono: float) -> int:
        # hist[0] is the last count seen at or before the window start (the baseline).
        hist = tr["restarts"]
        if len(hist) < 2:
            return 0
        return hist[-1][1] - hist[0][1]

    # ---- log ----------------------------------------------------------------------

    def _open(self, wid: str, subject: str, level: int, wall: float, *, peak: float | None = None,
              unit: str = "", kind: str | None = None, label: str = "") -> dict:
        entry = {
            "id": self._next_id,
            "kind": kind or wid,
            "subject": subject,
            "level": LEVEL_NAMES[level],
            "peak_level": LEVEL_NAMES[level],
            "label": label,
            "start": wall,
            "end": None,
            "peak": peak if peak is not None else 0,
            "peak_text": _fmt_value(peak, unit) if peak is not None else None,
            "value_text": _fmt_value(peak, unit) if peak is not None else None,
        }
        self._next_id += 1
        self.log.append(entry)
        self.active[wid] = entry
        return entry

    def _close(self, entry: dict | None, wall: float) -> None:
        if entry is None:
            return
        entry["end"] = wall
        for wid, e in list(self.active.items()):
            if e is entry:
                del self.active[wid]

    # ---- outputs ------------------------------------------------------------------

    def active_list(self) -> list[dict]:
        """Worst first: error before warning, then newest."""
        return sorted(self.active.values(), key=lambda e: (LEVEL_NAMES_INV[e["level"]], e["start"]),
                      reverse=True)

    def section_levels(self) -> dict[str, str]:
        out = {"cpu": NONE, "mem": NONE, "containers": NONE}
        for e in self.active.values():
            sec = SECTION_OF[e["kind"]]
            out[sec] = max(out[sec], LEVEL_NAMES_INV[e["level"]])
        return {k: LEVEL_NAMES[v] for k, v in out.items()}

    def log_entries(self) -> list[dict]:
        return [_public(e) for e in reversed(self.log)]

    def status(self) -> dict:
        return compose_status(self.active_list(), self._last_sample)

    def title(self) -> str:
        return compose_title(self.active_list())


LEVEL_NAMES_INV = {v: k for k, v in LEVEL_NAMES.items()}


def _public(e: dict) -> dict:
    keys = ("id", "kind", "subject", "level", "peak_level", "label", "start", "end", "peak_text", "value_text")
    return {k: e.get(k) for k in keys}


def _metric_label(rule: Rule, level: int) -> str:
    line = rule.red if level == ERROR and rule.red is not None else rule.amber
    return f"{rule.subject} above {_fmt_value(line, rule.unit)}"


def _culprit(sample: dict | None, which: str, total: float | None) -> dict | None:
    if not sample or not total:
        return None
    groups = (sample.get("groups") or {}).get(which) or []
    if not groups:
        return None
    top = groups[0]
    if top["value"] < total * CULPRIT_SHARE:
        return None
    return top


def _who(group: dict) -> str:
    if group["count"] > 1:
        return f"{group['name']} ({group['count']} processes)"
    return group["name"]


def compose_status(active: list[dict], sample: dict | None) -> dict:
    """The serif sentence (DR4, D21): the worst active warning plus how many more."""
    if not active:
        return {"level": "good", "text": "All calm.", "more": 0, "key": "calm"}
    worst = active[0]
    kind, level = worst["kind"], worst["level"]
    s = sample or {}
    if kind == "cpu":
        g = _culprit(s, "cpu", s.get("cpu"))
        text = "CPU is busy" + (f": {_who(g)} is using {round(g['value'])}%." if g else ".")
    elif kind == "ram":
        head = "Memory is nearly full" if level == "error" else "Memory is high"
        g = _culprit(s, "ram", s.get("mem_used"))
        text = head + (f": {_who(g)} is using {_gb(g['value'])}." if g else ".")
    elif kind == "swap":
        head = "Swap is nearly full" if level == "error" else "Swap is busy"
        used, total = s.get("swap_used"), s.get("swap_total")
        text = head + (f": {_gb(used)} of {_gb(total)} in use." if used is not None and total else ".")
    elif kind == "temp":
        head = "CPU is very hot" if level == "error" else "CPU is hot"
        text = f"{head}: {worst['value_text']}."
    else:  # container
        if worst["label"].endswith("restarting repeatedly"):
            text = f"Container {worst['subject']} keeps restarting."
        else:
            text = f"Container {worst['subject']} exited with code {worst.get('exit_code', '?')}."
    return {"level": level, "text": text, "more": len(active) - 1, "key": f"{level}:{kind}:{worst['id']}"}


def compose_title(active: list[dict]) -> str:
    """Tab title (DR17). The client overrides it for Connecting / Disconnected."""
    if not active:
        return "Stavsboard"
    w = active[0]
    if w["kind"] == "container":
        short = f"{w['subject']} restarting" if w["label"].endswith("restarting repeatedly") else f"{w['subject']} exited"
    else:
        short = f"{w['subject']} {w['value_text']}"
    return f"● {short} · Stavsboard"
