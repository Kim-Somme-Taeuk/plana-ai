import Link from "next/link";

import styles from "../public.module.css";
import type {
  RankingSnapshot,
  RankingSnapshotCutoff,
  RankingSnapshotDistribution,
  RankingSnapshotSummary,
  Season,
  SeasonCutoffSeries,
} from "../lib/types";

export function PublicShell({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.headerTop}>
            <div className={styles.brandBlock}>
              <span className={styles.eyebrow}>{eyebrow}</span>
              <h1 className={styles.title}>{title}</h1>
            </div>
            <div className={styles.headerActions}>
              <Link href="/" className={styles.ghostButton}>
                홈
              </Link>
            </div>
          </div>
          <p className={styles.subtitle}>{subtitle}</p>
        </header>
        {children}
      </div>
    </main>
  );
}

export function PublicErrorBox({ message }: { message: string }) {
  return <div className={styles.errorBox}>{message}</div>;
}

export function PublicEmptyBox({ message }: { message: string }) {
  return <div className={styles.emptyBox}>{message}</div>;
}

export function FeaturedSeasonPanel({
  season,
  latestSnapshot,
  summary,
}: {
  season: Season;
  latestSnapshot: RankingSnapshot | null;
  summary: RankingSnapshotSummary | null;
}) {
  return (
    <section className={styles.heroSection}>
      <div className={styles.heroCard}>
        <div className={styles.heroHeader}>
          <div>
            <span className={styles.heroLabel}>지금 보기 좋은 시즌</span>
            <h2 className={styles.heroTitle}>{season.season_label}</h2>
          </div>
          <Link href={`/rankings/${season.id}`} className={styles.primaryButton}>
            시즌 보기
          </Link>
        </div>
        <div className={styles.heroMeta}>
          <PublicMetaItem label="이벤트" value={formatEventType(season.event_type)} />
          <PublicMetaItem label="서버" value={season.server} />
          <PublicMetaItem label="보스" value={season.boss_name} />
          <PublicMetaItem label="지형" value={season.terrain} />
          <PublicMetaItem label="방어 타입" value={season.armor_type ?? "-"} />
        </div>
      </div>
      <div className={styles.heroSideGrid}>
        <PublicStatCard
          label="최근 완료 스냅샷"
          value={latestSnapshot ? `#${latestSnapshot.id}` : "-"}
          description={
            latestSnapshot ? formatDate(latestSnapshot.captured_at) : "완료된 스냅샷이 없습니다."
          }
        />
        <PublicStatCard
          label="유효 엔트리"
          value={summary ? summary.valid_entry_count.toLocaleString() : "-"}
          description="최근 완료 스냅샷 기준"
        />
        <PublicStatCard
          label="최고 점수"
          value={summary ? formatNumber(summary.highest_score) : "-"}
          description="유효 엔트리 기준"
        />
        <PublicStatCard
          label="최저 점수"
          value={summary ? formatNumber(summary.lowest_score) : "-"}
          description="유효 엔트리 기준"
        />
      </div>
    </section>
  );
}

export function PublicCutoffHighlightPanel({
  seasonId,
  snapshot,
  summary,
  cutoffs,
}: {
  seasonId: number;
  snapshot: RankingSnapshot;
  summary: RankingSnapshotSummary;
  cutoffs: RankingSnapshotCutoff[];
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionEyebrow}>최근 완료 스냅샷</span>
          <h2>대표 컷오프</h2>
        </div>
        <div className={styles.sectionActions}>
          <Link href={`/rankings/${seasonId}`} className={styles.ghostButton}>
            시즌 상세
          </Link>
          <Link href={`/snapshots/${snapshot.id}`} className={styles.ghostButton}>
            관리용 상세
          </Link>
        </div>
      </div>
      <div className={styles.cutoffLeadCard}>
        <div className={styles.cutoffLeadRow}>
          <span>스냅샷</span>
          <strong>#{snapshot.id}</strong>
        </div>
        <div className={styles.cutoffLeadRow}>
          <span>수집 시각</span>
          <strong>{formatDate(snapshot.captured_at)}</strong>
        </div>
        <div className={styles.cutoffLeadRow}>
          <span>유효 엔트리</span>
          <strong>{summary.valid_entry_count.toLocaleString()}</strong>
        </div>
      </div>
      <div className={styles.cutoffGrid}>
        {cutoffs.map((cutoff) => (
          <article key={cutoff.rank} className={styles.cutoffCard}>
            <span className={styles.cutoffRank}>#{cutoff.rank.toLocaleString()}</span>
            <strong className={styles.cutoffScore}>{formatNumber(cutoff.score)}</strong>
          </article>
        ))}
      </div>
    </section>
  );
}

