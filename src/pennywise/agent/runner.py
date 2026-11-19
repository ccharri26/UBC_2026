"""Runner: run agent cycles once or on repeat, settling finished Events after each one.

One Runner runs one cycle at a time. A cycle is run_cycle() (rule) or run_llm_cycle()
(llm), then scoring.settle() so outcomes keep up with the log. Both are blocking and
print to the console as usual.

  runner = Runner()
  runner.run_once()               # one cycle now, in the caller's thread
  runner.start(every_seconds=120)  # repeat in a background thread
  runner.status()                 # plain dict for a dashboard / API
  runner.stop()

Safety: the runner adds no spending path. Every purchase still goes through
get_signals() -> pay() and every guardrail, and the kill switch still applies: while it
is on no cycle runs, and a repeat run stops after the cycle in which it turned on. On top
of that, a Runner refuses to run a cycle while NANSEN_STUB is off unless it was
created with allow_live=True (checked before every cycle, because .env can change
while a loop is running).

The interval is measured start to start and clamped to [MIN_EVERY, MAX_EVERY]. Faster
loops don't spend more on Nansen (the cache and budgets cap that); they only add Grok
calls and log rows. A repeat run stops by itself after `max_cycles`, or after
MAX_FAILURES failed cycles in a row.

CLI:
  uv run python -m pennywise.agent.runner --once
  uv run python -m pennywise.agent.runner --every 2m [--cycles 30] [--mode rule|llm] [--live]
"""

import argparse
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from pennywise.agent import grok
from pennywise.nansen import stub_mode
from pennywise.payments.control import kill_switch_on
from pennywise.scoring.settle import settle

Mode = Literal["rule", "llm"]

MIN_EVERY = 60  # seconds: a Grok cycle can take 10-30 s, and 5M contracts need ~1-2 min
MAX_EVERY = 3600
MAX_FAILURES = 3  # failed cycles in a row before a repeat run stops itself


class RunnerBusy(RuntimeError):
    """A cycle is already running (or a repeat run is active)."""


@dataclass(frozen=True)
class CycleReport:
    started_at: str
    finished_at: str
    mode: Mode
    stub: bool
    ok: bool
    error: str | None  # short label, e.g. "ConfigError: GROK_MODEL is not set"
    settle: dict[str, int] | None  # settle() counts, or None if settling failed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short(e: BaseException) -> str:
    text = f"{type(e).__name__}: {e}"
    return text if len(text) <= 200 else text[:197] + "..."


def _cycle_fn(mode: Mode) -> Callable[[], None]:
    if mode == "llm":
        from pennywise.agent.llm import run_llm_cycle  # imported lazily: needs the openai SDK

        return run_llm_cycle
    from pennywise.agent.cycle import run_cycle

    return run_cycle


