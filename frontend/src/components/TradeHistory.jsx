import { useEffect, useState } from "react";

const EXIT_BADGE = {
  "STOP LOSS":   "bg-red-900/60 text-red-300 border border-red-700",
  "TAKE PROFIT": "bg-emerald-900/60 text-emerald-300 border border-emerald-700",
  "AI CLOSE":    "bg-blue-900/60 text-blue-300 border border-blue-700",
};

export default function TradeHistory({ lastEvent, apiUrl }) {
  const [trades, setTrades] = useState([]);

  const load = () =>
    fetch(`${apiUrl}/trades/history?limit=50`)
      .then((r) => r.json())
      .then(setTrades)
      .catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (lastEvent?.event === "trade_executed" || lastEvent?.event === "position_closed") load();
  }, [lastEvent]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 max-h-96 overflow-y-auto">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Trade History ({trades.length})
      </h2>
      {trades.length === 0 ? (
        <p className="text-gray-600 text-sm">No closed trades yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left pb-2">Time</th>
              <th className="text-left pb-2">Coin</th>
              <th className="text-left pb-2">Exit</th>
              <th className="text-right pb-2">Entry</th>
              <th className="text-right pb-2">Exit Price</th>
              <th className="text-right pb-2">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const pnl = t.pnl_aud;
              const pos = pnl >= 0;
              const badge = EXIT_BADGE[t.exit_label] || EXIT_BADGE["AI CLOSE"];
              return (
                <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td className="py-1.5 text-gray-500 text-xs tabular-nums">
                    {new Date(t.exit_time).toLocaleTimeString()}
                  </td>
                  <td className="font-bold text-blue-400">{t.coin}</td>
                  <td>
                    <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${badge}`}>
                      {t.exit_label || t.exit_reason}
                    </span>
                  </td>
                  <td className="text-right text-gray-500 text-xs tabular-nums">
                    ${Number(t.entry_price).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </td>
                  <td className="text-right text-gray-300 tabular-nums">
                    ${Number(t.exit_price).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </td>
                  <td className={`text-right font-semibold tabular-nums ${pos ? "text-emerald-400" : "text-red-400"}`}>
                    {pos ? "+" : ""}${Number(pnl).toFixed(2)}
                    <span className="text-xs ml-1 opacity-70">
                      ({pos ? "+" : ""}{Number(t.pnl_percent).toFixed(2)}%)
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
