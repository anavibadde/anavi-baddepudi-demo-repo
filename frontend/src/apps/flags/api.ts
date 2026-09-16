import { request } from "../../api";
import type {
  ChangeRequest,
  Environment,
  Flag,
  FlagDetail,
  FlagsConfig,
} from "./types";

export const getFlagsConfig = () => request<FlagsConfig>("/flags/config");

export const getFlags = () => request<Flag[]>("/flags/flags");

export const getFlag = (id: number) =>
  request<FlagDetail>(`/flags/flags/${id}`);

export const getOpenRequests = () =>
  request<ChangeRequest[]>("/flags/requests");

export const getEffective = (environment: Environment) =>
  request<Record<string, boolean>>(`/flags/effective/${environment}`);

export const setState = (
  id: number,
  payload: { environment: Environment; enabled: boolean; reason?: string },
) =>
  request<FlagDetail>(`/flags/flags/${id}/state`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const proposeChange = (
  id: number,
  payload: {
    environment: Environment;
    from_value: boolean;
    to_value: boolean;
    reason: string;
  },
) =>
  request<FlagDetail>(`/flags/flags/${id}/requests`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const decideChange = (
  id: number,
  payload: { approve: boolean; note: string },
) =>
  request<FlagDetail>(`/flags/requests/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const withdrawChange = (id: number) =>
  request<FlagDetail>(`/flags/requests/${id}/withdraw`, { method: "POST" });
