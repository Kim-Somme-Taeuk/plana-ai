import Link from "next/link";

import styles from "../../dashboard.module.css";
import {
  CutoffSeriesPanel,
  EmptyBox,
  ErrorBox,
  PageShell,
  SeasonSummary,
  SnapshotList,
} from "../../components/dashboard";
import {
  getSeason,
  getSeasonCutoffSeries,
  getSeasonSnapshots,
} from "../../lib/api";

export const dynamic = "force-dynamic";

type SeasonPageProps = {
  params: Promise<{ seasonId: string }>;
  searchParams: Promise<{ rank?: string }>;
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

  const [seasonResult, snapshotsResult, seriesResult] = await Promise.all([
    getSeason(numericSeasonId),
    getSeasonSnapshots(numericSeasonId),
    getSeasonCutoffSeries(numericSeasonId, Number.isNaN(seriesRank) ? 10 : seriesRank),
  ]);

  const season = seasonResult.data;

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

            <section className={styles.panel}>
              <div className={styles.panelTitle}>
                <h2>Snapshots</h2>
                <span className={styles.muted}>
                  수집 상태와 row 수를 빠르게 확인합니다.
                </span>
              </div>
              {snapshotsResult.error ? (
                <ErrorBox
                  message={`snapshot 목록을 불러오지 못했습니다. ${snapshotsResult.error}`}
                />
              ) : snapshotsResult.data && snapshotsResult.data.length > 0 ? (
                <SnapshotList snapshots={snapshotsResult.data} />
              ) : (
                <EmptyBox message="이 시즌에는 snapshot이 아직 없습니다." />
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
