import { request } from "../../api";
import type {
  NewRequest,
  RefundRequestDetail,
  RefundsConfig,
  RequestPage,
  Status,
} from "./types";

export const getRefundsConfig = () => request<RefundsConfig>("/refunds/config");

export function getRequests(filters: {
  status?: Status | "";
  flagged?: boolean;
  limit?: number;
  offset?: number;
}): Promise<RequestPage> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.flagged) params.set("flagged", "true");
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<RequestPage>(`/refunds/requests${query ? `?${query}` : ""}`);
}

export const getRequest = (id: number) =>
  request<RefundRequestDetail>(`/refunds/requests/${id}`);

export const createRequest = (payload: NewRequest) =>
  request<RefundRequestDetail>("/refunds/requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const decideRequest = (
  id: number,
  payload: { action: "approved" | "rejected"; comment: string; confirm_risk: boolean },
) =>
  request<RefundRequestDetail>(`/refunds/requests/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
