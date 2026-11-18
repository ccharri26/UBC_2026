import type { Signal, Signals as SignalsData } from "../api";
import { Badge, Card, Empty } from "../components/ui";
import { compactUsd, DASH, num, time, tierName, tone, usd } from "../lib/format";

function Metric({ label, value, hint, toneOf }: { label: string; value: string; hint?: string; toneOf?: number | null }) {
  return (
    <div>
      <div className="text-xs text-ink-3">{label}</div>
      <div className={`tabular mt-0.5 text-lg font-semibold ${tone(toneOf)}`}>{value}</div>
      {hint && <div className="text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

function SignalCard({ s }: { s: Signal }) {
  const basic = s.tier === "basic";
  return (
    <div className="rounded-xl border border-line p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{s.asset}</span>
          <Badge tone={basic ? "neutral" : "accent"}>{tierName(s.tier)}</Badge>
        </div>
        <span className="text-xs text-ink-3">{s.horizons.join(" · ") || DASH}</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {basic ? (
          <>
            <Metric label="Smart traders" value={compactUsd(s.smart_trader_net_flow_usd)} toneOf={s.smart_trader_net_flow_usd}
              hint={s.smart_trader_wallet_count ? `${num(s.smart_trader_wallet_count)} wallets` : undefined} />
            <Metric label="Whales" value={compactUsd(s.whale_net_flow_usd)} toneOf={s.whale_net_flow_usd} />
            <Metric label="Exchanges" value={compactUsd(s.exchange_net_flow_usd)} hint="inflow leans bearish" />
          </>
        ) : (
          <>
            <Metric label="Smart money, 1h" value={compactUsd(s.sm_net_flow_1h_usd)} toneOf={s.sm_net_flow_1h_usd} />
            <Metric label="Traders" value={num(s.sm_trader_count)} />
            <div />
          </>
        )}
      </div>
      <div className="mt-4 flex justify-between border-t border-line pt-3 text-xs text-ink-3">
        <span>Bought {time(s.fetched_at)}</span>
        <span className="tabular">{s.cost_usd ? usd(s.cost_usd) : "free"}</span>
      </div>
    </div>
  );
}

export function Signals({ data }: { data?: SignalsData }) {
  return (
    <Card
      title="1 · On-chain signals"
      subtitle="Nansen net flows, cut down to numbers before the agent sees them. Positive means net buying."
      action={data && <Badge tone={data.mode === "live" ? "gain" : "caution"}>{data.mode === "live" ? "Paid data" : "Stub data"}</Badge>}
    >
      {!data ? (
        <Empty>Loading…</Empty>
      ) : !data.signals.length ? (
        <Empty>
          {data.mode === "live" ? "Nothing bought yet. Live mode only shows data the agent already paid for." : "No signals."}
        </Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.signals.map((s) => (
            <SignalCard key={`${s.asset}-${s.tier}`} s={s} />
          ))}
        </div>
      )}
      {data && data.errors.length > 0 && (
        <p className="mt-3 text-xs text-ink-3">{data.errors.length} asset/Horizon pairs unavailable.</p>
      )}
    </Card>
  );
}
