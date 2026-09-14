import type { AppSummary, User } from "../types";
import { Link } from "./Link";

const ROLE_LABELS: Record<string, string> = {
  viewer: "Read only",
  contributor: "Can submit",
  reviewer: "Can decide",
  admin: "Full access",
};

export function Home({
  viewer,
  apps,
  notice,
}: {
  viewer: User;
  apps: AppSummary[];
  notice: string;
}) {
  return (
    <section className="home">
      <h2>Your tools</h2>
      <p className="muted">
        Signed in as {viewer.name}. This lists the tools you have been granted — not every
        tool on the platform.
      </p>

      {apps.length === 0 ? (
        <p className="empty">
          You hold no tools yet. An admin grants access per tool; signing in does not.
        </p>
      ) : (
        <div className="tiles">
          {apps.map((app) => (
            <Link key={app.slug} to={app.path} className="tile">
              <h3>{app.name}</h3>
              <p>{app.description}</p>
              <span className="chip small">{ROLE_LABELS[app.app_role] ?? app.app_role}</span>
            </Link>
          ))}
        </div>
      )}

      <p className="muted small footnote">{notice}</p>
    </section>
  );
}
