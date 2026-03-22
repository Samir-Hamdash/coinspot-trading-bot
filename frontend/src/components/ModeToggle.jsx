export default function ModeToggle({ mode }) {
  const isPaper = mode === "paper";
  return (
    <div
      className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-semibold ${
        isPaper
          ? "border-yellow-600 text-yellow-400 bg-yellow-900/20"
          : "border-red-600 text-red-400 bg-red-900/20"
      }`}
      title={isPaper ? "Paper trading — no real money at risk" : "LIVE trading — real funds in use"}
    >
      <span className={`w-2 h-2 rounded-full ${isPaper ? "bg-yellow-400" : "bg-red-500 animate-pulse"}`} />
      {isPaper ? "PAPER MODE" : "LIVE MODE"}
    </div>
  );
}
