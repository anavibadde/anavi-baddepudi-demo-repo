import { when } from "../../format";
import type { Flag } from "./types";

interface Props {
  flags: Flag[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function Toggle({ on }: { on: boolean }) {
  return (
    <span className={on ? "toggle toggle-on" : "toggle toggle-off"}>
      {on ? "on" : "off"}
    </span>
  );
}

export function FlagTable({ flags, selectedId, onSelect }: Props) {
  if (flags.length === 0) return <p className="empty">No flags yet.</p>;
  return (
    <table className="queue">
      <thead>
        <tr>
          <th>Flag</th>
          <th>Dev</th>
          <th>Production</th>
          <th>Pending change</th>
          <th>Last changed</th>
        </tr>
      </thead>
      <tbody>
        {flags.map((flag) => {
          const dev = flag.states.find((state) => state.environment === "dev");
          const prod = flag.states.find(
            (state) => state.environment === "prod",
          );
          const pending = flag.pending[0];
          const latest = flag.states
            .map((state) => state.updated_at)
            .sort()
            .at(-1);
          return (
            <tr
              key={flag.id}
              className={flag.id === selectedId ? "selected" : undefined}
              onClick={() => onSelect(flag.id)}
            >
              <td>
                <div>{flag.name}</div>
                <div className="muted small mono">{flag.key}</div>
              </td>
              <td>{dev && <Toggle on={dev.enabled} />}</td>
              <td>{prod && <Toggle on={prod.enabled} />}</td>
              <td className="small">
                {pending ? (
                  <span
                    className={
                      pending.stale ? "badge aging-overdue" : "badge unassigned"
                    }
                  >
                    {pending.from_value ? "on" : "off"} →{" "}
                    {pending.to_value ? "on" : "off"}
                    {pending.stale ? " · stale" : ""}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="muted small">{latest ? when(latest) : ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
