import { request } from "../../api";
import type { CaseDetail, CaseStatus, KycCase, KycConfig } from "./types";

export const getKycConfig = () => request<KycConfig>("/kyc/config");

export const getCases = (params: { status?: CaseStatus; mine?: boolean }) => {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.mine) query.set("mine", "true");
  const suffix = query.toString();
  return request<KycCase[]>(`/kyc/cases${suffix ? `?${suffix}` : ""}`);
};

export const getCase = (id: number) => request<CaseDetail>(`/kyc/cases/${id}`);

export const claimCase = (id: number) =>
  request<CaseDetail>(`/kyc/cases/${id}/claim`, { method: "POST" });

export const releaseCase = (id: number) =>
  request<CaseDetail>(`/kyc/cases/${id}/release`, { method: "POST" });

export const recommendCase = (
  id: number,
  payload: { recommendation: CaseStatus; note: string },
) =>
  request<CaseDetail>(`/kyc/cases/${id}/recommendation`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const signOffCase = (
  id: number,
  payload: { approve: boolean; note: string },
) =>
  request<CaseDetail>(`/kyc/cases/${id}/sign-off`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const requestInfo = (id: number, note: string) =>
  request<CaseDetail>(`/kyc/cases/${id}/needs-info`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const supplyInfo = (id: number, note: string) =>
  request<CaseDetail>(`/kyc/cases/${id}/info-supplied`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
