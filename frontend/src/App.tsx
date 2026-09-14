import { useCallback, useEffect, useState } from "react";

import {
  getApps,
  getConfig,
  getMe,
  logout,
  setToken,
  storedToken,
} from "./api";
import { FlagsApp } from "./apps/flags/FlagsApp";
import { RefundsApp } from "./apps/refunds/RefundsApp";
import { Home } from "./shell/Home";
import { LoginForm } from "./shell/LoginForm";
import { Link } from "./shell/Link";
import { navigate, usePath } from "./shell/router";
import { ViewAs } from "./shell/ViewAs";
import "./App.css";
import type { AppSummary, PlatformConfig, User } from "./types";

export default function App() {
  const [config, setConfig] = useState<PlatformConfig | null>(null);
  const [viewer, setViewer] = useState<User | null>(null);
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [restoring, setRestoring] = useState(storedToken() !== null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = usePath();

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch(() =>
        setError(
          "Could not reach the API. Is the backend running on port 8000?",
        ),
      );
  }, []);

  useEffect(() => {
    // A token in localStorage may be expired or revoked; the server decides.
    if (storedToken() === null) return;
    getMe()
      .then(setViewer)
      .catch(() => setToken(null))
      .finally(() => setRestoring(false));
  }, []);

  useEffect(() => {
    if (!viewer) return;
    getApps()
      .then(setApps)
      .catch(() => setApps([]));
  }, [viewer]);

  const onDrawerChange = useCallback(
    (open: boolean) => setDrawerOpen(open),
    [],
  );

  function signedInAs(user: User) {
    setViewer(user);
    setDrawerOpen(false);
  }

  function switchedTo(user: User) {
    // The new identity may hold a different set of tools, so land on home
    // rather than inside a tool they may no longer be able to open.
    signedInAs(user);
    navigate("/");
  }

  async function signOut() {
    await logout();
    setViewer(null);
    setApps([]);
    setDrawerOpen(false);
    navigate("/");
  }

  if (error) return <main className="shell error">{error}</main>;
  if (!config || restoring) return <main className="shell">Loading…</main>;
  if (!viewer) return <LoginForm onSignedIn={signedInAs} />;

  const held = apps.find((app) => app.path === path);
  const inTool = held !== undefined;

  return (
    <main className={drawerOpen ? "shell drawer-open" : "shell"}>
      <header className="topbar">
        <div className="brand">
          <Link to="/" className="home-link">
            Internal tools
          </Link>
          {inTool && <span className="crumb">{held.name}</span>}
        </div>
        <div className="session">
          {config.demo_switch ? (
            <ViewAs
              viewer={viewer}
              notice={config.demo_notice}
              onSwitched={switchedTo}
            />
          ) : (
            <span className="muted">
              {viewer.name} <span className="small">({viewer.role})</span>
            </span>
          )}
          <button onClick={signOut}>Sign out</button>
        </div>
      </header>

      {path === "/refunds" && inTool ? (
        <RefundsApp
          // Remount per identity: a row selected as someone else must not stay
          // open against a queue they cannot see.
          key={viewer.id}
          viewer={viewer}
          onSignedOut={() => setViewer(null)}
          onDrawerChange={onDrawerChange}
        />
      ) : path === "/flags" && inTool ? (
        <FlagsApp
          key={viewer.id}
          viewer={viewer}
          onSignedOut={() => setViewer(null)}
          onDrawerChange={onDrawerChange}
        />
      ) : path === "/" ? (
        <Home viewer={viewer} apps={apps} notice={config.demo_notice} />
      ) : (
        <section className="home">
          <h2>Not available</h2>
          <p className="muted">
            {inTool
              ? "This tool has no screen yet."
              : "You do not have access to this tool, or it does not exist."}
          </p>
          <Link to="/" className="chip">
            Back to your tools
          </Link>
        </section>
      )}
    </main>
  );
}
