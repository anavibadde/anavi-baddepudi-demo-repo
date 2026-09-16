import { useCallback, useEffect, useState } from "react";

import { ApiError, setToken } from "../../api";
import type { User } from "../../types";
import { getEffective, getFlags, getFlagsConfig } from "./api";
import { DemoSurface } from "./DemoSurface";
import { FlagDetail } from "./FlagDetail";
import { FlagTable } from "./FlagTable";
import type { Environment, Flag, FlagsConfig } from "./types";

export function FlagsApp({
  viewer,
  onSignedOut,
  onDrawerChange,
}: {
  viewer: User;
  onSignedOut: () => void;
  onDrawerChange: (open: boolean) => void;
}) {
  const [config, setConfig] = useState<FlagsConfig | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [effective, setEffective] = useState<Record<string, boolean>>({});
  const [surface, setSurface] = useState<Environment>("prod");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getFlagsConfig()
      .then(setConfig)
      .catch(() => setError("Could not load the flags tool."));
  }, []);

  useEffect(
    () => onDrawerChange(selectedId !== null),
    [selectedId, onDrawerChange],
  );

  const refresh = useCallback(() => {
    Promise.all([getFlags(), getEffective(surface)])
      .then(([loaded, config]) => {
        setFlags(loaded);
        setEffective(config);
      })
      .catch((err: ApiError) => {
        if (err.status === 401) {
          setToken(null);
          onSignedOut();
          return;
        }
        setError("Could not load flags.");
      });
  }, [surface, onSignedOut]);

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

  const openCount = flags.reduce(
    (total, flag) => total + flag.pending.length,
    0,
  );

  return (
    <>
      <section className="controls">
        <div className="filters">
          <span className="muted small">
            Dev moves on the spot · production needs a second approver
          </span>
        </div>
        <div className="right-controls">
          <span className="muted small">
            {flags.length} flags
            {openCount > 0 && (
              <span className="overdue-count">
                {" "}
                · {openCount} awaiting approval
              </span>
            )}
          </span>
        </div>
      </section>

      <FlagTable
        flags={flags}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      <DemoSurface
        environment={surface}
        environments={config.environments}
        effective={effective}
        onEnvironmentChange={setSurface}
      />

      {selectedId !== null && (
        <FlagDetail
          key={`${viewer.id}-${selectedId}`}
          flagId={selectedId}
          config={config}
          onChanged={refresh}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  );
}
