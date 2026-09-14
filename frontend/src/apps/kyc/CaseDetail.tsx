import { useEffect, useState } from "react";

import { ApiError } from "../../api";
import { blockedReason, humanize, when } from "../../format";
import {
  claimCase,
  getCase,
  recommendCase,
  releaseCase,
  requestInfo,
  signOffCase,
  supplyInfo,
} from "./api";
import { StatusBadge } from "./CaseTable";
import type { CaseDetail as CaseDetailType, KycConfig } from "./types";

interface Props {
  caseId: number;
  viewerId: number;
  config: KycConfig;
  onChanged: () => void;
  onClose: () => void;
}

export function CaseDetail({
  caseId,
  viewerId,
  config,
  onChanged,
  onClose,
}: Props) {
  const [item, setItem] = useState<CaseDetailType | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getCase(caseId)
      .then((loaded) => active && setItem(loaded))
      .catch((err: ApiError) => active && setError(err.detail));
    return () => {
      active = false;
    };
  }, [caseId]);

  if (error && !item) return <aside className="detail error">{error}</aside>;
  if (!item) return <aside className="detail">Loading…</aside>;

  async function run(action: () => Promise<CaseDetailType>) {
    setBusy(true);
    setError(null);
    try {
      setItem(await action());
      setNote("");
    } catch (err) {
      const apiError = err as ApiError;
      setError(blockedReason(apiError.detail) ?? apiError.detail);
      getCase(caseId)
        .then(setItem)
        .catch(() => undefined);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  // Once a case is recommended or closed the claim no longer decides
  // anything, so its timer is noise.
  const claimIsLive = item.status === "new" || item.status === "claimed";
  const holdsClaim =
    item.claimer?.id === viewerId && !item.claim_expired && !item.decided_at;
  const awaitingSignOff = item.status === "recommended";

  return (
    <aside className="detail">
      <header>
        <div>
          <h2>{item.applicant_name}</h2>
          <p className="muted mono small">{item.reference}</p>
        </div>
        <button className="link" onClick={onClose}>
          Close
        </button>
      </header>

      <p className="note">{item.summary}</p>

      <dl className="facts">
        <div>
          <dt>Status</dt>
          <dd>
            <StatusBadge status={item.status} />
          </dd>
        </div>
        <div>
          <dt>Entity</dt>
          <dd>
            {humanize(item.entity_type)} · {item.country}
          </dd>
        </div>
        <div>
          <dt>Risk tier</dt>
          <dd>{humanize(item.risk_tier)}</dd>
        </div>
        <div>
          <dt>Review cycle</dt>
          <dd>{item.cycles}</dd>
        </div>
        <div>
          <dt>Claim</dt>
          <dd>
            {item.claimer ? (
              <>
                {item.claimer.name}
                {claimIsLive && (
                  <span className="muted small">
                    {item.claim_expired
                      ? " · lapsed, free to take"
                      : ` · holds it for ${config.claim_hours}h`}
                  </span>
                )}
              </>
            ) : (
              <span className="muted">Unclaimed</span>
            )}
          </dd>
        </div>
        {item.recommender && (
          <div>
            <dt>Recommended</dt>
            <dd>
              {item.recommendation && humanize(item.recommendation)}
              <span className="muted small"> · {item.recommender.name}</span>
            </dd>
          </div>
        )}
        {item.decider && (
          <div>
            <dt>Signed off</dt>
            <dd>
              {item.decider.name}
              <span className="muted small">
                {" "}
                · {item.decided_at && when(item.decided_at)}
              </span>
            </dd>
          </div>
        )}
      </dl>

      {config.can_review && item.status === "needs_info" && (
        <div className="decision">
          <p className="muted small">
            Waiting on documents. Marking them received puts the case back in
            the pool on a new cycle.
          </p>
          <label>
            Note
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={2}
              placeholder="What arrived?"
            />
          </label>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() => run(() => supplyInfo(item.id, note))}
            >
              Documents received
            </button>
          </div>
        </div>
      )}

      {config.can_review && item.can_claim && (
        <div className="actions">
          <button disabled={busy} onClick={() => run(() => claimCase(item.id))}>
            {item.claimer ? "Take over lapsed claim" : "Claim this case"}
          </button>
        </div>
      )}

      {holdsClaim && !awaitingSignOff && (
        <div className="decision">
          <h3>Your recommendation</h3>
          <p className="muted small">
            A recommendation is not a decision — a different reviewer signs it
            off.
          </p>
          <label>
            Note
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              placeholder="What did you check?"
            />
          </label>
          <div className="actions">
            <button
              className="approve"
              disabled={busy || !item.can_recommend}
              onClick={() =>
                run(() =>
                  recommendCase(item.id, {
                    recommendation: "approved",
                    note,
                  }),
                )
              }
            >
              Recommend approve
            </button>
            <button
              className="reject"
              disabled={busy || !item.can_recommend}
              onClick={() =>
                run(() =>
                  recommendCase(item.id, {
                    recommendation: "rejected",
                    note,
                  }),
                )
              }
            >
              Recommend reject
            </button>
            <button
              className="link"
              disabled={busy}
              onClick={() => run(() => releaseCase(item.id))}
            >
              Release
            </button>
          </div>
        </div>
      )}

      {awaitingSignOff && (
        <div className="decision">
          <h3>
            Sign-off: {item.recommendation && humanize(item.recommendation)}
          </h3>
          <p className="muted small">
            {item.recommender?.name} recommended this
            {item.recommended_at ? ` · ${when(item.recommended_at)}` : ""}
          </p>
          {!item.can_sign_off && (
            <p className="callout muted">
              {blockedReason(item.blocked_reason) ??
                "Only a different authorised reviewer can sign this off."}
            </p>
          )}
          {config.can_sign_off && (
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
                  disabled={busy || !item.can_sign_off}
                  onClick={() =>
                    run(() => signOffCase(item.id, { approve: true, note }))
                  }
                >
                  Agree and close
                </button>
                <button
                  className="reject"
                  disabled={busy || !item.can_sign_off}
                  onClick={() =>
                    run(() => signOffCase(item.id, { approve: false, note }))
                  }
                >
                  Disagree, send back
                </button>
                <button
                  className="link"
                  disabled={busy || note.trim() === ""}
                  onClick={() => run(() => requestInfo(item.id, note))}
                >
                  Request more info
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <h3>History</h3>
      <ol className="history">
        {item.events.map((event) => (
          <li key={event.id}>
            <span className={`dot dot-${event.action}`} />
            <div>
              <strong>{humanize(event.action)}</strong>
              {event.actor ? ` by ${event.actor.name}` : ""}
              {item.cycles > 1 && (
                <span className="muted small"> · cycle {event.cycle}</span>
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
