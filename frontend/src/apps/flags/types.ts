import type { User } from "../../types";

export type Environment = "dev" | "prod";

export type ChangeStatus = "pending" | "applied" | "rejected" | "withdrawn";

export type FlagAction =
  "set_directly" | "proposed" | "applied" | "rejected" | "withdrawn";

export interface FlagStateRow {
  environment: Environment;
  enabled: boolean;
  updated_at: string;
  updated_by: User | null;
}

export interface ChangeRequest {
  id: number;
  flag_id: number;
  flag_key: string;
  environment: Environment;
  from_value: boolean;
  to_value: boolean;
  reason: string;
  status: ChangeStatus;
  requester: User;
  requested_at: string;
  decider: User | null;
  decided_at: string | null;
  decision_note: string;
  stale: boolean;
  can_decide: boolean;
  decide_blocked_reason: string | null;
}

export interface FlagEvent {
  id: number;
  action: FlagAction;
  environment: Environment;
  from_value: boolean | null;
  to_value: boolean | null;
  comment: string;
  actor: User;
  created_at: string;
}

export interface Flag {
  id: number;
  key: string;
  name: string;
  description: string;
  states: FlagStateRow[];
  pending: ChangeRequest[];
}

export interface FlagDetail extends Flag {
  events: FlagEvent[];
}

export interface FlagsConfig {
  environments: Environment[];
  can_edit: boolean;
  can_approve: boolean;
}
