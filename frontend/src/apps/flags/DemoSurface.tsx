import type { Environment } from "./types";

interface Props {
  environment: Environment;
  environments: Environment[];
  effective: Record<string, boolean>;
  onEnvironmentChange: (environment: Environment) => void;
}

/** A pretend customer page whose contents come from the same rows an approval
 * writes, so an applied change is visible rather than merely logged. */
export function DemoSurface({
  environment,
  environments,
  effective,
  onEnvironmentChange,
}: Props) {
  const on = (key: string) => effective[key] === true;

  return (
    <section className="demo-surface">
      <header>
        <div>
          <h3>Customer page (simulated)</h3>
          <p className="muted small">
            Rendered from the stored configuration for this environment — not a
            mock.
          </p>
        </div>
        <div className="filters">
          {environments.map((value) => (
            <button
              key={value}
              className={environment === value ? "chip active" : "chip"}
              onClick={() => onEnvironmentChange(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </header>

      <div
        className={on("dashboard.new_nav") ? "fake-page new-nav" : "fake-page"}
      >
        <nav>
          {on("dashboard.new_nav") ? "Home · Orders · Billing" : "☰ Menu"}
        </nav>
        <div className="fake-body">
          <p>
            <strong>Order #A-4821</strong> · $84.00
          </p>
          {on("pricing.annual_discount") && (
            <p className="fake-banner">
              Save 20% when you switch to annual billing.
            </p>
          )}
          <p>
            {on("checkout.express_refunds")
              ? "Refund issued instantly to your card."
              : "Request a refund — a specialist reviews it within 2 business days."}
          </p>
        </div>
        {on("support.chat_widget") && (
          <div className="fake-chat">Chat with us</div>
        )}
      </div>
    </section>
  );
}
