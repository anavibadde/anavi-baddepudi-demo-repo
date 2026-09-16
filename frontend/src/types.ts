export type Role = "analyst" | "manager" | "admin";

/** Level inside one tool. Held per tool, not inherited from the platform role. */
export type AppRole = "viewer" | "contributor" | "reviewer" | "admin";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  manager_id: number | null;
  is_active: boolean;
}

export interface LoginResult {
  token: string;
  expires_at: string;
  user: User;
}

export interface AppSummary {
  slug: string;
  name: string;
  description: string;
  path: string;
  app_role: AppRole;
}

export interface PlatformConfig {
  demo_switch: boolean;
  demo_notice: string;
}
