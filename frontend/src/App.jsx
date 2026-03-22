import { useEffect, useRef, useState } from "react";
import AIReasoningPanel from "./components/AIReasoningPanel";
import Dashboard from "./components/Dashboard";
import MemoryStats from "./components/MemoryStats";
import ModeToggle from "./components/ModeToggle";
import OpenTrades from "./components/OpenTrades";
import PriceTickerAll from "./components/PriceTickerAll";
import TradeHistory from "./components/TradeHistory";

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const [mode, setMode] = useState("paper");
  const wsRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // auto-reconnect
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        try {
          setLastEvent(JSON.parse(e.data));
        } catch {}
      };
    };
    connect();
    return () => wsRef.current?.close();
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/health`)
      .then((r) => r.json())
      .then((d) => setMode(d.mode))
      .catch(() => {});
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-mono">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold text-emerald-400">CoinSpot AI Bot</span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full border ${
              connected
                ? "border-emerald-500 text-emerald-400"
                : "border-red-500 text-red-400"
            }`}
          >
            {connected ? "LIVE" : "DISCONNECTED"}
          </span>
        </div>
        <ModeToggle mode={mode} />
      </header>

      {/* Main grid */}
      <main className="p-6 grid grid-cols-12 gap-4">
        {/* Row 1 */}
        <div className="col-span-12">
          <Dashboard apiUrl={API_URL} lastEvent={lastEvent} />
        </div>

        {/* Row 2 */}
        <div className="col-span-12 lg:col-span-8">
          <PriceTickerAll apiUrl={API_URL} lastEvent={lastEvent} />
        </div>
        <div className="col-span-12 lg:col-span-4">
          <AIReasoningPanel apiUrl={API_URL} lastEvent={lastEvent} />
        </div>

        {/* Row 3 */}
        <div className="col-span-12 lg:col-span-6">
          <OpenTrades apiUrl={API_URL} lastEvent={lastEvent} />
        </div>
        <div className="col-span-12 lg:col-span-6">
          <TradeHistory apiUrl={API_URL} lastEvent={lastEvent} />
        </div>

        {/* Row 4 */}
        <div className="col-span-12">
          <MemoryStats apiUrl={API_URL} lastEvent={lastEvent} />
        </div>
      </main>
    </div>
  );
}
