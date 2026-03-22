import { useEffect, useState } from "react";

export default function Dashboard({ apiUrl, lastEvent }) {
  const [balance, setBalance] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);

  const fetch_data = () => {
    fetch(`${apiUrl}/api/positions`).then((r) => r.json()).then(setPositions).catch(() => {});
    fetch(`${apiUrl}/api/trades?limit=200`).then((r) => r.json()).then(setTrades).catch(() => {});
  };

  useEffect(() => { fetch_data(); }, []);

  useEffect(() => {
    if (lastEvent?.event === "bot_tick") {
      setBalance(lastEvent.data?.balance);
      fetch_data();
    }
  }, [lastEvent]);

  const totalPnl = trades
    .filter((t) => t.pnl != null)
    .reduce((acc, t) => acc + t.pnl, 0);

  const openCount = positions.length;

  const winRate = (() => {
    const closed = trades.filter((t) => t.pnl != null);
    if (!closed.length) return null;
    const wins = closed.filter((t) => t.pnl > 0).length;
    return ((wins / closed.length) * 100).toFixed(1);
  })();

  const cards = [
    {
      label: "Balance (AUD)",
      value: balance != null ? `$${balance.toFixed(2)}` : "—",
      color: "text-emerald-400",
    },
    {
      label: "Open Positions",
      value: openCount,
      color: "text-blue-400",
    },
    {
      label: "Total PnL",
      value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`,
      color: totalPnl >= 0 ? "text-emerald-400" : "text-red-400",
    },
    {
      label: "Win Rate",
      value: winRate != null ? `${winRate}%` : "—",
      color: "text-yellow-400",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{c.label}</div>
          <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
