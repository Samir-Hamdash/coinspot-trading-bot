import { useEffect, useState } from "react";

export default function Dashboard({ portfolio, openTrades, apiUrl }) {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch(`${apiUrl}/memory/stats`).then((r) => r.json()).then(setStats).catch(() => {});
  }, []);

  // Refresh stats after each trade closes
  useEffect(() => {
    if (portfolio) {
      fetch(`${apiUrl}/memory/stats`).then((r) => r.json()).then(setStats).catch(() => {});
    }
  }, [portfolio]);

  const cash = portfolio?.cash_aud ?? null;
  const totalValue = portfolio?.total_value_aud ?? null;
  const openCount = openTrades?.length ?? 0;
  const winRate = stats?.win_rate_pct;
  const totalTrades = stats?.total_trades ?? 0;

  const cards = [
    {
      label: "Cash Balance",
      value: cash != null ? `$${Number(cash).toFixed(2)}` : "—",
      sub: totalValue != null ? `Portfolio $${Number(totalValue).toFixed(2)}` : null,
      color: "text-emerald-400",
    },
    {
      label: "Open Positions",
      value: openCount,
      sub: `${openCount}/5 slots used`,
      color: "text-blue-400",
    },
    {
      label: "Win Rate",
      value: winRate != null ? `${winRate}%` : "—",
      sub: totalTrades ? `${totalTrades} closed trades` : "No trades yet",
      color: winRate >= 50 ? "text-emerald-400" : winRate != null ? "text-red-400" : "text-gray-400",
    },
    {
      label: "Best Coin",
      value: stats?.best_coins?.[0]?.coin ?? "—",
      sub: stats?.best_coins?.[0] ? `avg ${stats.best_coins[0].avg_pnl_pct > 0 ? "+" : ""}${stats.best_coins[0].avg_pnl_pct}%` : null,
      color: "text-yellow-400",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{c.label}</div>
          <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
          {c.sub && <div className="text-xs text-gray-600 mt-1">{c.sub}</div>}
        </div>
      ))}
    </div>
  );
}
