import { useEffect, useState } from "react";

import { ApiError } from "../../api";
import { blockedReason, humanize, when } from "../../format";
import {
  decideChange,
  getFlag,
  proposeChange,
  setState,
  withdrawChange,
} from "./api";
import { Toggle } from "./FlagTable";
import type { FlagDetail as FlagDetailType, FlagsConfig } from "./types";

interface Props {
  flagId: number;
  config: FlagsConfig;
  onChanged: () => void;
  onClose: () => void;
}

export function FlagDetail({ flagId, config, onChanged, onClose }: Props) {
  const [flag, setFlag] = useState<FlagDetailType | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getFlag(flagId)
      .then((loaded) => active && setFlag(loaded))
      .catch((err: ApiError) => active && setError(err.detail));
    return () => {
      active = false;
    };
  }, [flagId]);

  if (error && !flag) return <aside className="detail error">{error}</aside>;
  if (!flag) return <aside className="detail">Loading…</aside>;

  const dev = flag.states.find((state) => state.environment === "dev");
  const prod = flag.states.find((state) => state.environment === "prod");
  const pending = flag.pending.find(
    (request) => request.environment === "prod",
  );

  async function run(action: () => Promise<FlagDetailType>) {
    setBusy(true);
    setError(null);
    try {
      const updated = await action();
      setFlag(updated);
      setReason("");
      setNote("");
      onChanged();
    } catch (err) {
      const apiError = err as ApiError;
      setError(blockedReason(apiError.detail) ?? apiError.detail);
      getFlag(flagId)
        .then(setFlag)
        .catch(() => undefined);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="detail">
      <header>
        <div>
          <h2>{flag.name}</h2>
          <p className="muted mono small">{flag.key}</p>
        </div>
        <button className="link" onClick={onClose}>
          Close
        </button>
      </header>

      <p className="note">{flag.description}</p>

      <dl className="facts">
        <div>
          <dt>Dev</dt>
          <dd>
            {dev && <Toggle on={dev.enabled} />}
            {dev?.updated_by && (
              <span className="muted small"> · {dev.updated_by.name}</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Production</dt>
          <dd>
            {prod && <Toggle on={prod.enabled} />}
            {prod?.updated_by && (
              <span className="muted small"> · {prod.updated_by.name}</span>
            )}
          </dd>
        </div>
      </dl>

      {config.can_edit && dev && (
        <div className="decision">
          <label>
            Reason <span className="muted small">(optional in dev)</span>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
              placeholder="Why is this moving?"
            />
          </label>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                run(() =>
                  setState(flag.id, {
                    environment: "dev",
                    enabled: !dev.enabled,
                    reason,
                  }),
                )
              }
            >
              Turn dev {dev.enabled ? "off" : "on"}
            </button>
            {!pending && prod && (
              <button
                className="approve"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    proposeChange(flag.id, {
                      environment: "prod",
                      from_value: prod.enabled,
                      to_value: !prod.enabled,
                      reason,
                    }),
                  )
                }
              >
                Propose prod {prod.enabled ? "off" : "on"}
              </button>
            )}
          </div>
        </div>
      )}

      {pending && (
        <div className="decision">
          <h3>
            Proposed: production {pending.from_value ? "on" : "off"} →{" "}
            {pending.to_value ? "on" : "off"}
          </h3>
          <p className="muted small">
            {pending.requester.name} · {when(pending.requested_at)}
          </p>
          {pending.reason && <p className="comment">{pending.reason}</p>}
          {pending.stale && (
            <p className="callout">
              Production has moved since this was proposed, so it can no longer
              be applied — it has to be withdrawn and proposed again against the
              current value.
            </p>
          )}
          {!pending.can_decide && !pending.stale && (
            <p className="callout muted">
              {blockedReason(pending.decide_blocked_reason)}
            </p>
          )}
          {config.can_approve && (
            <>
              <label>
                Note
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={2}
                  placeholder="What did you check?"
                />
              </label>
              <div className="actions">
                <button
                  className="approve"
                  disabled={busy || !pending.can_decide}
                  onClick={() =>
                    run(() => decideChange(pending.id, { approve: true, note }))
                  }
                >
                  Approve and apply
                </button>
                <button
                  className="reject"
                  disabled={busy || note.trim() === ""}
                  onClick={() =>
                    run(() =>
                      decideChange(pending.id, { approve: false, note }),
                    )
                  }
                >
                  Reject
                </button>
              </div>
            </>
          )}
          {config.can_edit && (
            <div className="actions">
              <button
                className="link"
                disabled={busy}
                onClick={() => run(() => withdrawChange(pending.id))}
              >
                Withdraw
              </button>
            </div>
          )}
          {error && <p className="error">{error}</p>}
        </div>
      )}

      {error && !pending && <p className="error">{error}</p>}

      <h3>History</h3>
      <ol className="history">
        {flag.events.map((event) => (
          <li key={event.id}>
            <span className={`dot dot-${event.action}`} />
            <div>
              <strong>{humanize(event.action)}</strong> in {event.environment}{" "}
              by {event.actor.name}
              {event.to_value !== null && (
                <span className="muted small">
                  {" "}
                  · {event.from_value ? "on" : "off"} →{" "}
                  {event.to_value ? "on" : "off"}
                </span>
              )}
              <div className="muted small">{when(event.created_at)}</div>
              {event.comment && <p className="comment">{event.comment}</p>}
            </div>
          </li>
        ))}
      </ol>
    </aside>
  );
}
