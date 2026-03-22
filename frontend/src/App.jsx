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
  const [mode, setMode] = useState("paper");
  const [realEnabled, setRealEnabled] = useState(false);
  const [portfolio, setPortfolio] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [prices, setPrices] = useState({});
  const [openTrades, setOpenTrades] = useState([]);
  const [lastEvent, setLastEvent] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          setLastEvent(msg);
          const d = msg.data || {};
          if (msg.event === "init" || msg.event === "bot_tick") {
            if (d.mode) setMode(d.mode);
            if (d.real_enabled !== undefined) setRealEnabled(d.real_enabled);
            if (d.prices) setPrices(d.prices);
            if (d.open_trades) setOpenTrades(d.open_trades);
            if (d.decisions) setDecisions(d.decisions);
            if (d.portfolio) setPortfolio(d.portfolio);
          }
        } catch {}
      };
    };
    connect();
    return () => wsRef.current?.close();
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-mono">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold text-emerald-400">CoinSpot AI Bot</span>
          <span className={`text-xs px-2 py-0.5 rounded-full border ${
            connected ? "border-emerald-500 text-emerald-400" : "border-red-500 text-red-400"
          }`}>
            {connected ? "LIVE" : "DISCONNECTED"}
          </span>
        </div>
        <ModeToggle mode={mode} realEnabled={realEnabled} apiUrl={API_URL} />
      </header>

      <main className="p-6 grid grid-cols-12 gap-4">
        <div className="col-span-12">
          <Dashboard portfolio={portfolio} openTrades={openTrades} apiUrl={API_URL} />
        </div>
        <div className="col-span-12 lg:col-span-8">
          <PriceTickerAll prices={prices} apiUrl={API_URL} />
        </div>
        <div className="col-span-12 lg:col-span-4">
          <AIReasoningPanel decisions={decisions} apiUrl={API_URL} />
        </div>
        <div className="col-span-12 lg:col-span-6">
          <OpenTrades openTrades={openTrades} lastEvent={lastEvent} apiUrl={API_URL} />
        </div>
        <div className="col-span-12 lg:col-span-6">
          <TradeHistory lastEvent={lastEvent} apiUrl={API_URL} />
        </div>
        <div className="col-span-12">
          <MemoryStats lastEvent={lastEvent} apiUrl={API_URL} />
        </div>
      </main>
    </div>
  );
}
