import { useEffect, useState } from "react";

const WATCHED = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE", "MATIC", "LTC", "LINK", "DOT"];

export default function PriceTickerAll({ apiUrl, lastEvent }) {
  const [prices, setPrices] = useState({});
  const [prev, setPrev] = useState({});

  const load = () =>
    fetch(`${apiUrl}/api/prices`)
      .then((r) => r.json())
      .then((d) => {
        setPrev((p) => ({ ...p, ...prices }));
        setPrices(d?.prices || {});
      })
      .catch(() => {});

  useEffect(() => { load(); const iv = setInterval(load, 30_000); return () => clearInterval(iv); }, []);
  useEffect(() => { if (lastEvent?.event === "bot_tick") load(); }, [lastEvent]);

  const coins = WATCHED.filter((c) => prices[c]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Live Prices (AUD)
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {coins.map((coin) => {
          const data = prices[coin] || {};
          const last = parseFloat(data.last || 0);
          const prevLast = parseFloat(prev[coin]?.last || last);
          const up = last > prevLast;
          const down = last < prevLast;
          return (
            <div
              key={coin}
              className={`rounded-lg p-3 border transition-colors duration-500 ${
                up
                  ? "border-emerald-700 bg-emerald-900/20"
                  : down
                  ? "border-red-700 bg-red-900/20"
                  : "border-gray-800 bg-gray-800/30"
              }`}
            >
              <div className="text-xs font-bold text-gray-400">{coin}</div>
              <div className={`text-lg font-bold ${up ? "text-emerald-400" : down ? "text-red-400" : "text-gray-100"}`}>
                ${last.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="flex gap-2 text-xs text-gray-600 mt-1">
                <span>B: ${parseFloat(data.bid || 0).toLocaleString()}</span>
                <span>A: ${parseFloat(data.ask || 0).toLocaleString()}</span>
              </div>
            </div>
          );
        })}
        {coins.length === 0 && <p className="text-gray-600 text-sm col-span-5">Loading prices…</p>}
      </div>
    </div>
  );
}
