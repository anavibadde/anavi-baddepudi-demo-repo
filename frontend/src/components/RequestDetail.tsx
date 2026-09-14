import { useEffect, useState } from "react";

import { ApiError, decideRequest, getRequest } from "../api";
import { blockedReason, humanize, money, waited, when } from "../format";
import type { Config, RefundRequestDetail } from "../types";
import { RiskFlags } from "./RiskFlags";

interface Props {
  requestId: number;
  config: Config;
  onDecided: () => void;
  onClose: () => void;
}

export function RequestDetail({ requestId, config, onDecided, onClose }: Props) {
  const [request, setRequest] = useState<RefundRequestDetail | null>(null);
  const [comment, setComment] = useState("");
  const [confirmRisk, setConfirmRisk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getRequest(requestId)
      .then((loaded) => active && setRequest(loaded))
      .catch((err: ApiError) => active && setError(err.detail));
    return () => {
      active = false;
    };
  }, [requestId]);

  if (error && !request) return <aside className="detail error">{error}</aside>;
  if (!request) return <aside className="detail">Loading…</aside>;

  const pending = request.status === "pending";
  const flagged = request.risk_flags.length > 0;
  const approveDisabled = busy || (flagged && !confirmRisk);

  async function decide(action: "approved" | "rejected") {
    setBusy(true);
    setError(null);
    try {
      const updated = await decideRequest(requestId, {
        action,
        comment,
        confirm_risk: confirmRisk,
      });
      setRequest(updated);
      onDecided();
    } catch (err) {
      const apiError = err as ApiError;
      setError(
        apiError.status === 409
          ? "Someone else already decided this request."
          : blockedReason(apiError.detail) ?? apiError.detail,
      );
      if (apiError.status === 409) {
        getRequest(requestId).then(setRequest).catch(() => undefined);
        onDecided();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="detail">
      <header>
        <div>
          <h2>
            {money(request.amount_cents, request.currency)}{" "}
            <span className={`status status-${request.status}`}>{request.status}</span>
          </h2>
          <p className="muted">
            {request.customer_name} · {request.customer_id} · {request.order_id}
          </p>
        </div>
        <button className="link" onClick={onClose}>
          Close
        </button>
      </header>

      <dl className="facts">
        <div>
          <dt>Reason</dt>
          <dd>{humanize(request.reason)}</dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>
            <RiskFlags flags={request.risk_flags} labels={config.flag_labels} />
          </dd>
        </div>
        <div>
          <dt>Submitted by</dt>
          <dd>{request.submitter.name}</dd>
        </div>
        <div>
          <dt>Submitted</dt>
          <dd>{when(request.created_at)}</dd>
        </div>
        {pending && (
          <div>
            <dt>Waiting</dt>
            <dd className={request.aging ? `badge aging-${request.aging}` : undefined}>
              {waited(request.age_hours)}
              {request.aging ? ` · ${config.aging_labels[request.aging]}` : ""}
            </dd>
          </div>
        )}
      </dl>

      <p className="note">{request.note}</p>

      {request.unassigned && pending && (
        <p className="callout">
          Nobody active above {request.submitter.name} can review this — an admin has to pick it up.
        </p>
      )}

      {request.requires_admin && pending && (
        <p className="callout">
          High value plus another risk flag — only an admin can approve this.
        </p>
      )}

      {pending && !request.can_decide && (
        <p className="callout muted">{blockedReason(request.decide_blocked_reason)}</p>
      )}

      {pending && request.can_decide && (
        <div className="decision">
          <label>
            Comment <span className="muted small">(required to reject)</span>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
              placeholder="What did you check?"
            />
          </label>
          {flagged && (
            <label className="confirm">
              <input
                type="checkbox"
                checked={confirmRisk}
                onChange={(event) => setConfirmRisk(event.target.checked)}
              />
              I have reviewed the risk flags on this {money(request.amount_cents)} refund.
            </label>
          )}
          <div className="actions">
            <button className="approve" disabled={approveDisabled} onClick={() => decide("approved")}>
              Approve
            </button>
            <button
              className="reject"
              disabled={busy || comment.trim() === ""}
              onClick={() => decide("rejected")}
            >
              Reject
            </button>
          </div>
          {error && <p className="error">{error}</p>}
        </div>
      )}

      <h3>History</h3>
      <ol className="history">
        {request.events.map((event) => (
          <li key={event.id}>
            <span className={`dot dot-${event.action}`} />
            <div>
              <strong>{humanize(event.action)}</strong> by {event.actor.name}
              <div className="muted small">{when(event.created_at)}</div>
              {event.comment && <p className="comment">{event.comment}</p>}
            </div>
          </li>
        ))}
      </ol>
    </aside>
  );
}
