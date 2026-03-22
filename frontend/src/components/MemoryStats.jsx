import { useEffect, useState } from "react";

function StatCard({ label, value, sub, color = "text-gray-100" }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value ?? "—"}</div>
      {sub && <div className="text-xs text-gray-600 mt-1">{sub}</div>}
    </div>
  );
}

function CoinRankCard({ label, coins, positive }) {
  if (!coins?.length) return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{label}</div>
      <p className="text-gray-600 text-xs">No data yet.</p>
    </div>
  );
  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{label}</div>
      <div className="flex flex-col gap-1">
        {coins.slice(0, 3).map((c) => (
          <div key={c.coin} className="flex items-center justify-between text-sm">
            <span className="font-bold text-gray-300">{c.coin}</span>
            <span className={`font-semibold tabular-nums ${positive ? "text-emerald-400" : "text-red-400"}`}>
              {c.avg_pnl_pct > 0 ? "+" : ""}{c.avg_pnl_pct}%
              <span className="text-gray-600 text-xs ml-1">({c.trades}t)</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function MemoryStats({ lastEvent, apiUrl }) {
  const [stats, setStats] = useState(null);

  const load = () =>
    fetch(`${apiUrl}/memory/stats`).then((r) => r.json()).then(setStats).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (lastEvent?.event === "bot_tick" || lastEvent?.event === "position_closed") load();
  }, [lastEvent]);

  const winRate = stats?.win_rate_pct;
  const histDays = stats?.data_history_days;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Bot Memory
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="Total Trades"
          value={stats?.total_trades ?? "—"}
          sub={stats ? `${stats.wins}W / ${stats.losses}L` : null}
          color="text-blue-400"
        />
        <StatCard
          label="Win Rate"
          value={winRate != null ? `${winRate}%` : "—"}
          sub={winRate != null ? (winRate >= 50 ? "Profitable" : "Needs work") : "No trades yet"}
          color={winRate == null ? "text-gray-400" : winRate >= 50 ? "text-emerald-400" : "text-red-400"}
        />
        <StatCard
          label="Data History"
          value={histDays != null ? `${histDays}d` : "—"}
          sub={stats?.price_history_coins?.length
            ? `${stats.price_history_coins.length} coins tracked`
            : "Collecting data…"}
          color="text-yellow-400"
        />
        <CoinRankCard label="Best Coins" coins={stats?.best_coins} positive={true} />
        <CoinRankCard label="Worst Coins" coins={stats?.worst_coins} positive={false} />
      </div>
    </div>
  );
}