export function PublicTrendPanel({
  title,
  description,
  series,
}: {
  title: string;
  description: string;
  series: SeasonCutoffSeries;
}) {
  const validPoints = series.points.filter((point) => point.score !== null);
  const maxScore =
    validPoints.length > 0
      ? Math.max(...validPoints.map((point) => point.score ?? 0))
      : 0;

  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionEyebrow}>시계열</span>
          <h2>{title}</h2>
        </div>
        <p className={styles.sectionDescription}>{description}</p>
      </div>
      {series.points.length === 0 ? (
        <PublicEmptyBox message="시계열 데이터가 아직 없습니다." />
      ) : (
        <>
          <div className={styles.trendChart}>
            {series.points.map((point) => {
              const height =
                point.score !== null && maxScore > 0
                  ? Math.max(16, Math.round((point.score / maxScore) * 140))
                  : 14;
              return (
                <div key={point.snapshot_id} className={styles.trendBar}>
                  <div className={styles.trendTrack}>
                    <div
                      className={
                        point.score === null
                          ? `${styles.trendFill} ${styles.trendFillMuted}`
                          : styles.trendFill
                      }
                      style={{ height }}
                    />
                  </div>
                  <div className={styles.trendMeta}>
                    <span>#{point.snapshot_id}</span>
                    <strong>{point.score !== null ? formatCompactNumber(point.score) : "-"}</strong>
                  </div>
                </div>
              );
            })}
          </div>
          <div className={styles.publicTableWrap}>
            <table className={styles.publicTable}>
              <thead>
                <tr>
                  <th>스냅샷</th>
                  <th>수집 시각</th>
                  <th>점수</th>
                </tr>
              </thead>
              <tbody>
                {series.points.map((point) => (
                  <tr key={point.snapshot_id}>
                    <td>#{point.snapshot_id}</td>
                    <td>{formatDate(point.captured_at)}</td>
                    <td>{formatNumber(point.score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function PublicDistributionPanel({
  distribution,
}: {
  distribution: RankingSnapshotDistribution;
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionEyebrow}>분포 요약</span>
          <h2>최근 완료 스냅샷 분포</h2>
        </div>
        <p className={styles.sectionDescription}>유효 엔트리만 기준으로 계산한 요약입니다.</p>
      </div>
      <div className={styles.statGrid}>
        <PublicStatCard label="엔트리 수" value={distribution.count.toLocaleString()} />
        <PublicStatCard label="최저 점수" value={formatNumber(distribution.min_score)} />
        <PublicStatCard label="최고 점수" value={formatNumber(distribution.max_score)} />
        <PublicStatCard label="평균 점수" value={formatNumber(distribution.avg_score)} />
        <PublicStatCard label="중앙값" value={formatNumber(distribution.median_score)} />
      </div>
    </section>
  );
}

export function PublicSeasonGrid({ seasons }: { seasons: Season[] }) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionEyebrow}>전체 시즌</span>
          <h2>시즌 둘러보기</h2>
        </div>
        <p className={styles.sectionDescription}>
          시즌별 상세 화면에서 최신 컷오프와 시계열을 바로 확인할 수 있습니다.
        </p>
      </div>
      <div className={styles.seasonGrid}>
        {seasons.map((season) => (
          <Link key={season.id} href={`/rankings/${season.id}`} className={styles.seasonCard}>
            <div className={styles.seasonCardTop}>
              <span className={styles.cardBadge}>{formatEventType(season.event_type)}</span>
              <span className={styles.cardMeta}>#{season.id}</span>
            </div>
            <strong className={styles.seasonCardTitle}>{season.season_label}</strong>
            <div className={styles.seasonCardMeta}>
              <span>{season.server}</span>
              <span>{season.boss_name}</span>
              <span>{season.terrain}</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function PublicRecentSnapshotPanel({
  snapshots,
}: {
  snapshots: RankingSnapshot[];
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <span className={styles.sectionEyebrow}>최근 스냅샷</span>
          <h2>완료된 수집 시점</h2>
        </div>
        <p className={styles.sectionDescription}>
          최신 완료 스냅샷 기준으로 시점별 흐름을 빠르게 확인합니다.
        </p>
      </div>
      {snapshots.length === 0 ? (
        <PublicEmptyBox message="완료된 스냅샷이 아직 없습니다." />
      ) : (
        <div className={styles.snapshotGrid}>
          {snapshots.map((snapshot) => (
            <article key={snapshot.id} className={styles.snapshotCard}>
              <div className={styles.snapshotCardTop}>
                <span className={styles.cardBadge}>#{snapshot.id}</span>
                <span className={styles.cardMeta}>{formatSourceType(snapshot.source_type)}</span>
              </div>
              <strong>{formatDate(snapshot.captured_at)}</strong>
              <span className={styles.snapshotCardMeta}>
                수집 행 수{" "}
                {snapshot.total_rows_collected !== null
                  ? snapshot.total_rows_collected.toLocaleString()
                  : "-"}
              </span>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function PublicMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metaItem}>
      <span className={styles.metaLabel}>{label}</span>
      <strong className={styles.metaValue}>{value}</strong>
    </div>
  );
}

function PublicStatCard({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description?: string;
}) {
  return (
    <article className={styles.statCard}>
      <span className={styles.statLabel}>{label}</span>
      <strong className={styles.statValue}>{value}</strong>
      {description ? <span className={styles.statDescription}>{description}</span> : null}
    </article>
  );
}

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatNumber(value: number | null) {
  return value !== null ? value.toLocaleString() : "-";
}

function formatCompactNumber(value: number | null) {
  return value !== null
    ? new Intl.NumberFormat("ko-KR", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value)
    : "-";
}

function formatEventType(value: string) {
  switch (value) {
    case "grand_assault":
      return "대결전";
    case "total_assault":
      return "총력전";
    default:
      return value;
  }
}

function formatSourceType(value: string) {
  switch (value) {
    case "image_tesseract":
      return "이미지 OCR";
    case "image_sidecar":
      return "이미지 사이드카";
    case "mock_json":
      return "목 JSON";
    default:
      return value;
  }
}
