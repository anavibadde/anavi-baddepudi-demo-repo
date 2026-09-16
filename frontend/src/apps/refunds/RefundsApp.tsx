import { useCallback, useEffect, useState } from "react";

import { ApiError, setToken } from "../../api";
import type { User } from "../../types";
import { getRefundsConfig, getRequests } from "./api";
import { NewRequestForm } from "./NewRequestForm";
import { RequestDetail } from "./RequestDetail";
import { RequestTable } from "./RequestTable";
import type { RefundRequest, RefundsConfig, Status } from "./types";

export function RefundsApp({
  viewer,
  onSignedOut,
  onDrawerChange,
}: {
  viewer: User;
  onSignedOut: () => void;
  onDrawerChange: (open: boolean) => void;
}) {
  const [config, setConfig] = useState<RefundsConfig | null>(null);
  const [requests, setRequests] = useState<RefundRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [status, setStatus] = useState<Status | "">("pending");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRefundsConfig()
      .then(setConfig)
      .catch(() => setError("Could not load the refunds tool."));
  }, []);

  useEffect(() => onDrawerChange(selectedId !== null), [selectedId, onDrawerChange]);

  // One request for however many pages are on screen, so refreshing after a
  // decision doesn't collapse the list back to page one.
  const refresh = useCallback(() => {
    if (!config) return;
    getRequests({ status, flagged: flaggedOnly, limit: config.page_size * pages })
      .then((page) => {
        setRequests(page.items);
        setTotal(page.total);
      })
      .catch((err: ApiError) => {
        if (err.status === 401) {
          setToken(null);
          onSignedOut();
          return;
        }
        setError("Could not load requests.");
      });
  }, [config, status, flaggedOnly, pages, onSignedOut]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!config) return <div>Loading…</div>;

  const overdueCount = requests.filter((request) => request.aging === "overdue").length;

  return (
    <>
      <section className="controls">
        <div className="filters">
          {(["pending", "approved", "rejected", ""] as const).map((value) => (
            <button
              key={value || "all"}
              className={status === value ? "chip active" : "chip"}
              onClick={() => {
                setStatus(value);
                setPages(1);
              }}
            >
              {value === "" ? "All" : value}
            </button>
          ))}
          <label className="chip checkbox">
            <input
              type="checkbox"
              checked={flaggedOnly}
              onChange={(event) => {
                setFlaggedOnly(event.target.checked);
                setPages(1);
              }}
            />
            Flagged only
          </label>
        </div>
        <div className="right-controls">
          <span className="muted small">
            Showing {requests.length} of {total}
            {overdueCount > 0 && <span className="overdue-count"> · {overdueCount} overdue</span>}
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

      {requests.length < total && (
        <div className="load-more">
          <button onClick={() => setPages((n) => n + 1)}>Load more</button>
        </div>
      )}

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
    </>
  );
}
