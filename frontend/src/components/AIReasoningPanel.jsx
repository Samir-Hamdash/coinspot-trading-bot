import { useEffect, useState } from "react";

const CONFIDENCE_COLOR = (c) => {
  if (c >= 0.7) return "text-emerald-400";
  if (c >= 0.4) return "text-yellow-400";
  return "text-red-400";
};

const DECISION_BADGE = {
  buy: "bg-emerald-900/60 text-emerald-300 border-emerald-700",
  sell: "bg-red-900/60 text-red-300 border-red-700",
  hold: "bg-gray-800 text-gray-400 border-gray-600",
};

export default function AIReasoningPanel({ apiUrl, lastEvent }) {
  const [decision, setDecision] = useState(null);

  const load = () =>
    fetch(`${apiUrl}/api/decision`).then((r) => r.json()).then(setDecision).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => { if (lastEvent?.event === "bot_tick") setDecision(lastEvent.data?.decision); }, [lastEvent]);

  if (!decision) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full flex items-center justify-center">
        <p className="text-gray-600 text-sm">Waiting for first AI decision…</p>
      </div>
    );
  }

  const { decision: action, coin, confidence = 0, reasoning, risk_notes } = decision;
  const badgeClass = DECISION_BADGE[action] || DECISION_BADGE.hold;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        AI Reasoning
      </h2>

      <div className="flex items-center gap-3">
        <span className={`text-sm font-bold px-3 py-1 rounded-full border ${badgeClass}`}>
          {(action || "hold").toUpperCase()}
          {coin ? ` ${coin}` : ""}
        </span>
        <span className={`text-sm font-semibold ${CONFIDENCE_COLOR(confidence)}`}>
          {(confidence * 100).toFixed(0)}% confident
        </span>
      </div>

      {/* Confidence bar */}
      <div className="w-full bg-gray-800 rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full transition-all duration-700 ${
            confidence >= 0.7 ? "bg-emerald-500" : confidence >= 0.4 ? "bg-yellow-500" : "bg-red-500"
          }`}
          style={{ width: `${(confidence * 100).toFixed(0)}%` }}
        />
      </div>

      <div>
        <div className="text-xs text-gray-500 mb-1 uppercase tracking-wide">Reasoning</div>
        <p className="text-sm text-gray-300 leading-relaxed">{reasoning}</p>
      </div>

      {risk_notes && (
        <div>
          <div className="text-xs text-gray-500 mb-1 uppercase tracking-wide">Risk Notes</div>
          <p className="text-sm text-yellow-300/80 leading-relaxed">{risk_notes}</p>
        </div>
      )}
    </div>
  );
}
