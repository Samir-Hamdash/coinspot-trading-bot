import { useEffect, useState } from "react";

export default function TradeHistory({ apiUrl, lastEvent }) {
  const [trades, setTrades] = useState([]);

  const load = () =>
    fetch(`${apiUrl}/api/trades?limit=50`).then((r) => r.json()).then(setTrades).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => { if (lastEvent?.event === "trade_executed") load(); }, [lastEvent]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 max-h-96 overflow-y-auto">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Trade History
      </h2>
      {trades.length === 0 ? (
        <p className="text-gray-600 text-sm">No trades yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left pb-2">Time</th>
              <th className="text-left pb-2">Coin</th>
              <th className="text-left pb-2">Side</th>
              <th className="text-right pb-2">Price</th>
              <th className="text-right pb-2">PnL</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="py-1.5 text-gray-500 text-xs">
                  {new Date(t.timestamp).toLocaleTimeString()}
                </td>
                <td className="font-bold text-blue-400">{t.coin}</td>
                <td>
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded font-semibold ${
                      t.side === "buy"
                        ? "bg-emerald-900/50 text-emerald-400"
                        : "bg-red-900/50 text-red-400"
                    }`}
                  >
                    {t.side.toUpperCase()}
                  </span>
                </td>
                <td className="text-right text-gray-300">${Number(t.price).toLocaleString()}</td>
                <td
                  className={`text-right font-semibold ${
                    t.pnl == null
                      ? "text-gray-600"
                      : t.pnl >= 0
                      ? "text-emerald-400"
                      : "text-red-400"
                  }`}
                >
                  {t.pnl == null ? "—" : `${t.pnl >= 0 ? "+" : ""}$${Number(t.pnl).toFixed(2)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
