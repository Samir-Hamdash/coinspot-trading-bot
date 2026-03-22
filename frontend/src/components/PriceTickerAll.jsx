import { useEffect, useRef, useState } from "react";

const WATCHED = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE", "MATIC", "LTC", "LINK", "DOT"];

export default function PriceTickerAll({ prices, apiUrl }) {
  const [display, setDisplay] = useState({});
  const prevRef = useRef({});
  const [flashing, setFlashing] = useState({});

  // Seed from REST on mount; live updates come from the prices prop
  useEffect(() => {
    fetch(`${apiUrl}/api/prices`)
      .then((r) => r.json())
      .then((d) => { if (d?.prices) setDisplay(d.prices); })
      .catch(() => {});
    const iv = setInterval(() => {
      fetch(`${apiUrl}/api/prices`)
        .then((r) => r.json())
        .then((d) => { if (d?.prices) setDisplay(d.prices); })
        .catch(() => {});
    }, 30_000);
    return () => clearInterval(iv);
  }, []);

  // Merge WS prices prop into display
  useEffect(() => {
    if (!prices || !Object.keys(prices).length) return;
    const prev = prevRef.current;
    const newFlash = {};
    for (const coin of Object.keys(prices)) {
      const curr = parseFloat(prices[coin]?.last || 0);
      const old = parseFloat(prev[coin]?.last || 0);
      if (old && curr !== old) newFlash[coin] = curr > old ? "up" : "down";
    }
    prevRef.current = { ...prev, ...prices };
    setDisplay((d) => ({ ...d, ...prices }));
    if (Object.keys(newFlash).length) {
      setFlashing(newFlash);
      setTimeout(() => setFlashing({}), 800);
    }
  }, [prices]);

  const coins = WATCHED.filter((c) => display[c]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Live Prices (AUD)
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {coins.map((coin) => {
          const data = display[coin] || {};
          const last = parseFloat(data.last || 0);
          const flash = flashing[coin];
          return (
            <div
              key={coin}
              className={`rounded-lg p-3 border transition-all duration-500 ${
                flash === "up"
                  ? "border-emerald-500 bg-emerald-900/30"
                  : flash === "down"
                  ? "border-red-500 bg-red-900/30"
                  : "border-gray-800 bg-gray-800/30"
              }`}
            >
              <div className="text-xs font-bold text-gray-400">{coin}</div>
              <div className={`text-lg font-bold transition-colors duration-500 ${
                flash === "up" ? "text-emerald-400" : flash === "down" ? "text-red-400" : "text-gray-100"
              }`}>
                ${last.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="flex gap-2 text-xs text-gray-600 mt-1">
                <span>B: ${parseFloat(data.bid || 0).toLocaleString()}</span>
                <span>A: ${parseFloat(data.ask || 0).toLocaleString()}</span>
              </div>
            </div>
          );
        })}
        {coins.length === 0 && (
          <p className="text-gray-600 text-sm col-span-5">Loading prices…</p>
        )}
      </div>
    </div>
  );
}
