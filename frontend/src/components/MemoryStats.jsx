import { useEffect, useState } from "react";

export default function MemoryStats({ apiUrl, lastEvent }) {
  const [memory, setMemory] = useState({});

  const load = () =>
    fetch(`${apiUrl}/api/memory`).then((r) => r.json()).then(setMemory).catch(() => {});

  useEffect(() => { load(); }, []);
  useEffect(() => { if (lastEvent?.event === "bot_tick") load(); }, [lastEvent]);

  const entries = Object.entries(memory);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Bot Memory ({entries.length} keys)
      </h2>
      {entries.length === 0 ? (
        <p className="text-gray-600 text-sm">No memory entries yet.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {entries.map(([key, entry]) => (
            <div key={key} className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
              <div className="text-xs font-semibold text-blue-400 mb-1 truncate">{key}</div>
              <div className="text-sm text-gray-300 break-words">
                {typeof entry.value === "object"
                  ? JSON.stringify(entry.value, null, 2)
                  : String(entry.value)}
              </div>
              <div className="text-xs text-gray-600 mt-1">
                {entry.updated_at ? new Date(entry.updated_at).toLocaleString() : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
