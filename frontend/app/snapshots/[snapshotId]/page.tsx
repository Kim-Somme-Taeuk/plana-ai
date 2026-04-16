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
  return (
    <PageShell
      eyebrow="스냅샷 상세"
      title={`스냅샷 #${snapshot.id}`}
      subtitle="요약, 컷오프, 분포, 엔트리 목록을 한 화면에서 확인합니다."
      backHref={`/seasons/${snapshot.season_id}`}
      backLabel={`시즌 #${snapshot.season_id}로`}
    >
      <div className={styles.grid}>
        {summaryResult.error || !summaryResult.data ? (
          <ErrorBox
            message={`요약 정보를 불러오지 못했습니다. ${
              summaryResult.error ?? "알 수 없는 오류입니다."
            }`}
          />
        ) : (
          <SummaryCards summary={summaryResult.data} snapshot={snapshot} />
        )}

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
          <ValidationIssuesPanel
            issues={summaryResult.data.validation_issues}
            snapshotId={snapshot.id}
          />
        )}

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

        <section className={styles.panel}>
          <div className={styles.panelTitle}>
            <h2>랭킹 엔트리</h2>
            <span className={styles.muted}>
              백엔드 query parameter로 필터링합니다.
            </span>
          </div>

          <form className={styles.controls}>
            <div className={styles.controlRow}>
              <div className={styles.field}>
                <label htmlFor="isValid">유효성</label>
                <select id="isValid" name="isValid" defaultValue={isValid}>
                  <option value="all">전체</option>
                  <option value="true">유효</option>
                  <option value="false">무효</option>
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
                <label htmlFor="order">정렬 방향</label>
                <select id="order" name="order" defaultValue={order}>
                  <option value="asc">오름차순</option>
                  <option value="desc">내림차순</option>
                </select>
              </div>
              <button type="submit" className={styles.button}>
                적용
              </button>
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
                  현재 offset {offset.toLocaleString()}에서 최대{" "}
                  {limit.toLocaleString()}개의 엔트리를 표시합니다.
                </span>
              </div>
            </>
          ) : (
            <EmptyBox message="조건에 맞는 엔트리가 없습니다." />
          )}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelTitle}>
            <h2>빠른 이동</h2>
          </div>
          <div className={styles.paginationLinks}>
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
      </div>
    </PageShell>
  );
}
