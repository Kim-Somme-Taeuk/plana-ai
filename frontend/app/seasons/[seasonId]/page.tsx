import Link from "next/link";

import styles from "../../dashboard.module.css";
import {
  CutoffSeriesPanel,
  EmptyBox,
  ErrorBox,
  PageShell,
  SeasonValidationOverviewPanel,
  SeasonSummary,
  SnapshotList,
  ValidationIssuesPanel,
} from "../../components/dashboard";
import {
  getSeason,
  getSeasonCutoffSeries,
  getSeasonSnapshots,
  getSeasonValidationOverview,
} from "../../lib/api";

export const dynamic = "force-dynamic";

type SeasonPageProps = {
  params: Promise<{ seasonId: string }>;
  searchParams: Promise<{ rank?: string; status?: string; source?: string }>;
};

const SERIES_RANK_OPTIONS = [1, 10, 100, 1000, 5000, 10000];

export default async function SeasonDetailPage({
  params,
  searchParams,
}: SeasonPageProps) {
  const { seasonId } = await params;
  const resolvedSearchParams = await searchParams;
  const numericSeasonId = Number(seasonId);
  const seriesRank = Number(resolvedSearchParams.rank ?? "10");
  const selectedStatus =
    resolvedSearchParams.status && resolvedSearchParams.status.trim()
      ? resolvedSearchParams.status
      : "all";
  const selectedSource =
    resolvedSearchParams.source && resolvedSearchParams.source.trim()
      ? resolvedSearchParams.source
      : "all";

  const [seasonResult, snapshotsResult, seriesResult, validationOverviewResult] =
    await Promise.all([
      getSeason(numericSeasonId),
      getSeasonSnapshots(numericSeasonId),
      getSeasonCutoffSeries(numericSeasonId, Number.isNaN(seriesRank) ? 10 : seriesRank),
      getSeasonValidationOverview(numericSeasonId),
    ]);

  const season = seasonResult.data;
  const snapshots = snapshotsResult.data ?? [];
  const sourceOptions = Array.from(
    new Set(snapshots.map((snapshot) => snapshot.source_type)),
  ).sort();
  const filteredSnapshots = snapshots.filter((snapshot) => {
    if (selectedStatus !== "all" && snapshot.status !== selectedStatus) {
      return false;
    }
    if (selectedSource !== "all" && snapshot.source_type !== selectedSource) {
      return false;
    }
    return true;
  });

  return (
    <PageShell
      eyebrow="Season Detail"
      title={season?.season_label ?? `Season #${seasonId}`}
      subtitle="시즌 정보, snapshot 목록, 기본 cutoff 시계열을 함께 확인합니다."
      backHref="/"
      backLabel="시즌 목록으로"
    >
      {seasonResult.error || !season ? (
        <ErrorBox
          message={`시즌 정보를 불러오지 못했습니다. ${
            seasonResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      ) : (
        <div className={`${styles.grid} ${styles.twoColumn}`}>
          <div className={styles.grid}>
            <SeasonSummary season={season} />

            {validationOverviewResult.error || !validationOverviewResult.data ? (
              <ErrorBox
                message={`validation overview를 불러오지 못했습니다. ${
                  validationOverviewResult.error ?? "알 수 없는 오류입니다."
                }`}
              />
            ) : (
              <>
                <SeasonValidationOverviewPanel
                  overview={validationOverviewResult.data}
                />
                <ValidationIssuesPanel
                  issues={validationOverviewResult.data.validation_issues}
                />
              </>
            )}

            <section className={styles.panel}>
              <div className={styles.panelTitle}>
                <h2>Snapshots</h2>
                <span className={styles.muted}>
                  수집 상태와 row 수를 빠르게 확인합니다.
                </span>
              </div>
              <form className={styles.controls}>
                <div className={styles.controlRow}>
                  <div className={styles.field}>
                    <label htmlFor="status">Status</label>
                    <select
                      id="status"
                      name="status"
                      defaultValue={selectedStatus}
                    >
                      <option value="all">all</option>
                      <option value="completed">completed</option>
                      <option value="collecting">collecting</option>
                      <option value="failed">failed</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="source">Source</label>
                    <select
                      id="source"
                      name="source"
                      defaultValue={selectedSource}
                    >
                      <option value="all">all</option>
                      {sourceOptions.map((sourceType) => (
                        <option key={sourceType} value={sourceType}>
                          {sourceType}
                        </option>
                      ))}
                    </select>
                  </div>
                  <input type="hidden" name="rank" value={String(seriesRank)} />
                  <button type="submit" className={styles.button}>
                    적용
                  </button>
                </div>
              </form>
              {snapshotsResult.error ? (
                <ErrorBox
                  message={`snapshot 목록을 불러오지 못했습니다. ${snapshotsResult.error}`}
                />
              ) : filteredSnapshots.length > 0 ? (
                <SnapshotList snapshots={filteredSnapshots} />
              ) : (
                <EmptyBox message="조건에 맞는 snapshot이 없습니다." />
              )}
            </section>
          </div>

          <div className={styles.grid}>
            <section className={styles.panel}>
              <div className={styles.panelTitle}>
                <h2>Cutoff Series 설정</h2>
              </div>
              <form className={styles.controls}>
                <div className={styles.controlRow}>
                  <div className={styles.field}>
                    <label htmlFor="rank">Rank</label>
                    <select id="rank" name="rank" defaultValue={String(seriesRank)}>
                      {SERIES_RANK_OPTIONS.map((rank) => (
                        <option key={rank} value={rank}>
                          {rank.toLocaleString()}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button type="submit" className={styles.button}>
                    갱신
                  </button>
                </div>
              </form>
              <p className={styles.muted}>
                completed 상태의 snapshot만 시계열에 포함됩니다.
              </p>
            </section>

            {seriesResult.error ? (
              <ErrorBox
                message={`cutoff-series를 불러오지 못했습니다. ${seriesResult.error}`}
              />
            ) : seriesResult.data ? (
              <CutoffSeriesPanel series={seriesResult.data} />
            ) : (
              <EmptyBox message="cutoff-series를 표시할 데이터가 없습니다." />
            )}

            <section className={styles.panel}>
              <div className={styles.panelTitle}>
                <h2>빠른 이동</h2>
              </div>
              <p className={styles.muted}>
                snapshot 카드를 클릭하면 상세 통계와 entry 목록 화면으로 이동합니다.
              </p>
              <div className={styles.paginationLinks}>
                <Link href="/" className={styles.linkButton}>
                  시즌 목록
                </Link>
              </div>
            </section>
          </div>
        </div>
      )}
    </PageShell>
  );
}
