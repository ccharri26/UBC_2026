import { ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import type { Decision, Decisions as DecisionsData, Trade } from "../api";
import { Badge, Card, cx, Empty, Table, Td, Th } from "../components/ui";
import { DASH, num, pct, signedUsd, time, tierName, usd } from "../lib/format";

function DataChoice({ d }: { d: Decision }) {
  const i = d.info;
  const verdict =
    i.source === "paid" ? <Badge tone="accent">{d.stub ? "Bought (stub)" : `Bought ${usd(i.cost_usd)}`}</Badge>
    : i.source === "cached" ? <Badge tone="neutral">Reused</Badge>
    : i.buy ? <Badge tone="caution">Wanted</Badge>
    : <Badge tone="neutral">Skipped</Badge>;
  return (
    <div className="flex items-center gap-2">
      {verdict}
      <span className="text-ink-2">{i.reason}</span>
      {d.llm_override && <Badge tone="caution">LLM override</Badge>}
      {i.error && <Badge tone="loss">{i.error}</Badge>}
    </div>
  );
}

function TradeChip({ t }: { t: Trade }) {
  const result =
    t.result === "won" ? <Badge tone="gain">Won {signedUsd(t.pnl_usd)}</Badge>
    : t.result === "lost" ? <Badge tone="loss">Lost {signedUsd(t.pnl_usd)}</Badge>
    : <Badge tone="neutral">Open</Badge>;
  return (
    <div className="flex items-center gap-2">
      <span className="tabular">
        {t.side} ×{t.contracts} @ {usd(t.price)}
      </span>
      {result}
    </div>
  );
}

function Contracts({ d }: { d: Decision }) {
  if (!d.quotes.length) return <p className="py-3 text-sm text-ink-3">No Contracts quoted.</p>;
  const traded = new Set(d.trades.map((t) => `${t.event}|${t.strike}`));
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-ink-3">
          {["Event", "Strike", "Mins left", "Market (bid–ask)", "Baseline", "Informed", "Best edge", "Call"].map((h, i) => (
            <th key={h} className={cx("px-3 py-2 font-medium", i === 0 ? "text-left" : "text-right")}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {d.quotes.map((q) => {
          const edge = Math.max(q.yes_edge ?? -Infinity, q.no_edge ?? -Infinity);
          return (
            <tr key={`${q.event}|${q.strike}`} className={cx(traded.has(`${q.event}|${q.strike}`) && "bg-accent-soft/50")}>
              <td className="px-3 py-1.5 font-mono text-xs text-ink-2">{q.event}</td>
              <td className="tabular px-3 py-1.5 text-right">{num(q.strike, q.strike < 10 ? 4 : 0)}</td>
              <td className="tabular px-3 py-1.5 text-right">{num(q.mins_left)}</td>
              <td className="tabular px-3 py-1.5 text-right">{pct(q.bid, 0)}–{pct(q.ask, 0)}</td>
              <td className="tabular px-3 py-1.5 text-right">{pct(q.baseline)}</td>
              <td className="tabular px-3 py-1.5 text-right">{q.informed === null ? DASH : pct(q.informed)}</td>
              <td className={cx("tabular px-3 py-1.5 text-right", edge > 0 && "text-gain")}>
                {Number.isFinite(edge) ? pct(edge, 1, true) : DASH}
              </td>
              <td className="px-3 py-1.5 text-right">
                {q.call === "pass" ? <span className="text-ink-3">pass</span> : <Badge tone="accent">{q.call}</Badge>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Decisions({ data }: { data?: DecisionsData }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (k: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  return (
    <Card
      title="2 · Decisions"
      subtitle="Per asset and Tier, each pass: is the data worth its price, and is any Contract worth trading? Click a row for its Contracts."
      flush
    >
      {!data ? (
        <div className="px-5 pb-5"><Empty>Loading…</Empty></div>
      ) : !data.rows.length ? (
        <div className="px-5 pb-5">
          <Empty>No Decisions yet. Start the runner: uv run python -m pennywise.agent.runner --every 1m</Empty>
        </div>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th className="w-8" />
              <Th>Time</Th>
              <Th>Asset</Th>
              <Th>By</Th>
              <Th>Data</Th>
              <Th num>Value / price</Th>
              <Th num>Reading</Th>
              <Th>Trade</Th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((d) => {
              const key = `${d.at}|${d.asset}|${d.tier}`;
              const isOpen = open.has(key);
              return (
                <Fragment key={key}>
                  <tr onClick={() => toggle(key)} className="cursor-pointer transition-colors hover:bg-subtle/60">
                    <Td className="pr-0">
                      <ChevronRight className={cx("size-4 text-ink-3 transition-transform", isOpen && "rotate-90")} />
                    </Td>
                    <Td>
                      <span className="tabular">{time(d.at)}</span>
                      {d.stub && <span className="ml-2"><Badge tone="caution">stub</Badge></span>}
                    </Td>
                    <Td>
                      <span className="font-medium">{d.asset}</span>
                      <span className="ml-2 text-ink-3">{tierName(d.tier)}</span>
                    </Td>
                    <Td>{d.decided_by === "llm" ? <Badge tone="accent">LLM</Badge> : <span className="text-ink-2">Rule</span>}</Td>
                    <Td><DataChoice d={d} /></Td>
                    <Td num>
                      {usd(d.info.value_usd, 3)} <span className="text-ink-3">/ {usd(d.info.price_usd)}</span>
                    </Td>
                    <Td num>{d.info.reading === null ? DASH : d.info.reading.toFixed(2)}</Td>
                    <Td>
                      {d.trades.length ? (
                        <div className="space-y-1">{d.trades.map((t) => <TradeChip key={`${t.event}|${t.strike}`} t={t} />)}</div>
                      ) : (
                        <span className="text-ink-3">No trade</span>
                      )}
                    </Td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={8} className="border-b border-line bg-subtle/40 px-5 py-2">
                        <div className="overflow-x-auto"><Contracts d={d} /></div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
      )}
      {data && data.skipped > 0 && (
        <p className="px-5 py-3 text-xs text-ink-3">{data.skipped} log lines could not be read.</p>
      )}
    </Card>
  );
}
