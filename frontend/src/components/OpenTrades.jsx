import { useEffect, useState } from "react";

export default function OpenTrades({ apiUrl, lastEvent }) {
  const [positions, setPositions] = useState([]);

  const load = () =>
    fetch(`${apiUrl}/api/positions`).then((r) => r.json()).then(setPositions).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => { if (lastEvent?.event === "bot_tick" || lastEvent?.event === "trade_executed") load(); }, [lastEvent]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Open Positions ({positions.length})
      </h2>
      {positions.length === 0 ? (
        <p className="text-gray-600 text-sm">No open positions.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="text-left pb-2">Coin</th>
              <th className="text-right pb-2">Entry</th>
              <th className="text-right pb-2">Qty</th>
              <th className="text-right pb-2">Value (AUD)</th>
              <th className="text-left pb-2 pl-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="py-2 font-bold text-blue-400">{p.coin}</td>
                <td className="text-right text-gray-300">${Number(p.price).toLocaleString()}</td>
                <td className="text-right text-gray-300">{Number(p.quantity).toFixed(6)}</td>
                <td className="text-right text-gray-300">${Number(p.aud_value).toFixed(2)}</td>
                <td className="pl-3 text-gray-500 text-xs max-w-xs truncate">{p.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
