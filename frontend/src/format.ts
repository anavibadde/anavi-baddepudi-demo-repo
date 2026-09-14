export function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const BLOCKED_REASONS: Record<string, string> = {
  cannot_decide_own_request: "You submitted this request",
  analysts_cannot_decide: "Analysts cannot decide requests",
  already_decided: "Already decided",
  admin_approval_required: "Needs an admin: high value plus another risk flag",
  not_found: "Not visible to you",
};

export function blockedReason(reason: string | null): string | null {
  if (!reason) return null;
  return BLOCKED_REASONS[reason] ?? humanize(reason);
}
