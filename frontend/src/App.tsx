import { useCallback, useEffect, useState } from "react";

import { getConfig, getRequests, getUsers } from "./api";
import { NewRequestForm } from "./components/NewRequestForm";
import { RequestDetail } from "./components/RequestDetail";
import { RequestTable } from "./components/RequestTable";
import "./App.css";
import type { Config, RefundRequest, Status, User } from "./types";

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [viewer, setViewer] = useState<User | null>(null);
  const [requests, setRequests] = useState<RefundRequest[]>([]);
  const [status, setStatus] = useState<Status | "">("pending");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getConfig(), getUsers()])
      .then(([loadedConfig, loadedUsers]) => {
        setConfig(loadedConfig);
        setUsers(loadedUsers);
        setViewer(loadedUsers.find((user) => user.role === "manager") ?? loadedUsers[0] ?? null);
      })
      .catch(() => setError("Could not reach the API. Is the backend running on port 8000?"));
  }, []);

  const refresh = useCallback(() => {
    if (!viewer) return;
    getRequests(viewer.id, { status, flagged: flaggedOnly })
      .then(setRequests)
      .catch(() => setError("Could not load requests."));
  }, [viewer, status, flaggedOnly]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  if (error) return <main className="shell error">{error}</main>;
  if (!config || !viewer) return <main className="shell">Loading…</main>;

  const pendingCount = requests.filter((request) => request.status === "pending").length;

  return (
    <main className={selectedId === null ? "shell" : "shell drawer-open"}>
      <header className="topbar">
        <h1>Refund review</h1>
        <label className="viewer">
          Viewing as
          <select
            value={viewer.id}
            onChange={(event) => {
              const next = users.find((user) => user.id === Number(event.target.value));
              setViewer(next ?? viewer);
              setSelectedId(null);
            }}
          >
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} ({user.role})
              </option>
            ))}
          </select>
        </label>
      </header>

      <section className="controls">
        <div className="filters">
          {(["pending", "approved", "rejected", ""] as const).map((value) => (
            <button
              key={value || "all"}
              className={status === value ? "chip active" : "chip"}
              onClick={() => setStatus(value)}
            >
              {value === "" ? "All" : value}
            </button>
          ))}
          <label className="chip checkbox">
            <input
              type="checkbox"
              checked={flaggedOnly}
              onChange={(event) => setFlaggedOnly(event.target.checked)}
            />
            Flagged only
          </label>
        </div>
        <div className="right-controls">
          <span className="muted small">
            {requests.length} visible · {pendingCount} pending
          </span>
          <button className="approve" onClick={() => setComposing(true)}>
            New request
          </button>
        </div>
      </section>

      <RequestTable
        requests={requests}
        config={config}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {selectedId !== null && (
        <RequestDetail
          key={`${viewer.id}-${selectedId}`}
          requestId={selectedId}
          viewer={viewer}
          config={config}
          onDecided={refresh}
          onClose={() => setSelectedId(null)}
        />
      )}

      {composing && (
        <NewRequestForm
          viewer={viewer}
          config={config}
          onClose={() => setComposing(false)}
          onCreated={(id) => {
            setComposing(false);
            setSelectedId(id);
            refresh();
          }}
        />
      )}
    </main>
  );
}
