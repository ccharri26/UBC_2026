import { Loader2, Play, Square, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { getApprovalSettings, startRun, stopRun, type AgentMode, type RunnerStatus, type Status } from "../api";
import { Badge, Button, Modal, cx } from "../components/ui";
import { time, usd } from "../lib/format";

const SAVED_KEY = "pennywise.run"; // last choices, this browser only

interface Choices {
  mode: AgentMode;
  once: boolean;
  everyMinutes: string;
  maxCycles: string;
}

const DEFAULTS: Choices = { mode: "rule", once: false, everyMinutes: "2", maxCycles: "30" };

function loadChoices(): Choices {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVED_KEY) ?? "{}");
    return {
      mode: saved.mode === "llm" ? "llm" : "rule",
      once: saved.once === true,
      everyMinutes: typeof saved.everyMinutes === "string" ? saved.everyMinutes : DEFAULTS.everyMinutes,
      maxCycles: typeof saved.maxCycles === "string" ? saved.maxCycles : DEFAULTS.maxCycles,
    };
  } catch {
    return DEFAULTS;
  }
}

function saveChoices(c: Choices) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(c));
  } catch {
    // private window or blocked storage: the modal just starts from defaults next time
  }
}

export const runActive = (r: RunnerStatus | undefined) => !!r && (r.repeating || r.cycle_running);

