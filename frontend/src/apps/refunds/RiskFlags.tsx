import { humanize } from "../../format";

interface Props {
  flags: string[];
  labels: Record<string, string>;
}

export function RiskFlags({ flags, labels }: Props) {
  if (flags.length === 0) return <span className="muted">—</span>;
  return (
    <span className="flags">
      {flags.map((flag) => (
        <span key={flag} className={`flag flag-${flag}`}>
          {labels[flag] ?? humanize(flag)}
        </span>
      ))}
    </span>
  );
}
