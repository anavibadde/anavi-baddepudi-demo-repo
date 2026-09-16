import { humanize, money, waited, when } from "../../format";
import type { RefundRequest, RefundsConfig } from "./types";
import { RiskFlags } from "./RiskFlags";

interface Props {
  requests: RefundRequest[];
  config: RefundsConfig;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function RequestTable({ requests, config, selectedId, onSelect }: Props) {
  if (requests.length === 0) {
    return <p className="empty">No requests match this filter.</p>;
  }
  return (
    <table className="queue">
      <thead>
        <tr>
          <th>Status</th>
          <th>Customer</th>
          <th>Reason</th>
          <th className="right">Amount</th>
          <th>Risk</th>
          <th>Submitted by</th>
          <th>Submitted</th>
          <th>Waiting</th>
        </tr>
      </thead>
      <tbody>
        {requests.map((request) => (
          <tr
            key={request.id}
            className={request.id === selectedId ? "selected" : undefined}
            onClick={() => onSelect(request.id)}
          >
            <td>
              <span className={`status status-${request.status}`}>{request.status}</span>
              {request.unassigned && (
                <div className="badge unassigned" title="No active manager above the submitter">
                  Unassigned
                </div>
              )}
            </td>
            <td>
              <div>{request.customer_name}</div>
              <div className="muted small">{request.order_id}</div>
            </td>
            <td>{humanize(request.reason)}</td>
            <td className="right mono">{money(request.amount_cents, request.currency)}</td>
            <td>
              <RiskFlags flags={request.risk_flags} labels={config.flag_labels} />
            </td>
            <td>{request.submitter.name}</td>
            <td className="muted small">{when(request.created_at)}</td>
            <td className="small">
              {request.status === "pending" && (
                <span
                  className={request.aging ? `badge aging-${request.aging}` : "muted"}
                  title={request.aging ? config.aging_labels[request.aging] : undefined}
                >
                  {waited(request.age_hours)}
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
