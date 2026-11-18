import { Power, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { setKillSwitch, type Status } from "../api";
import { Badge, Button, Modal } from "../components/ui";
import { time, usd } from "../lib/format";

/** Sticky top bar: mode badges and the kill switch. Stopping is one click; resuming needs the modal. */
export function Header({
  status,
  onStatus,
  updatedAt,
  onError,
}: {
  status: Status | undefined;
  onStatus: (s: Status) => void;
  updatedAt: Date | undefined;
  onError: (msg: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggle(on: boolean) {
    setBusy(true);
    try {
      onStatus(await setKillSwitch(on, !on));
      setConfirming(false);
    } catch (e) {
      onError(`Kill switch: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <header className="sticky top-0 z-10 border-b border-line bg-canvas/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="grid size-8 place-items-center rounded-lg bg-ink text-sm font-bold text-canvas">¢</div>
          <div>
            <div className="text-[15px] leading-tight font-semibold tracking-tight">PennyWise</div>
            <div className="text-xs leading-tight text-ink-3">Pays for on-chain data only when it's worth it</div>
          </div>
        </div>

        {status && (
          <div className="flex flex-wrap items-center gap-1.5">
            {status.stub_mode ? <Badge tone="caution" dot>Stub data</Badge> : <Badge tone="gain" dot>Live data</Badge>}
            {status.kill_switch ? <Badge tone="loss" dot>Spending off</Badge> : <Badge tone="gain" dot>Spending on</Badge>}
            {status.paused_after_failures && <Badge tone="loss">Paused after failures</Badge>}
          </div>
        )}

        <div className="ml-auto flex items-center gap-3">
          {updatedAt && <span className="hidden text-xs text-ink-3 sm:inline">Updated {time(updatedAt.toISOString())}</span>}
          {status &&
            (status.dashboard_stopped ? (
              <Button onClick={() => setConfirming(true)} disabled={status.env_lock || busy}
                title={status.env_lock ? "Locked by KILL_SWITCH in .env" : undefined}>
                <Power className="size-4" /> Resume spending
              </Button>
            ) : (
              <Button variant="danger" onClick={() => toggle(true)} disabled={busy}>
                <Power className="size-4" /> Stop all spending
              </Button>
            ))}
        </div>
      </div>

      <Modal open={confirming} onClose={() => setConfirming(false)}>
        <div className="flex items-start gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-full bg-caution-soft text-caution">
            <ShieldAlert className="size-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold">Resume spending?</h3>
            <p className="mt-1.5 text-sm text-ink-2">
              The agent will be able to pay real USDC on Base for Nansen data again. Every guardrail still applies.
            </p>
          </div>
        </div>
        {status && (
          <div className="mt-5 rounded-xl bg-subtle px-4 py-3 text-sm">
            <div className="flex justify-between py-1">
              <span className="text-ink-2">Remaining today</span>
              <span className="tabular font-medium">{usd(status.remaining_today_usd)}</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-ink-2">Max per call</span>
              <span className="tabular font-medium">{usd(status.max_per_call_usd)}</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-ink-2">Data mode</span>
              <span className="font-medium">{status.stub_mode ? "Stub (no real spending)" : "Live"}</span>
            </div>
          </div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <Button onClick={() => setConfirming(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => toggle(false)} disabled={busy}>
            Resume spending
          </Button>
        </div>
      </Modal>
    </header>
  );
}
