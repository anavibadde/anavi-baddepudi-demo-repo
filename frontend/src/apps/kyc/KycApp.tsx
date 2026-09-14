import { useCallback, useEffect, useState } from "react";

import { ApiError, setToken } from "../../api";
import { humanize } from "../../format";
import type { User } from "../../types";
import { getCases, getKycConfig } from "./api";
import { CaseDetail } from "./CaseDetail";
import { CaseTable } from "./CaseTable";
import type { CaseStatus, KycCase, KycConfig } from "./types";

export function KycApp({
  viewer,
  onSignedOut,
  onDrawerChange,
}: {
  viewer: User;
  onSignedOut: () => void;
  onDrawerChange: (open: boolean) => void;
}) {
  const [config, setConfig] = useState<KycConfig | null>(null);
  const [cases, setCases] = useState<KycCase[]>([]);
  const [status, setStatus] = useState<CaseStatus | "">("");
  const [mine, setMine] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getKycConfig()
      .then(setConfig)
      .catch(() => setError("Could not load the KYC tool."));
  }, []);

  useEffect(
    () => onDrawerChange(selectedId !== null),
    [selectedId, onDrawerChange],
  );

  const refresh = useCallback(() => {
    getCases({ status: status || undefined, mine })
      .then(setCases)
      .catch((err: ApiError) => {
        if (err.status === 401) {
          setToken(null);
          onSignedOut();
          return;
        }
        setError("Could not load the queue.");
      });
  }, [status, mine, onSignedOut]);

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

  const awaiting = cases.filter((item) => item.status === "recommended").length;

  return (
    <>
      <section className="controls">
        <div className="filters">
          <label>
            Status
            <select
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as CaseStatus | "")
              }
            >
              <option value="">All</option>
              {config.statuses.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="chip checkbox">
            <input
              type="checkbox"
              checked={mine}
              onChange={(event) => setMine(event.target.checked)}
            />
            Only cases I hold
          </label>
        </div>
        <div className="right-controls">
          <span className="muted small">
            {cases.length} cases
            {awaiting > 0 && (
              <span className="overdue-count">
                {" "}
                · {awaiting} awaiting sign-off
              </span>
            )}
          </span>
        </div>
      </section>

      <p className="muted small">
        One shared pool: claim a case to work it, and a second reviewer signs
        off on what you recommend. Claims lapse after {config.claim_hours} hours
        so nothing stays parked.
      </p>

      <CaseTable
        cases={cases}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {selectedId !== null && (
        <CaseDetail
          key={`${viewer.id}-${selectedId}`}
          caseId={selectedId}
          viewerId={viewer.id}
          config={config}
          onChanged={refresh}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  );
}
