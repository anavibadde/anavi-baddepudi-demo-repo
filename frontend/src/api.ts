import type {
  Config,
  LoginResult,
  NewRequest,
  RefundRequest,
  RefundRequestDetail,
  Status,
  User,
} from "./types";

const TOKEN_KEY = "refund-review-token";

let token: string | null = localStorage.getItem(TOKEN_KEY);

export const storedToken = () => token;

export function setToken(next: string | null) {
  token = next;
  if (next === null) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(TOKEN_KEY, next);
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, String(body.detail ?? response.statusText));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(userId: number, password: string): Promise<LoginResult> {
  const result = await request<LoginResult>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, password }),
  });
  setToken(result.token);
  return result;
}

export async function logout(): Promise<void> {
  // Revoke server-side first; dropping the token locally would leave it valid.
  await request<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
  setToken(null);
}

export const getMe = () => request<User>("/auth/me");

export const getConfig = () => request<Config>("/config");

export function getRequests(filters: {
  status?: Status | "";
  flagged?: boolean;
}): Promise<RefundRequest[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.flagged) params.set("flagged", "true");
  const query = params.toString();
  return request<RefundRequest[]>(`/requests${query ? `?${query}` : ""}`);
}

export const getRequest = (id: number) => request<RefundRequestDetail>(`/requests/${id}`);

export const createRequest = (payload: NewRequest) =>
  request<RefundRequestDetail>("/requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const decideRequest = (
  id: number,
  payload: { action: "approved" | "rejected"; comment: string; confirm_risk: boolean },
) =>
  request<RefundRequestDetail>(`/requests/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
