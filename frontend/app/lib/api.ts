import "server-only";

import type {
  ApiResult,
  RankingEntry,
  RankingSnapshot,
  RankingSnapshotCutoffs,
  RankingSnapshotDistribution,
  RankingSnapshotSummary,
  RankingSnapshotValidationReport,
  Season,
  SeasonCutoffSeries,
  SeasonValidationSeries,
  SeasonValidationOverview,
  ValidationIssueFilter,
} from "./types";

const EXPLICIT_API_BASE_URL =
  process.env.BACKEND_INTERNAL_URL || process.env.API_BASE_URL || null;
const DEFAULT_API_BASE_URL_CANDIDATES = [
  "http://localhost:8000",
  "http://backend:8000",
];

let resolvedApiBaseUrl: string | null = EXPLICIT_API_BASE_URL;

function normalizeError(detail: unknown, fallback: string): string {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first) {
      return String(first.msg);
    }
  }

  return fallback;
}

async function fetchApi<T>(path: string): Promise<ApiResult<T>> {
  const candidateBaseUrls = resolvedApiBaseUrl
    ? [resolvedApiBaseUrl]
    : DEFAULT_API_BASE_URL_CANDIDATES;

  for (const baseUrl of candidateBaseUrls) {
    try {
      const response = await fetch(`${baseUrl}${path}`, {
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      });

      resolvedApiBaseUrl = baseUrl;

      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        return {
          data: null,
          error: normalizeError(payload?.detail, "데이터를 불러오지 못했습니다."),
          status: response.status,
        };
      }

      return {
        data: payload as T,
        error: null,
        status: response.status,
      };
    } catch {
      continue;
    }
  }

  return {
    data: null,
    error: "서버에 연결하지 못했습니다.",
    status: 500,
  };
}

export function getSeasons() {
  return fetchApi<Season[]>("/seasons");
}

export function getSeason(seasonId: number) {
  return fetchApi<Season>(`/seasons/${seasonId}`);
}

export function getSeasonSnapshots(seasonId: number) {
  return fetchApi<RankingSnapshot[]>(`/seasons/${seasonId}/ranking-snapshots`);
}

export function getSnapshot(snapshotId: number) {
  return fetchApi<RankingSnapshot>(`/ranking-snapshots/${snapshotId}`);
}

export function getSnapshotSummary(snapshotId: number) {
  return fetchApi<RankingSnapshotSummary>(
    `/ranking-snapshots/${snapshotId}/summary`,
  );
}

export function getSnapshotValidationReport(snapshotId: number) {
  return fetchApi<RankingSnapshotValidationReport>(
    `/ranking-snapshots/${snapshotId}/validation-report`,
  );
}

export function getSnapshotCutoffs(snapshotId: number) {
  return fetchApi<RankingSnapshotCutoffs>(
    `/ranking-snapshots/${snapshotId}/cutoffs`,
  );
}

export function getSnapshotDistribution(snapshotId: number) {
  return fetchApi<RankingSnapshotDistribution>(
    `/ranking-snapshots/${snapshotId}/distribution`,
  );
}

export function getSnapshotEntries(
  snapshotId: number,
  options: {
    isValid?: "true" | "false";
    validationIssue?: ValidationIssueFilter;
    limit?: number;
    offset?: number;
    sortBy?: "rank" | "score";
    order?: "asc" | "desc";
  } = {},
) {
  const params = new URLSearchParams();

  if (options.isValid) {
    params.set("is_valid", options.isValid);
  }

  if (options.validationIssue) {
    params.set("validation_issue", options.validationIssue);
  }

  if (options.limit) {
    params.set("limit", String(options.limit));
  }

  if (options.offset) {
    params.set("offset", String(options.offset));
  }

  if (options.sortBy) {
    params.set("sort_by", options.sortBy);
  }

  if (options.order) {
    params.set("order", options.order);
  }

  const query = params.toString();
  return fetchApi<RankingEntry[]>(
    `/ranking-snapshots/${snapshotId}/entries${query ? `?${query}` : ""}`,
  );
}

export function getSeasonCutoffSeries(
  seasonId: number,
  rank: number,
  options: {
    sourceType?: string;
  } = {},
) {
  const params = new URLSearchParams();
  params.set("rank", String(rank));
  if (options.sourceType) {
    params.set("source_type", options.sourceType);
  }
  return fetchApi<SeasonCutoffSeries>(
    `/seasons/${seasonId}/cutoff-series?${params.toString()}`,
  );
}

export function getSeasonValidationOverview(
  seasonId: number,
  options: {
    status?: "completed" | "collecting" | "failed";
    sourceType?: string;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.status) {
    params.set("status", options.status);
  }
  if (options.sourceType) {
    params.set("source_type", options.sourceType);
  }
  return fetchApi<SeasonValidationOverview>(
    `/seasons/${seasonId}/validation-overview${params.size ? `?${params.toString()}` : ""}`,
  );
}

export function getSeasonValidationSeries(
  seasonId: number,
  options: {
    status?: "completed" | "collecting" | "failed";
    sourceType?: string;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.status) {
    params.set("status", options.status);
  }
  if (options.sourceType) {
    params.set("source_type", options.sourceType);
  }
  return fetchApi<SeasonValidationSeries>(
    `/seasons/${seasonId}/validation-series${params.size ? `?${params.toString()}` : ""}`,
  );
}
