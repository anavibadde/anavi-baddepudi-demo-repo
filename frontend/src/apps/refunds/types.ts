import type { User } from "../../types";

export type Status = "pending" | "approved" | "rejected";
export type Action = "submitted" | "approved" | "rejected";

export interface DecisionEvent {
  id: number;
  action: Action;
  comment: string;
  created_at: string;
  actor: User;
}

export interface RefundRequest {
  id: number;
  customer_id: string;
  customer_name: string;
  order_id: string;
  reason: string;
  amount_cents: number;
  currency: string;
  note: string;
  status: Status;
  risk_flags: string[];
  requires_admin: boolean;
  created_at: string;
  decided_at: string | null;
  submitter: User;
  decider: User | null;
  can_decide: boolean;
  decide_blocked_reason: string | null;
  age_hours: number;
  aging: "due" | "overdue" | null;
  unassigned: boolean;
}

export interface RequestPage {
  items: RefundRequest[];
  total: number;
  limit: number;
  offset: number;
}

export interface RefundRequestDetail extends RefundRequest {
  events: DecisionEvent[];
}

export interface RefundsConfig {
  high_value_cents: number;
  reasons: string[];
  flag_labels: Record<string, string>;
  aging_labels: Record<string, string>;
  due_hours: number;
  overdue_hours: number;
  page_size: number;
}

export interface NewRequest {
  customer_id: string;
  customer_name: string;
  order_id: string;
  reason: string;
  amount_cents: number;
  note: string;
  idempotency_key: string;
}
