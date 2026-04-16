import Link from "next/link";

import styles from "../../dashboard.module.css";
import {
  CutoffTable,
  DistributionPanel,
  EmptyBox,
  ErrorBox,
  PageShell,
  SnapshotEntryTable,
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
} from "../../lib/api";
import type { ValidationIssueFilter } from "../../lib/types";

export const dynamic = "force-dynamic";

type SnapshotPageProps = {
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<{
    isValid?: string;
    validationIssue?: string;
    sortBy?: string;
    order?: string;
  }>;
};

const PAGE_SIZE = 20;

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
        eyebrow="Snapshot Detail"
        title={`Snapshot #${snapshotId}`}
        subtitle="snapshot 통계와 entry 목록을 확인하는 화면입니다."
        backHref="/"
        backLabel="시즌 목록으로"
      >
        <ErrorBox
          message={`snapshot 정보를 불러오지 못했습니다. ${
            snapshotResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      </PageShell>
    );
  }

  const [summaryResult, cutoffsResult, distributionResult, entriesResult] =
    await Promise.all([
      getSnapshotSummary(snapshot.id),
      getSnapshotCutoffs(snapshot.id),
      getSnapshotDistribution(snapshot.id),
      getSnapshotEntries(snapshot.id, {
        isValid: isValid === "all" ? undefined : isValid,
        validationIssue:
          validationIssue === "all" ? undefined : validationIssue,
        limit: PAGE_SIZE,
        offset: 0,
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
      eyebrow="Snapshot Detail"
      title={`Snapshot #${snapshot.id}`}
      subtitle="summary, cutoffs, distribution, entry 목록을 한 화면에서 확인합니다."
      backHref={`/seasons/${snapshot.season_id}`}
      backLabel={`시즌 #${snapshot.season_id}로`}
    >
      <div className={styles.grid}>
        {summaryResult.error || !summaryResult.data ? (
          <ErrorBox
            message={`summary를 불러오지 못했습니다. ${
              summaryResult.error ?? "알 수 없는 오류입니다."
            }`}
          />
        ) : (
          <SummaryCards summary={summaryResult.data} snapshot={snapshot} />
        )}

        <div className={`${styles.grid} ${styles.twoColumn}`}>
          {cutoffsResult.error || !cutoffsResult.data ? (
            <ErrorBox
              message={`cutoffs를 불러오지 못했습니다. ${
                cutoffsResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <CutoffTable cutoffs={cutoffsResult.data} />
          )}

          {distributionResult.error || !distributionResult.data ? (
            <ErrorBox
              message={`distribution을 불러오지 못했습니다. ${
                distributionResult.error ?? "알 수 없는 오류입니다."
              }`}
            />
          ) : (
            <DistributionPanel distribution={distributionResult.data} />
          )}
        </div>

        {summaryResult.error || !summaryResult.data ? null : (
          <ValidationIssuesPanel issues={summaryResult.data.validation_issues} />
        )}

        <section className={styles.panel}>
          <div className={styles.panelTitle}>
            <h2>Ranking Entries</h2>
            <span className={styles.muted}>
              backend query parameter로 필터링합니다.
            </span>
          </div>

          <form className={styles.controls}>
            <div className={styles.controlRow}>
              <div className={styles.field}>
                <label htmlFor="isValid">Validity</label>
                <select id="isValid" name="isValid" defaultValue={isValid}>
                  <option value="all">all</option>
                  <option value="true">valid</option>
                  <option value="false">invalid</option>
                </select>
              </div>
              <div className={styles.field}>
                <label htmlFor="sortBy">Sort By</label>
                <select id="sortBy" name="sortBy" defaultValue={sortBy}>
                  <option value="rank">rank</option>
                  <option value="score">score</option>
                </select>
              </div>
              <div className={styles.field}>
                <label htmlFor="validationIssue">Issue</label>
                <select
                  id="validationIssue"
                  name="validationIssue"
                  defaultValue={validationIssue}
                >
                  <option value="all">all</option>
                  {validationIssueOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label htmlFor="order">Order</label>
                <select id="order" name="order" defaultValue={order}>
                  <option value="asc">asc</option>
                  <option value="desc">desc</option>
                </select>
              </div>
              <button type="submit" className={styles.button}>
                적용
              </button>
            </div>
          </form>

          {entriesResult.error ? (
            <ErrorBox
              message={`entry 목록을 불러오지 못했습니다. ${entriesResult.error}`}
            />
          ) : entriesResult.data && entriesResult.data.length > 0 ? (
            <>
              <SnapshotEntryTable entries={entriesResult.data} />
              <div className={styles.pagination}>
                <span className={styles.muted}>
                  최대 {PAGE_SIZE}개의 entry를 표시합니다. 더 많은 entry 탐색은
                  backend API의 `limit`/`offset`을 직접 사용하세요.
                </span>
              </div>
            </>
          ) : (
            <EmptyBox message="조건에 맞는 entry가 없습니다." />
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
