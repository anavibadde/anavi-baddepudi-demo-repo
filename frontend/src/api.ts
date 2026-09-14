import type {
  Config,
  NewRequest,
  RefundRequest,
  RefundRequestDetail,
  Status,
  User,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, userId: number | null, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(userId === null ? {} : { "X-User-Id": String(userId) }),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, String(body.detail ?? response.statusText));
  }
  return (await response.json()) as T;
}

export const getConfig = () => request<Config>("/config", null);

export const getUsers = () => request<User[]>("/users", null);

export function getRequests(
  userId: number,
  filters: { status?: Status | ""; flagged?: boolean },
): Promise<RefundRequest[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.flagged) params.set("flagged", "true");
  const query = params.toString();
  return request<RefundRequest[]>(`/requests${query ? `?${query}` : ""}`, userId);
}

export const getRequest = (userId: number, id: number) =>
  request<RefundRequestDetail>(`/requests/${id}`, userId);

export const createRequest = (userId: number, payload: NewRequest) =>
  request<RefundRequestDetail>("/requests", userId, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const decideRequest = (
  userId: number,
  id: number,
  payload: { action: "approved" | "rejected"; comment: string; confirm_risk: boolean },
) =>
  request<RefundRequestDetail>(`/requests/${id}/decision`, userId, {
    method: "POST",
    body: JSON.stringify(payload),
  });
