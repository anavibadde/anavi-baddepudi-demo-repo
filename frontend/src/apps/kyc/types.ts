import type { User } from "../../types";

export type CaseStatus =
  "new" | "claimed" | "recommended" | "needs_info" | "approved" | "rejected";

export type RiskTier = "standard" | "enhanced";

export type CaseAction =
  | "opened"
  | "claimed"
  | "released"
  | "claim_expired"
  | "recommended"
  | "info_requested"
  | "info_supplied"
  | "approved"
  | "rejected";

export interface KycCase {
  id: number;
  reference: string;
  applicant_name: string;
  country: string;
  entity_type: string;
  risk_tier: RiskTier;
  summary: string;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
  cycles: number;
  claimer: User | null;
  claimed_at: string | null;
  claim_expires_at: string | null;
  claim_expired: boolean;
  recommender: User | null;
  recommendation: CaseStatus | null;
  recommended_at: string | null;
  decider: User | null;
  decided_at: string | null;
  can_claim: boolean;
  can_recommend: boolean;
  can_sign_off: boolean;
  blocked_reason: string | null;
}

export interface CaseEvent {
  id: number;
  action: CaseAction;
  cycle: number;
  comment: string;
  actor: User | null;
  created_at: string;
}

export interface CaseDetail extends KycCase {
  events: CaseEvent[];
}

export interface KycConfig {
  statuses: CaseStatus[];
  risk_tiers: RiskTier[];
  claim_hours: number;
  can_review: boolean;
  can_sign_off: boolean;
}
