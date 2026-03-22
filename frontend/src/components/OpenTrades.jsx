import { useEffect, useState } from "react";

const STOP_LOSS_PCT = 4.0;
const TAKE_PROFIT_PCT = 8.0;

function PnlCell({ pnl, pct }) {
  if (pnl == null) return <td className="text-right text-gray-600">—</td>;
  const pos = pnl >= 0;
  return (
    <td className={`text-right font-semibold tabular-nums ${pos ? "text-emerald-400" : "text-red-400"}`}>
      {pos ? "+" : ""}${Number(pnl).toFixed(2)}
      <span className="text-xs ml-1 opacity-70">({pos ? "+" : ""}{Number(pct).toFixed(2)}%)</span>
    </td>
  );
}

export default function OpenTrades({ openTrades, lastEvent, apiUrl }) {
  const [trades, setTrades] = useState([]);
  const [enriched, setEnriched] = useState([]);

  const load = () =>
    fetch(`${apiUrl}/trades/open`).then((r) => r.json()).then(setTrades).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (lastEvent?.event === "trade_executed" || lastEvent?.event === "position_closed") load();
  }, [lastEvent]);

  // Prefer live WS data; fall back to REST-fetched data
  const source = openTrades?.length ? openTrades : trades;

  // Enrich with stop/take prices
  useEffect(() => {
    setEnriched(source.map((t) => {
      const entry = Number(t.entry_price);
      const sl = entry * (1 - STOP_LOSS_PCT / 100);
      const tp = entry * (1 + TAKE_PROFIT_PCT / 100);
      return { ...t, sl_price: sl, tp_price: tp };
    }));
  }, [source]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 overflow-x-auto">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Open Positions ({enriched.length}/5)
      </h2>
      {enriched.length === 0 ? (
        <p className="text-gray-600 text-sm">No open positions.</p>
      ) : (
        <table className="w-full text-sm min-w-[560px]">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left pb-2">Coin</th>
              <th className="text-left pb-2">Dir</th>
              <th className="text-right pb-2">Entry</th>
              <th className="text-right pb-2">Qty</th>
              <th className="text-right pb-2">Value</th>
              <th className="text-right pb-2">P&amp;L</th>
              <th className="text-right pb-2">Stop Loss</th>
              <th className="text-right pb-2">Take Profit</th>
            </tr>
          </thead>
          <tbody>
            {enriched.map((t) => (
              <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="py-2 font-bold text-blue-400">{t.coin}</td>
                <td>
                  <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${
                    t.direction === "long"
                      ? "bg-emerald-900/50 text-emerald-400"
                      : "bg-red-900/50 text-red-400"
                  }`}>
                    {(t.direction || "long").toUpperCase()}
                  </span>
                </td>
                <td className="text-right text-gray-300 tabular-nums">
                  ${Number(t.entry_price).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="text-right text-gray-300 tabular-nums">
                  {Number(t.quantity).toFixed(6)}
                </td>
                <td className="text-right text-gray-300 tabular-nums">
                  ${Number(t.value_aud).toFixed(2)}
                </td>
                <PnlCell pnl={t.pnl_aud} pct={t.pnl_percent} />
                <td className="text-right text-red-400/70 text-xs tabular-nums">
                  ${t.sl_price.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="text-right text-emerald-400/70 text-xs tabular-nums">
                  ${t.tp_price.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
