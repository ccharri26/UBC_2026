import { Fragment } from "react";
import type { Score, ScoreGroup } from "../api";
import { Badge, Card, cx, Empty, Table, Td, Th } from "../components/ui";
import { DASH, pct, signedUsd, tierName, tone, usd } from "../lib/format";

const brier = (x: number | null) => (x === null ? DASH : x.toFixed(3));

function Line({ name, g, fake, strong }: { name: string; g: ScoreGroup; fake: boolean; strong?: boolean }) {
  const beatsMarket = g.brier_baseline !== null && g.brier_market !== null && g.brier_baseline < g.brier_market;
  const dataHelps =
    g.brier_informed !== null && g.brier_baseline_same_events !== null && g.brier_informed < g.brier_baseline_same_events;
  return (
    <tr className={cx(strong && "font-medium")}>
      <Td>
        {name}
        {fake && g.events_with_data > 0 && <span className="ml-2"><Badge tone="caution">fake data</Badge></span>}
      </Td>
      <Td num>{g.events}</Td>
      <Td num className={cx(beatsMarket && "text-gain")}>{brier(g.brier_baseline)}</Td>
      <Td num>{brier(g.brier_market)}</Td>
      <Td num>
        {g.events_with_data ? (
          <>
            <span className={cx(dataHelps && "text-gain")}>{brier(g.brier_informed)}</span>
            <span className="text-ink-3"> vs {brier(g.brier_baseline_same_events)} · {g.events_with_data}</span>
          </>
        ) : DASH}
      </Td>
      <Td num>{g.trades ? `${g.trades_won} / ${g.trades}` : DASH}</Td>
      <Td num className={tone(g.pnl_usd)}>{signedUsd(g.pnl_usd)}</Td>
      <Td num>{usd(g.data_cost_usd)}</Td>
      <Td num className={cx("font-semibold", tone(g.net_pnl_usd))}>{signedUsd(g.net_pnl_usd)}</Td>
      <Td num>{pct(g.return_on_stake, 1, true)}</Td>
    </tr>
  );
}

export function Profit({ score }: { score?: Score }) {
  const sections: [string, Record<string, ScoreGroup>, (k: string) => string][] = score
    ? [
        ["By asset", score.by_asset, (k) => k],
        ["By Tier", score.by_tier, tierName],
        ["By who decided", score.by_decided_by, (k) => (k === "llm" ? "LLM" : "Rule")],
      ]
    : [];

  return (
    <Card
      title="4 · Profit & accuracy"
      subtitle="Profit is settled shadow-trade P&L minus Nansen spend. Brier score: lower is better, 0.25 is a coin flip; the baseline only makes money if it beats the market."
      action={score && <Badge tone={score.include_stub ? "caution" : "neutral"}>{score.include_stub ? "Includes stub runs" : "Live runs only"}</Badge>}
      flush
    >
      {!score ? (
        <div className="px-5 pb-5"><Empty>Loading…</Empty></div>
      ) : (
        <>
          <Table>
            <thead>
              <tr>
                <Th>Group</Th>
                <Th num>Events</Th>
                <Th num>Brier baseline</Th>
                <Th num>Brier market</Th>
                <Th num>With data vs baseline</Th>
                <Th num>Trades won</Th>
                <Th num>Trade P&L</Th>
                <Th num>Data cost</Th>
                <Th num>Profit</Th>
                <Th num>Return</Th>
              </tr>
            </thead>
            <tbody>
              <Line name="Overall" g={score.overall} fake={score.include_stub} strong />
              {sections.map(([title, groups, label]) =>
                Object.keys(groups).length ? (
                  <Fragment key={title}>
                    <tr>
                      <td colSpan={10} className="border-b border-line px-5 pt-5 pb-2 text-xs font-medium tracking-wide text-ink-3 uppercase">
                        {title}
                      </td>
                    </tr>
                    {Object.entries(groups).map(([k, g]) => (
                      <Line key={k} name={label(k)} g={g} fake={score.include_stub} />
                    ))}
                  </Fragment>
                ) : null,
              )}
            </tbody>
          </Table>
          {score.include_stub && (
            <p className="px-5 py-4 text-xs text-ink-3">
              Stub runs use random Nansen readings, so rows marked fake data say nothing about whether the data helps.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
