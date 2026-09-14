import type { AppSummary, LoginResult, PlatformConfig, User } from "./types";

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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

export async function switchUser(userId: number): Promise<LoginResult> {
  // Demo only. The server mints a real session for the target, so the app is
  // genuinely that person afterwards rather than pretending locally.
  const result = await request<LoginResult>("/auth/switch", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
  setToken(result.token);
  return result;
}

export const getMe = () => request<User>("/auth/me");

export const getUsers = () => request<User[]>("/users");

export const getConfig = () => request<PlatformConfig>("/config");

/** Tools this person holds. The server repeats the check on every tool call. */
export const getApps = () => request<AppSummary[]>("/me/apps");