class Runner:
    def __init__(self, allow_live: bool = False) -> None:
        self.allow_live = allow_live
        self._cycle_lock = threading.Lock()  # held while a cycle runs: never two at once
        self._state_lock = threading.Lock()  # guards the fields below
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._every: int | None = None
        self._mode: Mode | None = None  # None = AGENT_MODE from .env, read each cycle
        self._max_cycles: int | None = None
        self._cycles_done = 0  # in the current repeat run
        self._failures = 0  # in a row
        self._next_at: datetime | None = None
        self._stopped_because: str | None = None
        self._last: CycleReport | None = None

    # --- one cycle ---------------------------------------------------------------

    def run_once(self, mode: Mode | None = None) -> CycleReport:
        """Run one cycle now and settle. Raises RunnerBusy if a cycle is already running."""
        if not self._cycle_lock.acquire(blocking=False):
            raise RunnerBusy("a cycle is already running")
        try:
            return self._run(mode)
        finally:
            self._cycle_lock.release()

    def _run(self, mode: Mode | None) -> CycleReport:
        mode = mode or grok.agent_mode()
        started, stub = _now(), stub_mode()
        error = None
        if not stub and not self.allow_live:
            error = "live mode not allowed: set NANSEN_STUB=true or create the runner with allow_live"
        elif kill_switch_on():
            error = "kill switch is on"
        else:
            try:
                _cycle_fn(mode)()
            except Exception as e:  # a bad cycle must not kill the loop
                error = _short(e)
        settled = None
        try:
            settled = settle()
            print(f"  settle: {settled['settled']} Events settled, {settled['not_yet']} not yet, {settled['errors']} errors")
        except Exception as e:
            print(f"  settle failed: {_short(e)}")
        report = CycleReport(
            started_at=started.isoformat(),
            finished_at=_now().isoformat(),
            mode=mode,
            stub=stub,
            ok=error is None,
            error=error,
            settle=settled,
        )
        if error:
            print(f"  cycle failed: {error}")
        with self._state_lock:
            self._last = report
        return report

    # --- repeat ------------------------------------------------------------------

    def start(self, every_seconds: float, mode: Mode | None = None, max_cycles: int | None = None) -> None:
        """Run a cycle now, then every `every_seconds` (clamped), in a background thread."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                raise RunnerBusy("already running on repeat; stop it first")
            if max_cycles is not None and max_cycles < 1:
                raise ValueError("max_cycles must be at least 1")
            self._every = int(min(max(every_seconds, MIN_EVERY), MAX_EVERY))
            self._mode = mode
            self._max_cycles = max_cycles
            self._cycles_done = 0
            self._failures = 0
            self._stopped_because = None
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="pennywise-runner", daemon=True)
            self._thread.start()

    def stop(self, wait: bool = False) -> None:
        """Stop after the current cycle (a running cycle is never cut off mid-way)."""
        self._stop.set()
        with self._state_lock:
            if self._stopped_because is None and self._thread is not None and self._thread.is_alive():
                self._stopped_because = "stopped"
            thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join()

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = _now()
            with self._cycle_lock:  # waits for a run_once() that is in progress
                if self._stop.is_set():
                    break
                report = self._run(self._mode)
            with self._state_lock:
                self._cycles_done += 1
                self._failures = 0 if report.ok else self._failures + 1
                if kill_switch_on():
                    self._stopped_because = "kill switch is on"
                elif self._max_cycles is not None and self._cycles_done >= self._max_cycles:
                    self._stopped_because = f"finished {self._cycles_done} cycles"
                elif self._failures >= MAX_FAILURES:
                    self._stopped_because = f"{self._failures} failed cycles in a row"
                if self._stopped_because:
                    self._stop.set()
                    break
                self._next_at = started + timedelta(seconds=self._every or MIN_EVERY)
            wait = (self._next_at - _now()).total_seconds()
            if wait > 0:
                self._stop.wait(wait)
        with self._state_lock:
            self._next_at = None

    # --- status ------------------------------------------------------------------

    def status(self) -> dict:
        """Plain JSON-safe dict: numbers, timestamps and short labels."""
        with self._state_lock:
            repeating = self._thread is not None and self._thread.is_alive() and not self._stop.is_set()
            return {
                "repeating": repeating,
                "cycle_running": self._cycle_lock.locked(),
                "every_seconds": self._every if repeating else None,
                "mode": self._mode or grok.agent_mode(),
                "stub_mode": stub_mode(),
                "allow_live": self.allow_live,
                "cycles_done": self._cycles_done,
                "max_cycles": self._max_cycles,
                "failures_in_a_row": self._failures,
                "next_run_at": self._next_at.isoformat() if repeating and self._next_at else None,
                "stopped_because": None if repeating else self._stopped_because,
                "last": asdict(self._last) if self._last else None,
            }


# --- CLI -----------------------------------------------------------------------------


def parse_duration(text: str) -> int:
    """Seconds from "90", "90s", "2m" or "1h"."""
    text = text.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        if text and text[-1] in units:
            return int(float(text[:-1]) * units[text[-1]])
        return int(float(text))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a duration: {text!r} (use e.g. 90, 90s, 2m, 1h)") from None


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m pennywise.agent.runner", description=__doc__.split("\n")[0])
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--once", action="store_true", help="run one cycle and exit")
    what.add_argument("--every", type=parse_duration, help=f"repeat interval, e.g. 2m (min {MIN_EVERY}s)")
    p.add_argument("--cycles", type=int, help="stop after this many cycles")
    p.add_argument("--mode", choices=["rule", "llm"], help="default: AGENT_MODE in .env")
    p.add_argument("--live", action="store_true", help="allow cycles with NANSEN_STUB off (spends real USDC)")
    args = p.parse_args(argv)

    if not stub_mode() and not args.live:
        sys.exit("NANSEN_STUB is off, so cycles may buy real Nansen data. Pass --live to allow it.")
    runner = Runner(allow_live=args.live)
    if args.once:
        report = runner.run_once(args.mode)
        sys.exit(0 if report.ok else 1)

    every = min(max(args.every, MIN_EVERY), MAX_EVERY)
    if every != args.every:
        print(f"interval clamped to {every}s")
    runner.start(every, mode=args.mode, max_cycles=args.cycles)
    print(f"running every {every}s (mode={args.mode or grok.agent_mode()}); Ctrl+C stops after the current cycle")
    try:
        while runner.status()["repeating"]:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        print("\nstopping after the current cycle...")
        runner.stop(wait=True)
    print(f"runner stopped: {runner.status()['stopped_because']}")


if __name__ == "__main__":
    main()
