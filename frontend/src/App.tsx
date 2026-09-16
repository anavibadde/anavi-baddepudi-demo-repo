import { useCallback, useEffect, useState } from "react";

import { ApiError, getConfig, getMe, getRequests, logout, setToken, storedToken } from "./api";
import { LoginForm } from "./components/LoginForm";
import { NewRequestForm } from "./components/NewRequestForm";
import { RequestDetail } from "./components/RequestDetail";
import { RequestTable } from "./components/RequestTable";
import "./App.css";
import type { Config, RefundRequest, Status, User } from "./types";

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [viewer, setViewer] = useState<User | null>(null);
  const [restoring, setRestoring] = useState(storedToken() !== null);
  const [requests, setRequests] = useState<RefundRequest[]>([]);
  const [status, setStatus] = useState<Status | "">("pending");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch(() => setError("Could not reach the API. Is the backend running on port 8000?"));
  }, []);

  useEffect(() => {
    // A token in localStorage may be expired or revoked; the server decides.
    if (storedToken() === null) return;
    getMe()
      .then(setViewer)
      .catch(() => setToken(null))
      .finally(() => setRestoring(false));
  }, []);

  const refresh = useCallback(() => {
    if (!viewer) return;
    getRequests({ status, flagged: flaggedOnly })
      .then(setRequests)
      .catch((err: ApiError) => {
        if (err.status === 401) {
          setToken(null);
          setViewer(null);
          return;
        }
        setError("Could not load requests.");
      });
  }, [viewer, status, flaggedOnly]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function signOut() {
    await logout();
    setViewer(null);
    setSelectedId(null);
    setRequests([]);
  }

  if (error) return <main className="shell error">{error}</main>;
  if (!config || restoring) return <main className="shell">Loading…</main>;
  if (!viewer) return <LoginForm onSignedIn={setViewer} />;

  const pendingCount = requests.filter((request) => request.status === "pending").length;

  return (
    <main className={selectedId === null ? "shell" : "shell drawer-open"}>
      <header className="topbar">
        <h1>Refund review</h1>
        <div className="session">
          <span className="muted">
            {viewer.name} <span className="small">({viewer.role})</span>
          </span>
          <button onClick={signOut}>Sign out</button>
        </div>
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
          config={config}
          onDecided={refresh}
          onClose={() => setSelectedId(null)}
        />
      )}

      {composing && (
        <NewRequestForm
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
