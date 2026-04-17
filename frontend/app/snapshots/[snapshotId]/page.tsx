import Link from "next/link";

import styles from "../../dashboard.module.css";
import {
  CutoffTable,
  DistributionPanel,
  EmptyBox,
  ErrorBox,
  PageShell,
  SnapshotEntryTable,
  SnapshotValidationReportPanel,
  SummaryCards,
  ValidationIssuesPanel,
  getValidationIssueOptions,
} from "../../components/dashboard";
import {
  getSnapshot,
  getSnapshotCutoffs,
  getSnapshotDistribution,
  getSnapshotEntries,
  getSnapshotSummary,
  getSnapshotValidationReport,
} from "../../lib/api";
import type { ValidationIssueFilter } from "../../lib/types";

export const dynamic = "force-dynamic";

type SnapshotPageProps = {
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<{
    isValid?: string;
    limit?: string;
    offset?: string;
    validationIssue?: string;
    sortBy?: string;
    order?: string;
  }>;
};

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [20, 50, 100];

export default async function SnapshotDetailPage({
  params,
  searchParams,
}: SnapshotPageProps) {
  const { snapshotId } = await params;
  const resolvedSearchParams = await searchParams;
  const numericSnapshotId = Number(snapshotId);
  const isValid =
    resolvedSearchParams.isValid === "true" ||
    resolvedSearchParams.isValid === "false"
      ? resolvedSearchParams.isValid
      : "all";
  const sortBy =
    resolvedSearchParams.sortBy === "score" ? "score" : "rank";
  const order = resolvedSearchParams.order === "desc" ? "desc" : "asc";
  const requestedLimit = Number(resolvedSearchParams.limit ?? DEFAULT_PAGE_SIZE);
  const limit = PAGE_SIZE_OPTIONS.includes(requestedLimit)
    ? requestedLimit
    : DEFAULT_PAGE_SIZE;
  const requestedOffset = Number(resolvedSearchParams.offset ?? "0");
  const offset =
    Number.isInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;
  const validationIssue =
    resolvedSearchParams.validationIssue &&
    resolvedSearchParams.validationIssue.trim()
      ? (resolvedSearchParams.validationIssue as ValidationIssueFilter)
      : "all";

  const snapshotResult = await getSnapshot(numericSnapshotId);
  const snapshot = snapshotResult.data;

  if (snapshotResult.error || !snapshot) {
    return (
      <PageShell
        eyebrow="스냅샷 상세"
        title={`스냅샷 #${snapshotId}`}
        subtitle="스냅샷 통계와 엔트리 목록을 확인하는 화면입니다."
        backHref="/"
        backLabel="시즌 목록으로"
      >
        <ErrorBox
          message={`스냅샷 정보를 불러오지 못했습니다. ${
            snapshotResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      </PageShell>
    );
  }

  const [
    summaryResult,
    validationReportResult,
    cutoffsResult,
    distributionResult,
    entriesResult,
  ] =
    await Promise.all([
      getSnapshotSummary(snapshot.id),
      getSnapshotValidationReport(snapshot.id),
      getSnapshotCutoffs(snapshot.id),
      getSnapshotDistribution(snapshot.id),
      getSnapshotEntries(snapshot.id, {
        isValid: isValid === "all" ? undefined : isValid,
        validationIssue:
          validationIssue === "all" ? undefined : validationIssue,
        limit,
        offset,
        sortBy,
        order,
      }),
    ]);
  const validationIssueOptions = getValidationIssueOptions(
    summaryResult.data?.validation_issues ?? [],
    validationIssue,
  );
  const shownEntryCount = entriesResult.data?.length ?? 0;
  const currentWindowStart = shownEntryCount > 0 ? offset + 1 : 0;
  const currentWindowEnd = shownEntryCount > 0 ? offset + shownEntryCount : 0;
  const activeEntryFilters = [
    isValid !== "all" ? `유효성: ${formatValidityLabel(isValid)}` : null,
    validationIssue !== "all" ? `이슈: ${validationIssue}` : null,
    sortBy !== "rank" ? `정렬 기준: ${formatSortByLabel(sortBy)}` : null,
    order !== "asc" ? `정렬 방향: ${formatOrderLabel(order)}` : null,
    limit !== DEFAULT_PAGE_SIZE ? `개수: ${limit.toLocaleString()}` : null,
    offset > 0 ? `오프셋: ${offset.toLocaleString()}` : null,
  ].filter((value): value is string => Boolean(value));

  return (
    <PageShell
      eyebrow="스냅샷 상세"
      title={`스냅샷 #${snapshot.id}`}
      subtitle="요약, 검증, 엔트리 탐색 흐름을 한 화면에서 확인합니다."
      backHref={`/seasons/${snapshot.season_id}`}
      backLabel={`시즌 #${snapshot.season_id}로`}
    >
      <div className={styles.grid}>
        <div id="snapshot-summary" className={styles.anchorTarget}>
          {summaryResult.error || !summaryResult.data ? (
            <ErrorBox
              message={`요약 정보를 불러오지 못했습니다. ${
                summaryResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <SummaryCards summary={summaryResult.data} snapshot={snapshot} />
          )}
        </div>

        <section className={styles.panel}>
          <div className={styles.panelTitle}>
            <h2>빠른 이동</h2>
            <span className={styles.muted}>
              검증 정보와 엔트리 탐색 구간을 빠르게 오갑니다.
            </span>
          </div>
          <div className={styles.quickLinkGrid}>
            <Link href="#validation-issues" className={styles.linkButton}>
              검증 이슈
            </Link>
            <Link href="#validation-report" className={styles.linkButton}>
              검증 리포트
            </Link>
            <Link href="#entries" className={styles.linkButton}>
              엔트리 탐색
            </Link>
            <Link
              href={`/snapshots/${snapshot.id}?isValid=false`}
              className={styles.linkButton}
            >
              무효 엔트리
            </Link>
            <Link href="/" className={styles.linkButton}>
              시즌 목록
            </Link>
            <Link
              href={`/seasons/${snapshot.season_id}`}
              className={styles.linkButton}
            >
              시즌 상세
            </Link>
          </div>
        </section>

        <div className={`${styles.grid} ${styles.twoColumn}`}>
          {cutoffsResult.error || !cutoffsResult.data ? (
            <ErrorBox
              message={`컷오프를 불러오지 못했습니다. ${
                cutoffsResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <CutoffTable cutoffs={cutoffsResult.data} />
          )}

          {distributionResult.error || !distributionResult.data ? (
            <ErrorBox
              message={`분포 정보를 불러오지 못했습니다. ${
                distributionResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <DistributionPanel distribution={distributionResult.data} />
          )}
        </div>

        {summaryResult.error || !summaryResult.data ? null : (
          <div id="validation-issues" className={styles.anchorTarget}>
            <ValidationIssuesPanel
              issues={summaryResult.data.validation_issues}
              snapshotId={snapshot.id}
            />
          </div>
        )}

        <div id="validation-report" className={styles.anchorTarget}>
          {validationReportResult.error || !validationReportResult.data ? (
            <ErrorBox
              message={`검증 리포트를 불러오지 못했습니다. ${
                validationReportResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <SnapshotValidationReportPanel
              report={validationReportResult.data}
              seasonId={snapshot.season_id}
            />
          )}
        </div>

        <div id="entries" className={styles.anchorTarget}>
          <section className={styles.panel}>
            <div className={styles.panelTitle}>
              <h2>랭킹 엔트리 탐색</h2>
              <span className={styles.muted}>
                백엔드 query parameter로 직접 필터링합니다.
              </span>
            </div>

            {activeEntryFilters.length > 0 ? (
              <div className={styles.filterSummary}>
                {activeEntryFilters.map((filter) => (
                  <span key={filter} className={styles.filterChip}>
                    {filter}
                  </span>
                ))}
              </div>
            ) : (
              <p className={styles.panelLead}>
                기본값은 순위 오름차순, 최대 20개, 전체 엔트리입니다.
              </p>
            )}

            <div className={styles.compactSummaryGrid}>
              <div className={styles.subPanel}>
                <div className={styles.panelTitle}>
                  <h3>현재 조회 범위</h3>
                </div>
                <div className={styles.keyValueList}>
                  <div className={styles.keyValueRow}>
                    <span>표시 중인 엔트리</span>
                    <strong>{shownEntryCount.toLocaleString()}</strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>현재 구간</span>
                    <strong>
                      {shownEntryCount > 0
                        ? `${currentWindowStart.toLocaleString()} ~ ${currentWindowEnd.toLocaleString()}`
                        : "-"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>정렬</span>
                    <strong>
                      {formatSortByLabel(sortBy)} · {formatOrderLabel(order)}
                    </strong>
                  </div>
                </div>
              </div>
              <div className={styles.subPanel}>
                <div className={styles.panelTitle}>
                  <h3>빠른 바로가기</h3>
                </div>
                <div className={styles.paginationLinks}>
                  <Link href={`/snapshots/${snapshot.id}`} className={styles.linkButton}>
                    전체 엔트리
                  </Link>
                  <Link
                    href={`/snapshots/${snapshot.id}?isValid=true`}
                    className={styles.linkButton}
                  >
                    유효만 보기
                  </Link>
                  <Link
                    href={`/snapshots/${snapshot.id}?isValid=false`}
                    className={styles.linkButton}
                  >
                    무효만 보기
                  </Link>
                </div>
              </div>
            </div>

            <form className={styles.controls}>
              <div className={styles.filterSection}>
                <div className={styles.sectionHeader}>
                  <h3>탐색 필터</h3>
                  <span className={styles.muted}>
                    유효성, 이슈, 정렬을 먼저 정하고 오프셋으로 구간을 이동합니다.
                  </span>
                </div>
                <div className={styles.filterGrid}>
                  <div className={styles.field}>
                    <label htmlFor="isValid">유효성</label>
                    <select id="isValid" name="isValid" defaultValue={isValid}>
                      <option value="all">전체</option>
                      <option value="true">유효</option>
                      <option value="false">무효</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="validationIssue">이슈</label>
                    <select
                      id="validationIssue"
                      name="validationIssue"
                      defaultValue={validationIssue}
                    >
                      <option value="all">전체</option>
                      {validationIssueOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="sortBy">정렬 기준</label>
                    <select id="sortBy" name="sortBy" defaultValue={sortBy}>
                      <option value="rank">순위</option>
                      <option value="score">점수</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="order">정렬 방향</label>
                    <select id="order" name="order" defaultValue={order}>
                      <option value="asc">오름차순</option>
                      <option value="desc">내림차순</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="limit">개수</label>
                    <select id="limit" name="limit" defaultValue={String(limit)}>
                      {PAGE_SIZE_OPTIONS.map((pageSize) => (
                        <option key={pageSize} value={pageSize}>
                          {pageSize}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="offset">오프셋</label>
                    <input
                      id="offset"
                      name="offset"
                      type="number"
                      min="0"
                      step="1"
                      defaultValue={offset}
                    />
                  </div>
                </div>
              </div>
              <div className={styles.filterActions}>
                <button type="submit" className={styles.button}>
                  필터 적용
                </button>
                <Link
                  href={`/snapshots/${snapshot.id}`}
                  className={styles.linkButton}
                >
                  필터 초기화
                </Link>
              </div>
            </form>

            {entriesResult.error ? (
              <ErrorBox
                message={`엔트리 목록을 불러오지 못했습니다. ${entriesResult.error}`}
              />
            ) : entriesResult.data && entriesResult.data.length > 0 ? (
              <>
                <SnapshotEntryTable entries={entriesResult.data} />
                <div className={styles.pagination}>
                  <span className={styles.muted}>
                    현재 {currentWindowStart.toLocaleString()} ~ {currentWindowEnd.toLocaleString()}
                    번째 엔트리를 보고 있습니다. 다음 구간을 보려면 오프셋을{" "}
                    {(offset + limit).toLocaleString()}로 바꿔 적용하세요.
                  </span>
                </div>
              </>
            ) : (
              <EmptyBox message="조건에 맞는 엔트리가 없습니다." />
            )}
          </section>
        </div>
      </div>
    </PageShell>
  );
}

function formatValidityLabel(value: string) {
  switch (value) {
    case "true":
      return "유효";
    case "false":
      return "무효";
    default:
      return value;
  }
}

function formatSortByLabel(value: string) {
  switch (value) {
    case "score":
      return "점수";
    case "rank":
      return "순위";
    default:
      return value;
  }
}

function formatOrderLabel(value: string) {
  switch (value) {
    case "desc":
      return "내림차순";
    case "asc":
      return "오름차순";
    default:
      return value;
  }
}