function Choice<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-subtle p-0.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cx(
            "cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition",
            v === value ? "bg-surface text-ink shadow-sm" : "text-ink-3 hover:text-ink",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** Header button: Run (opens the modal) while idle, Stop during a repeating Run, "Running…" during a single Cycle. */
export function RunButton({
  runner,
  status,
  onRunner,
  onError,
}: {
  runner: RunnerStatus | undefined;
  status: Status | undefined;
  onRunner: (r: RunnerStatus) => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [choices, setChoices] = useState<Choices>(DEFAULTS);
  const [budget, setBudget] = useState("");
  const [confirmLive, setConfirmLive] = useState(false);
  const [threshold, setThreshold] = useState<number>();

  if (!runner) return null;
  const killSwitch = runner.kill_switch || !!status?.kill_switch;
  const cap = runner.per_run_cap_usd;

  function show() {
    setChoices(loadChoices());
    setBudget(cap !== null ? cap.toFixed(2) : "");
    setConfirmLive(false);
    setOpen(true);
    getApprovalSettings()
      .then((s) => setThreshold(s.threshold_usd))
      .catch(() => setThreshold(undefined));
  }

  const set = (patch: Partial<Choices>) => setChoices((c) => ({ ...c, ...patch }));
  const every = Number(choices.everyMinutes);
  const cycles = Number(choices.maxCycles);
  const budgetValue = Number(budget);
  const minMin = runner.min_every_seconds / 60;
  const maxMin = runner.max_every_seconds / 60;
  const problems = [
    !choices.once && !(every >= minMin && every <= maxMin) && `Repeat every ${minMin} to ${maxMin} minutes.`,
    !choices.once && !(Number.isInteger(cycles) && cycles >= 1 && cycles <= 1000) && "Stop after 1 to 1000 Cycles.",
    cap === null && "BUDGET_PER_RUN_USD in .env is missing or invalid.",
    cap !== null && !(budget.trim() !== "" && budgetValue >= 0 && budgetValue <= cap + 1e-9) && `Budget from $0.00 to ${usd(cap)}.`,
  ].filter((p): p is string => !!p);
  const live = !runner.stub_mode;

  async function start() {
    if (problems.length) return;
    setBusy(true);
    try {
      saveChoices(choices);
      onRunner(
        await startRun({
          mode: choices.mode,
          once: choices.once,
          every_seconds: Math.round(every * 60),
          max_cycles: choices.once ? 1 : cycles,
          budget_usd: budgetValue,
          live,
        }),
      );
      setOpen(false);
    } catch (e) {
      onError(`Run: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      onRunner(await stopRun());
    } catch (e) {
      onError(`Stop: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  let button;
  if (runActive(runner) && runner.once) {
    button = (
      <Button disabled>
        <Loader2 className="size-4 animate-spin" /> Running…
      </Button>
    );
  } else if (runActive(runner)) {
    button = (
      <Button onClick={stop} disabled={busy || !runner.repeating} title="Stops after the current Cycle">
        <Square className="size-4" /> {runner.repeating ? "Stop" : "Stopping…"}
      </Button>
    );
  } else {
    button = (
      <Button variant="primary" onClick={show} disabled={killSwitch} title={killSwitch ? "Turn off the kill switch first" : undefined}>
        <Play className="size-4" /> Run
      </Button>
    );
  }

  return (
    <>
      {button}
      <Modal open={open} onClose={() => setOpen(false)}>
        <h3 className="text-base font-semibold">Start the agent</h3>
        <p className="mt-1.5 text-sm text-ink-2">
          Each Cycle scans Gemini, buys Nansen data only when it's worth it, and makes shadow trades. Every guardrail and your approval
          threshold apply.
        </p>

        <div className="mt-5 space-y-4 text-sm">
          <div className="flex items-center justify-between gap-4">
            <span className="font-medium">Decided by</span>
            <Choice value={choices.mode} options={[["rule", "Rules"], ["llm", "LLM (Grok)"]]} onChange={(mode) => set({ mode })} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="font-medium">Cycles</span>
            <Choice
              value={choices.once ? "once" : "repeat"}
              options={[["once", "Once"], ["repeat", "Repeat"]]}
              onChange={(v) => set({ once: v === "once" })}
            />
          </div>
          {!choices.once && (
            <div className="flex flex-wrap items-center gap-2 text-ink-2">
              Every
              <input
                type="number"
                inputMode="decimal"
                aria-label="Minutes between Cycles"
                min={minMin}
                max={maxMin}
                step={1}
                value={choices.everyMinutes}
                onChange={(e) => set({ everyMinutes: e.target.value })}
                className="tabular w-16 rounded-lg border border-line bg-surface px-2 py-1.5"
              />
              min, stop after
              <input
                type="number"
                inputMode="numeric"
                aria-label="Number of Cycles"
                min={1}
                max={1000}
                step={1}
                value={choices.maxCycles}
                onChange={(e) => set({ maxCycles: e.target.value })}
                className="tabular w-20 rounded-lg border border-line bg-surface px-2 py-1.5"
              />
              Cycles
            </div>
          )}
          <div className="flex items-center justify-between gap-4">
            <label className="font-medium" htmlFor="run-budget">
              Budget for this Run
            </label>
            <div className="flex items-center gap-2">
              <span className="text-ink-2">$</span>
              <input
                id="run-budget"
                type="number"
                inputMode="decimal"
                min={0}
                max={cap ?? undefined}
                step={0.01}
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                className="tabular w-24 rounded-lg border border-line bg-surface px-2 py-1.5"
              />
              <span className="text-ink-3">max {usd(cap)}</span>
            </div>
          </div>
        </div>

        <div className="mt-5 rounded-xl bg-subtle px-4 py-3 text-sm">
          <div className="flex justify-between py-1">
            <span className="text-ink-2">Data</span>
            {live ? <Badge tone="loss">Live: real USDC</Badge> : <Badge tone="caution">Stub: no money moves</Badge>}
          </div>
          <div className="flex justify-between py-1">
            <span className="text-ink-2">Asks you at or above</span>
            <span className="tabular font-medium">{usd(threshold)}</span>
          </div>
          <div className="flex justify-between py-1">
            <span className="text-ink-2">Left today</span>
            <span className="tabular font-medium">{usd(status?.remaining_today_usd)}</span>
          </div>
        </div>

        {live && (
          <label className="mt-4 flex items-start gap-2 rounded-xl border border-loss/30 bg-loss-soft px-4 py-3 text-sm text-loss">
            <input type="checkbox" className="mt-0.5" checked={confirmLive} onChange={(e) => setConfirmLive(e.target.checked)} />
            <span>
              NANSEN_STUB is off, so this Run pays real USDC on Base for Nansen data. I understand.
            </span>
          </label>
        )}
        {problems.length > 0 && <p className="mt-3 text-sm text-loss">{problems[0]}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={start} disabled={busy || problems.length > 0 || (live && !confirmLive) || killSwitch}>
            <Play className="size-4" /> Start
          </Button>
        </div>
      </Modal>
    </>
  );
}

function countdown(iso: string, now: number): string {
  const s = Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** One line under the header: what the current Run is doing, or how the last one ended. */
export function RunStatusBar({ runner }: { runner: RunnerStatus | undefined }) {
  const [now, setNow] = useState(Date.now());
  const active = runActive(runner);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);

  if (!runner || (!active && !runner.stopped_because && !runner.last)) return null;
  const mode = runner.mode === "llm" ? "LLM" : "Rules";
  const spend = runner.run_budget_usd !== null ? `${usd(runner.run_spent_usd)} of ${usd(runner.run_budget_usd)} spent` : null;

  let parts: string[];
  if (active) {
    const n = runner.cycles_done + (runner.cycle_running ? 1 : 0);
    const cycle = runner.max_cycles ? `Cycle ${n} of ${runner.max_cycles}` : `Cycle ${n}`;
    const next = runner.cycle_running ? "Cycle in progress" : runner.next_run_at ? `next in ${countdown(runner.next_run_at, now)}` : null;
    parts = [mode, cycle, next, spend].filter((p): p is string => !!p);
  } else {
    parts = [
      `Stopped: ${runner.stopped_because ?? "idle"}`,
      runner.last ? `last Cycle ended ${time(runner.last.finished_at)}` : null,
    ].filter((p): p is string => !!p);
  }
  const failed = runner.last && !runner.last.ok ? runner.last.error : null;

  return (
    <div className="border-b border-line bg-subtle/60">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm sm:px-6" aria-live="polite">
        {active ? <Badge tone="accent" dot>Running</Badge> : <Badge>Last Run</Badge>}
        <span className="tabular text-ink-2">{parts.join(" · ")}</span>
        {failed && (
          <span className="inline-flex items-center gap-1 text-loss">
            <TriangleAlert className="size-3.5" /> Last Cycle failed: {failed}
          </span>
        )}
      </div>
    </div>
  );
}
