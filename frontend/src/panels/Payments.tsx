import { ArrowUpRight } from "lucide-react";
import type { Payment } from "../api";
import { Badge, Card, Empty, Table, Td, Th } from "../components/ui";
import { dateTime, DASH, short, tierName, usd } from "../lib/format";

const statusTone = { settled: "gain", failed: "loss", pending: "caution" } as const;

export function Payments({ rows }: { rows?: Payment[] }) {
  return (
    <Card
      title="3 · Payments"
      subtitle="Every x402 payment to Nansen, in USDC on Base. Each one passed every guardrail before it was signed."
      flush
    >
      {!rows ? (
        <div className="px-5 pb-5"><Empty>Loading…</Empty></div>
      ) : !rows.length ? (
        <div className="px-5 pb-5"><Empty>No payments yet.</Empty></div>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Time</Th>
              <Th>For</Th>
              <Th num>Amount</Th>
              <Th>Status</Th>
              <Th>Transaction</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={p.tx_hash ?? `${p.at}-${i}`}>
                <Td className="tabular">{dateTime(p.at)}</Td>
                <Td>
                  {p.market ? <span className="font-medium">{p.market.split("-")[0]} </span> : null}
                  <span className="text-ink-2">{tierName(p.tier)}</span>
                </Td>
                <Td num>{usd(p.amount_usd)}</Td>
                <Td>
                  <Badge tone={statusTone[p.status] ?? "caution"}>{p.status}</Badge>
                  {p.status === "failed" && p.detail && <span className="ml-2 text-ink-3">{p.detail}</span>}
                </Td>
                <Td>
                  {p.tx_url && p.tx_hash ? (
                    <a href={p.tx_url} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-mono text-xs text-accent hover:underline">
                      {short(p.tx_hash, 10, 6)} <ArrowUpRight className="size-3" />
                    </a>
                  ) : (
                    <span className="text-ink-3">{DASH}</span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
