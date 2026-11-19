import { ShieldQuestion } from "lucide-react";
import { useEffect, useState } from "react";
import { answerApproval, getApprovalRequests, type ApprovalRequest } from "../api";
import { Badge, Button, Modal } from "../components/ui";
import { usePoll } from "../lib/usePoll";
import { usd } from "../lib/format";

const POLL_MS = 1_000; // the agent waits 90 s, so a request should appear within a second
const TITLE = document.title;

/** "ETH-smart_money" -> "ETH Smart Money" */
export function feedLabel(market: string): string {
  const [asset, tier] = market.split("-", 2);
  const tierName = { basic: "Basic", smart_money: "Smart Money" }[tier ?? ""] ?? tier;
  return tierName ? `${asset} ${tierName}` : market;
}

function secondsLeft(expiresAt: string, now: number): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000));
}

/**
 * Pops up whenever the agent is waiting on an Approval Request. It can't be dismissed:
 * the only ways out are Approve, Deny, or the timer running out (which trips the kill switch).
 */
export function ApprovalPrompt({ onError, onAnswered }: { onError: (msg: string) => void; onAnswered: () => void }) {
  const requests = usePoll(getApprovalRequests, POLL_MS);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const current: ApprovalRequest | undefined = requests.data?.find((r) => secondsLeft(r.expires_at, now) > 0);

  useEffect(() => {
    if (!current) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [current]);

  // A flashing tab title, so a pending request is noticed from another tab.
  useEffect(() => {
    if (!current) return;
    let on = false;
    const timer = setInterval(() => {
      on = !on;
      document.title = on ? "⚠ Approval needed" : TITLE;
    }, 1000);
    return () => {
      clearInterval(timer);
      document.title = TITLE;
    };
  }, [current]);

  async function answer(approve: boolean) {
    if (!current) return;
    setBusy(true);
    try {
      await answerApproval(current.id, approve);
    } catch (e) {
      onError(`Approval: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
      await requests.refresh();
      onAnswered();
    }
  }

  const left = current ? secondsLeft(current.expires_at, now) : 0;
  return (
    <Modal open={!!current} onClose={() => {}} locked>
      {current && (
        <>
          <div className="flex items-start gap-3">
            <div className="grid size-10 shrink-0 place-items-center rounded-full bg-caution-soft text-caution">
              <ShieldQuestion className="size-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold">Approve this purchase?</h3>
              <p className="mt-1.5 text-sm text-ink-2">
                The agent wants to buy Nansen data at or above your approval threshold. It's waiting for your answer.
              </p>
            </div>
          </div>
          <div className="mt-5 rounded-xl bg-subtle px-4 py-3 text-sm">
            <div className="flex justify-between py-1">
              <span className="text-ink-2">Data</span>
              <span className="font-medium">{feedLabel(current.market)}</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-ink-2">Price</span>
              <span className="tabular font-medium">
                {usd(current.amount_usd)} {current.stub ? <Badge tone="caution">Stub: no money moves</Badge> : <Badge tone="accent">Real USDC</Badge>}
              </span>
            </div>
          </div>
          <p className="mt-4 text-sm text-ink-3" aria-live="polite">
            <span className={left <= 15 ? "font-medium text-loss" : ""}>{left}s left.</span> With no answer, the purchase is refused and
            the kill switch stops all spending and trading.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <Button onClick={() => answer(false)} disabled={busy}>
              Deny
            </Button>
            <Button variant="primary" onClick={() => answer(true)} disabled={busy}>
              Approve {usd(current.amount_usd)}
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}
