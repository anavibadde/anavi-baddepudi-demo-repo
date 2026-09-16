import { humanize, when } from "../../format";
import type { KycCase } from "./types";

interface Props {
  cases: KycCase[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge status-${status}`}>{humanize(status)}</span>;
}

function claimCell(item: KycCase) {
  if (!item.claimer) return <span className="muted">Unclaimed</span>;
  const claimIsLive = item.status === "new" || item.status === "claimed";
  if (item.claim_expired && claimIsLive) {
    return (
      <span className="badge unassigned">{item.claimer.name} · lapsed</span>
    );
  }
  return <span>{item.claimer.name}</span>;
}

export function CaseTable({ cases, selectedId, onSelect }: Props) {
  if (cases.length === 0) return <p className="empty">Nothing in the queue.</p>;
  return (
    <table className="queue">
      <thead>
        <tr>
          <th>Case</th>
          <th>Applicant</th>
          <th>Risk</th>
          <th>Status</th>
          <th>Claimed by</th>
          <th>Recommendation</th>
          <th>Opened</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((item) => (
          <tr
            key={item.id}
            className={item.id === selectedId ? "selected" : undefined}
            onClick={() => onSelect(item.id)}
          >
            <td className="mono small">{item.reference}</td>
            <td>
              <div>{item.applicant_name}</div>
              <div className="muted small">
                {item.entity_type} · {item.country}
              </div>
            </td>
            <td className="small">
              {item.risk_tier === "enhanced" ? (
                <span className="badge risk">Enhanced</span>
              ) : (
                <span className="muted">Standard</span>
              )}
            </td>
            <td className="small">
              <StatusBadge status={item.status} />
              {item.cycles > 1 && (
                <span className="muted small"> · cycle {item.cycles}</span>
              )}
            </td>
            <td className="small">{claimCell(item)}</td>
            <td className="small">
              {item.recommendation && item.recommender ? (
                <>
                  {humanize(item.recommendation)}
                  <div className="muted small">{item.recommender.name}</div>
                </>
              ) : (
                <span className="muted">—</span>
              )}
            </td>
            <td className="muted small">{when(item.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
