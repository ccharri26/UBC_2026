import { useEffect, useState } from "react";
import { getDecisions, getPayments, getRunner, getScore, getSettle, getSignals, getStatus, getWallet, stopRun } from "./api";
import { usePoll } from "./lib/usePoll";
import { ApprovalPrompt } from "./panels/ApprovalPrompt";
import { Decisions } from "./panels/Decisions";
import { Guardrails } from "./panels/Guardrails";
import { Header } from "./panels/Header";
import { Hero } from "./panels/Hero";
import { Payments } from "./panels/Payments";
import { Profit } from "./panels/Profit";
import { RunStatusBar, runActive } from "./panels/RunControl";
import { Signals } from "./panels/Signals";

const RUNNER_MS = 2_000; // the Run status line has a countdown
const FAST_MS = 5_000; // status, payments, signals, decisions
const DECISION_ROWS = 24; // about three passes: enough to show the pattern without burying the rest
const SLOW_MS = 30_000; // wallet (an RPC call) and score (changes only when Events settle)

export default function App() {
  const status = usePoll(getStatus, FAST_MS);
  const runner = usePoll(getRunner, RUNNER_MS);
  const payments = usePoll(() => getPayments(), FAST_MS);
  const signals = usePoll(getSignals, FAST_MS);
  const [tradesOnly, setTradesOnly] = useState(false);
  const decisions = usePoll(() => getDecisions(DECISION_ROWS, tradesOnly), FAST_MS);
  const refreshDecisions = decisions.refresh;
  useEffect(() => {
    refreshDecisions(); // the filter changed: don't wait for the next poll
  }, [tradesOnly, refreshDecisions]);
  const wallet = usePoll(getWallet, SLOW_MS); // a failed RPC read just shows "—"
  const score = usePoll(getScore, SLOW_MS);
  const settle = usePoll(getSettle, SLOW_MS);

  const [actionError, setActionError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<Date>();
  useEffect(() => {
    if (status.data) setUpdatedAt(new Date());
  }, [status.data]);

  const pollError = [status, runner, payments, signals, decisions, score].find((p) => p.error)?.error;
  const error = actionError || (pollError ? `Can't reach the API: ${pollError.message}` : "");

  return (
    <div className="min-h-screen">
      <Header
        status={status.data}
        onStatus={(s) => {
          status.set(s);
          runner.refresh(); // the kill switch ends a Run
        }}
        runner={runner.data}
        onRunner={runner.set}
        updatedAt={updatedAt}
        onError={setActionError}
      />
      <RunStatusBar runner={runner.data} />
      <ApprovalPrompt
        onError={setActionError}
        onAnswered={() => {
          status.refresh();
          runner.refresh();
        }}
        onStopRun={runActive(runner.data) ? async () => runner.set(await stopRun()) : undefined}
      />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        {error && (
          <div role="alert" className="flex items-start justify-between gap-4 rounded-xl border border-loss/30 bg-loss-soft px-4 py-3 text-sm text-loss">
            <span>{error}</span>
            {actionError && (
              <button className="cursor-pointer font-medium hover:underline" onClick={() => setActionError("")}>Dismiss</button>
            )}
          </div>
        )}

        <Hero status={status.data} wallet={wallet.data} score={score.data} />
        <Signals data={signals.data} />
        <Decisions
          data={decisions.data}
          tradesOnly={tradesOnly}
          onTradesOnly={setTradesOnly}
          settle={settle.data}
          unsettled={score.data?.unsettled_or_unmatched}
          onSettled={(s) => {
            settle.set(s);
            score.refresh();
            decisions.refresh(); // trade results appear once their Event settles
          }}
          onError={setActionError}
        />
        <Payments rows={payments.data} />
        <Profit score={score.data} />
        <Guardrails status={status.data} />

        <footer className="pt-2 pb-6 text-center text-xs text-ink-3">
          PennyWise · trades are simulated (shadow mode) · data payments are real x402 on Base
        </footer>
      </main>
    </div>
  );
}
