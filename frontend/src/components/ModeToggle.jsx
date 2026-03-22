import { useState } from "react";

export default function ModeToggle({ mode, realEnabled, apiUrl }) {
  const isPaper = !realEnabled;
  const [showModal, setShowModal] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");

  const handleRealClick = () => {
    if (!isPaper) return;
    setError("");
    setShowModal(true);
  };

  const confirmRealMode = async () => {
    setSwitching(true);
    setError("");
    try {
      const r = await fetch(`${apiUrl}/mode/real`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      if (!r.ok) {
        const d = await r.json();
        setError(d.detail || "Failed to switch mode.");
      } else {
        setShowModal(false);
      }
    } catch {
      setError("Network error. Is the backend running?");
    } finally {
      setSwitching(false);
    }
  };

  return (
    <>
      <div
        onClick={handleRealClick}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-bold cursor-pointer select-none transition-all ${
          isPaper
            ? "border-emerald-500 text-emerald-300 bg-emerald-950 hover:bg-emerald-900/40"
            : "border-red-500 text-red-300 bg-red-950"
        }`}
        title={isPaper ? "Click to switch to real trading" : "Real trading active — using real funds"}
      >
        <span className={`w-2.5 h-2.5 rounded-full ${isPaper ? "bg-emerald-400" : "bg-red-500 animate-pulse"}`} />
        {isPaper ? "📄 PAPER TRADING" : "⚡ REAL TRADING ACTIVE"}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-red-700 rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <h2 className="text-xl font-bold text-red-400 mb-2">⚠️ Enable Real Trading?</h2>
            <p className="text-gray-300 text-sm mb-4 leading-relaxed">
              This will switch the bot to <strong className="text-red-300">REAL mode</strong> — trades
              will use actual AUD from your CoinSpot account.
            </p>
            <ul className="text-xs text-gray-400 mb-4 space-y-1 list-disc list-inside">
              <li>4% stop loss and 8% take profit are still enforced</li>
              <li>Max 20% of portfolio per trade</li>
              <li>Requires <code className="text-yellow-300">REAL_TRADING_CONFIRMED=true</code> in .env</li>
            </ul>
            {error && (
              <div className="bg-red-950 border border-red-700 rounded-lg px-3 py-2 text-sm text-red-300 mb-4">
                {error}
              </div>
            )}
            <div className="flex gap-3">
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm font-semibold transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmRealMode}
                disabled={switching}
                className="flex-1 px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-bold transition-colors"
              >
                {switching ? "Switching…" : "Yes, use real funds"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
