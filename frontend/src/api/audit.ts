import { apiFetch, buildQueryString } from "./client";
import type { AuditEntry } from "./types";

export async function fetchAuditLog(params?: {
  document_id?: string;
  author?: string;
  operation?: string;
  since?: string;
  until?: string;
  limit?: number;
}): Promise<AuditEntry[]> {
  const qs = buildQueryString(params ?? {});
  return apiFetch<AuditEntry[]>(`/audit-log${qs}`);
}

export async function setReviewStatus(
  documentId: string,
  status: string,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(
    `/documents/${documentId}/review-status`,
    {
      method: "POST",
      body: JSON.stringify({ status }),
    },
  );
}

export async function setVersionArchived(
  documentId: string,
  versionId: string,
  archived: boolean,
): Promise<{ archived: boolean }> {
  return apiFetch<{ archived: boolean }>(
    `/documents/${documentId}/versions/${versionId}/archive`,
    {
      method: "POST",
      body: JSON.stringify({ archived }),
    },
  );
}
