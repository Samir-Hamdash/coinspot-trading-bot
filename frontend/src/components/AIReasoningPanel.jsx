import { useEffect, useState } from "react";

const ACTION_BADGE = {
  buy:  "bg-emerald-900/60 text-emerald-300 border-emerald-700",
  sell: "bg-red-900/60 text-red-300 border-red-700",
  hold: "bg-gray-800 text-gray-400 border-gray-700",
};

const TREND_DOT = {
  bullish: "bg-emerald-400",
  bearish: "bg-red-400",
  neutral: "bg-gray-500",
};

function ConfidenceBar({ value }) {
  const pct = Math.min(100, Math.max(0, value));
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 45 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-800 rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-semibold w-8 text-right ${
        pct >= 70 ? "text-emerald-400" : pct >= 45 ? "text-yellow-400" : "text-red-400"
      }`}>{pct.toFixed(0)}%</span>
    </div>
  );
}

export default function AIReasoningPanel({ decisions, apiUrl }) {
  const [localDecisions, setLocalDecisions] = useState([]);

  // Seed from API on mount; live updates come from the decisions prop
  useEffect(() => {
    fetch(`${apiUrl}/api/decisions`).then((r) => r.json()).then((d) => {
      if (Array.isArray(d)) setLocalDecisions(d);
    }).catch(() => {});
  }, []);

  const active = (decisions?.length ? decisions : localDecisions)
    .filter((d) => d.action !== "hold")
    .slice(0, 5);

  const all = (decisions?.length ? decisions : localDecisions).slice(0, 5);
  const display = active.length ? active : all;

  if (!display.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full flex items-center justify-center">
        <p className="text-gray-600 text-sm">Waiting for first AI analysis…</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 h-full">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        AI Decisions ({display.length})
      </h2>
      <div className="flex flex-col gap-3 overflow-y-auto">
        {display.map((d, i) => (
          <div key={`${d.coin}-${i}`} className="border border-gray-800 rounded-lg p-3 bg-gray-800/30">
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${ACTION_BADGE[d.action] || ACTION_BADGE.hold}`}>
                {d.action.toUpperCase()}
              </span>
              <span className="font-bold text-gray-200">{d.coin}</span>
              <span className={`w-2 h-2 rounded-full ml-auto ${TREND_DOT[d.trend] || TREND_DOT.neutral}`}
                    title={d.trend} />
            </div>
            <ConfidenceBar value={d.confidence} />
            <p className="text-xs text-gray-400 mt-2 leading-relaxed line-clamp-3">{d.reasoning}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
