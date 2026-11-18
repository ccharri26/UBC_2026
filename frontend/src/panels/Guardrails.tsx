import { Lock } from "lucide-react";
import type { Status } from "../api";
import { Badge, Card, Empty, Row } from "../components/ui";
import { usd } from "../lib/format";

const onOff = (on: boolean) => (on ? <Badge tone="loss">On</Badge> : <Badge tone="gain">Off</Badge>);

/** Limits enforced in code before any payment is signed. Read-only: the kill switch is in the header. */
export function Guardrails({ status }: { status?: Status }) {
  return (
    <Card title="Guardrails" subtitle="Plain code that runs before every payment is signed. The agent can't change any of it.">
      {!status ? (
        <Empty>Loading…</Empty>
      ) : (
        <div className="grid gap-x-10 md:grid-cols-2">
          <div className="divide-y divide-line">
            <Row label="Max per call">{usd(status.max_per_call_usd)}</Row>
            <Row label="Per-run budget">{usd(status.per_run_budget_usd)}</Row>
            <Row label="Per asset and Tier, per day">{usd(status.per_market_budget_usd)}</Row>
            <Row label="Daily budget">{usd(status.daily_budget_usd)}</Row>
          </div>
          <div className="divide-y divide-line">
            <Row label="Kill switch (dashboard)">{onOff(status.dashboard_stopped)}</Row>
            <Row label={<span className="inline-flex items-center gap-1.5"><Lock className="size-3.5" /> Kill switch (.env lock)</span>}>
              {onOff(status.env_lock)}
            </Row>
            <Row label="Paused after repeated failures">{onOff(status.paused_after_failures)}</Row>
            <Row label="Payee">Nansen only, USDC on Base, price pinned</Row>
          </div>
          {(status.config_error || status.ledger_error || status.env_lock) && (
            <div className="mt-4 space-y-2 md:col-span-2">
              {status.config_error && <p className="rounded-lg bg-loss-soft px-3 py-2 text-sm text-loss">Config: {status.config_error}</p>}
              {status.ledger_error && (
                <p className="rounded-lg bg-loss-soft px-3 py-2 text-sm text-loss">Ledger: {status.ledger_error} (spending blocked)</p>
              )}
              {status.env_lock && (
                <p className="text-sm text-ink-3">Locked in .env: set KILL_SWITCH=false there by hand to allow spending.</p>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
