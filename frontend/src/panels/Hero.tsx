import type { Score, Status, Wallet } from "../api";
import { Meter, Stat } from "../components/ui";
import { DASH, pct, short, signedUsd, tone, usd } from "../lib/format";

/** The four numbers a judge should see first. */
export function Hero({ status, wallet, score }: { status?: Status; wallet?: Wallet; score?: Score }) {
  const o = score?.overall;
  const budget = status?.daily_budget_usd;
  const used = status && budget ? status.spent_today_usd / budget : 0;
  const winRate = o && o.trades ? o.trades_won / o.trades : null;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Stat
        label="Profit"
        value={o ? signedUsd(o.net_pnl_usd) : DASH}
        valueClass={tone(o?.net_pnl_usd)}
        hint={o ? `${signedUsd(o.pnl_usd)} trades − ${usd(o.data_cost_usd)} data` : "Loading…"}
      />
      <Stat
        label="Spent on data today"
        value={status ? usd(status.spent_today_usd) : DASH}
        hint={status ? (budget ? `of ${usd(budget)} daily budget` : "budget not configured") : "Loading…"}
      >
        {status && budget ? <Meter value={used} /> : null}
      </Stat>
      <Stat
        label="Wallet (USDC on Base)"
        value={wallet ? usd(wallet.usdc, 2) : DASH}
        hint={
          status?.wallet_address ? (
            <a
              href={`https://basescan.org/address/${status.wallet_address}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              {short(status.wallet_address)} ↗
            </a>
          ) : (
            "wallet not set"
          )
        }
      />
      <Stat
        label="Trades won"
        value={o ? (o.trades ? `${o.trades_won} / ${o.trades}` : "0") : DASH}
        hint={
          o
            ? `${winRate === null ? "no settled trades" : `${pct(winRate, 0)} win rate`} · ${o.events} Events settled`
            : "Loading…"
        }
      />
    </div>
  );
}
