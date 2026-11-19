import { ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { settleNow, type Decision, type Decisions as DecisionsData, type SettleStatus, type Trade } from "../api";
import { Badge, Button, Card, cx, Empty, Table, Td, Th } from "../components/ui";
import { DASH, dateTime, num, pct, signedUsd, time, tierName, usd } from "../lib/format";

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

// mins_left is measured from the row's time, like every other number in the row, so show
// the expiry it implies (d.at + mins_left) rather than a countdown that would look live.
// Expiries fall on the minute; rounding absorbs the snapshot's sub-second drift.
function expiryOf(at: string, minsLeft: number): Date {
  return new Date(Math.round((new Date(at).getTime() + minsLeft * 60_000) / 60_000) * 60_000);
}

function Expiry({ at, minsLeft, now }: { at: string; minsLeft: number; now: number }) {
  const expiry = expiryOf(at, minsLeft);
  const sameDay = expiry.toDateString() === new Date(now).toDateString();
  const label = sameDay
    ? expiry.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : dateTime(expiry.toISOString());
  return (
    <span className="inline-flex items-center gap-2" title={`${num(minsLeft)} min left when this row was logged`}>
      {expiry.getTime() <= now && <Badge tone="neutral">Expired</Badge>}
      {label}
    </span>
  );
}

function Contracts({ d }: { d: Decision }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000); // only flips the Expired marks
    return () => clearInterval(timer);
  }, []);

  if (!d.quotes.length) return <p className="py-3 text-sm text-ink-3">No Contracts quoted.</p>;
  const traded = new Set(d.trades.map((t) => `${t.event}|${t.strike}`));
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-ink-3">
          {["Event", "Strike", "Expires", "Market (bid–ask)", "Baseline", "Informed", "Best edge", "Call"].map((h, i) => (
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
              <td className="tabular px-3 py-1.5 text-right">
                <Expiry at={d.at} minsLeft={q.mins_left} now={now} />
              </td>
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

/** When Events last settled (the server does it every few minutes), plus a Settle now button. */
function SettleLine({
  settle,
  unsettled,
  onSettled,
  onError,
}: {
  settle?: SettleStatus;
  unsettled?: number;
  onSettled: (s: SettleStatus) => void;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const running = busy || !!settle?.running;
  const last = settle?.last;

  let text = "Not settled yet.";
  if (settle?.last_at) {
    text = `Last settled ${time(settle.last_at)}`;
    if (last) text += `: ${last.settled} new, ${last.not_yet} waiting on Gemini${last.errors ? `, ${last.errors} lookup errors` : ""}.`;
    else if (settle.last_error) text += ` (failed: ${settle.last_error}).`;
  }
  if (settle?.auto) text += ` Runs every ${Math.round(settle.every_seconds / 60)} min.`;
  if (unsettled !== undefined) text += ` ${unsettled} logged Events not settled yet.`;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3 text-xs text-ink-3">
      <span>{running ? "Settling…" : text}</span>
      <Button
        disabled={running}
        onClick={async () => {
          setBusy(true);
          try {
            onSettled(await settleNow());
          } catch (e) {
            onError(`Settle failed: ${(e as Error).message}`);
          } finally {
            setBusy(false);
          }
        }}
      >
        Settle now
      </Button>
    </div>
  );
}

function ViewToggle({ tradesOnly, onChange }: { tradesOnly: boolean; onChange: (v: boolean) => void }) {
  const options: [string, boolean][] = [["All", false], ["Trades only", true]];
  return (
    <div role="group" aria-label="Which Decisions to show" className="flex shrink-0 rounded-lg border border-line p-0.5 text-xs">
      {options.map(([label, value]) => (
        <button
          key={label}
          type="button"
          aria-pressed={tradesOnly === value}
          onClick={() => onChange(value)}
          className={cx(
            "cursor-pointer rounded-md px-2.5 py-1 font-medium transition-colors",
            tradesOnly === value ? "bg-ink text-canvas" : "text-ink-2 hover:bg-subtle",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function Decisions({
  data,
  tradesOnly,
  onTradesOnly,
  settle,
  unsettled,
  onSettled,
  onError,
}: {
  data?: DecisionsData;
  tradesOnly: boolean;
  onTradesOnly: (v: boolean) => void;
  settle?: SettleStatus;
  unsettled?: number; // from the score report: logged Events with no outcome yet
  onSettled: (s: SettleStatus) => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  // The server filters too; this covers a poll that was already in flight when the toggle changed.
  const rows = data ? (tradesOnly ? data.rows.filter((d) => d.trades.length) : data.rows) : [];
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
      action={<ViewToggle tradesOnly={tradesOnly} onChange={onTradesOnly} />}
      flush
    >
      <SettleLine settle={settle} unsettled={unsettled} onSettled={onSettled} onError={onError} />
      {!data ? (
        <div className="px-5 pb-5"><Empty>Loading…</Empty></div>
      ) : !rows.length ? (
        <div className="px-5 py-5">
          <Empty>
            {tradesOnly
              ? "No trades yet."
              : "No Decisions yet. Start the runner: uv run python -m pennywise.agent.runner --every 1m"}
          </Empty>
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
            {rows.map((d) => {
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
