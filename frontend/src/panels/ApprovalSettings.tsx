import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { getApprovalSettings, setApprovalThreshold, type ApprovalSettings as Settings, type Tier } from "../api";
import { Badge, Button, Modal } from "../components/ui";
import { usd } from "../lib/format";

const TIER_NAMES: Record<Tier, string> = { basic: "Basic", smart_money: "Smart Money" };

/** Header button + modal for the Approval Threshold. Lowering saves directly; raising needs a tick. */
export function ApprovalSettingsButton({ onError }: { onError: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings>();
  const [input, setInput] = useState("");
  const [confirmRaise, setConfirmRaise] = useState(false);
  const [busy, setBusy] = useState(false);

  async function show() {
    try {
      const s = await getApprovalSettings();
      setSettings(s);
      setInput(s.threshold_usd.toFixed(2));
      setConfirmRaise(false);
      setOpen(true);
    } catch (e) {
      onError(`Approval settings: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const value = Number(input);
  const valid = input.trim() !== "" && Number.isFinite(value) && value >= 0 && !!settings && value <= settings.ceiling_usd + 1e-9;
  const raising = !!settings && valid && value > settings.threshold_usd + 1e-9;

  async function save() {
    if (!valid) return;
    setBusy(true);
    try {
      setSettings(await setApprovalThreshold(value, raising));
      setOpen(false);
    } catch (e) {
      onError(`Approval settings: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button onClick={show}>
        <ShieldCheck className="size-4" /> Approval
      </Button>
      <Modal open={open} onClose={() => setOpen(false)}>
        {settings && (
          <>
            <h3 className="text-base font-semibold">Approval settings</h3>
            <p className="mt-1.5 text-sm text-ink-2">
              The agent buys data on its own below this price. At or above it, a purchase waits up to {settings.wait_seconds}s for
              your answer. With no answer, it's refused and the kill switch turns on.
            </p>

            <label className="mt-5 block text-sm font-medium" htmlFor="approval-threshold">
              Ask me for purchases at or above
            </label>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-ink-2">$</span>
              <input
                id="approval-threshold"
                type="number"
                inputMode="decimal"
                min={0}
                max={settings.ceiling_usd}
                step={0.01}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  setConfirmRaise(false);
                }}
                className="tabular w-32 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              />
              <span className="text-sm text-ink-3">max {usd(settings.ceiling_usd)} (set in .env)</span>
            </div>
            {!valid && <p className="mt-2 text-sm text-loss">Enter an amount from $0.00 to {usd(settings.ceiling_usd)}.</p>}

            <div className="mt-5 rounded-xl bg-subtle px-4 py-3 text-sm">
              {(Object.keys(settings.prices_usd) as Tier[]).map((tier) => {
                const price = settings.prices_usd[tier];
                const asks = valid && price >= value - 1e-9;
                return (
                  <div key={tier} className="flex items-center justify-between py-1">
                    <span className="text-ink-2">
                      {TIER_NAMES[tier] ?? tier} · {usd(price)}
                    </span>
                    {valid && (asks ? <Badge tone="caution">Asks you</Badge> : <Badge tone="gain">Automatic</Badge>)}
                  </div>
                );
              })}
            </div>

            {settings.ceiling_problem && <p className="mt-3 text-sm text-loss">{settings.ceiling_problem}.</p>}
            {raising && (
              <label className="mt-4 flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-0.5" checked={confirmRaise} onChange={(e) => setConfirmRaise(e.target.checked)} />
                <span>I understand more purchases will go through without asking me.</span>
              </label>
            )}

            <div className="mt-6 flex justify-end gap-2">
              <Button onClick={() => setOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={busy || !valid || (raising && !confirmRaise)}>
                Save
              </Button>
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
