import Link from "next/link";

import styles from "../dashboard.module.css";
import type {
  RankingEntry,
  RankingSnapshot,
  RankingSnapshotCutoffs,
  RankingSnapshotDistribution,
  RankingSnapshotSummary,
  Season,
  SeasonCutoffSeries,
} from "../lib/types";

export function PageShell({
  eyebrow,
  title,
  subtitle,
  backHref,
  backLabel,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  backHref?: string;
  backLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          {backHref && backLabel ? (
            <Link href={backHref} className={styles.backLink}>
              ← {backLabel}
            </Link>
          ) : null}
          <span className={styles.eyebrow}>{eyebrow}</span>
          <div className={styles.titleRow}>
            <div>
              <h1 className={styles.title}>{title}</h1>
              <p className={styles.subtitle}>{subtitle}</p>
            </div>
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className={styles.errorBox}>{message}</div>;
}

export function EmptyBox({ message }: { message: string }) {
  return <div className={styles.emptyBox}>{message}</div>;
}

export function LoadingBox({ message }: { message: string }) {
  return <div className={styles.loadingBox}>{message}</div>;
}

export function StatusBadge({ status }: { status: string }) {
  const className =
    status === "completed"
      ? styles.statusCompleted
      : status === "failed"
        ? styles.statusFailed
        : styles.statusCollecting;

  return (
    <span className={`${styles.statusBadge} ${className}`}>{status}</span>
  );
}

export function SeasonList({ seasons }: { seasons: Season[] }) {
  return (
    <div className={styles.seasonList}>
      {seasons.map((season) => (
        <Link
          key={season.id}
          href={`/seasons/${season.id}`}
          className={styles.seasonCard}
        >
          <div className={styles.seasonCardTitle}>
            <strong>{season.season_label}</strong>
            <span className={styles.muted}>#{season.id}</span>
          </div>
          <div className={styles.metaGrid}>
            <MetaItem label="Event Type" value={season.event_type} />
            <MetaItem label="Server" value={season.server} />
            <MetaItem label="Boss" value={season.boss_name} />
            <MetaItem label="Armor" value={season.armor_type ?? "-"} />
            <MetaItem label="Terrain" value={season.terrain} />
          </div>
        </Link>
      ))}
    </div>
  );
}

export function SeasonSummary({ season }: { season: Season }) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>시즌 정보</h2>
      </div>
      <div className={styles.metaGrid}>
        <MetaItem label="Season Label" value={season.season_label} />
        <MetaItem label="Event Type" value={season.event_type} />
        <MetaItem label="Server" value={season.server} />
        <MetaItem label="Boss" value={season.boss_name} />
        <MetaItem label="Armor" value={season.armor_type ?? "-"} />
        <MetaItem label="Terrain" value={season.terrain} />
      </div>
    </section>
  );
}

export function SnapshotList({ snapshots }: { snapshots: RankingSnapshot[] }) {
  return (
    <div className={styles.snapshotList}>
      {snapshots.map((snapshot) => (
        <Link
          key={snapshot.id}
          href={`/snapshots/${snapshot.id}`}
          className={styles.snapshotCard}
        >
          <div className={styles.snapshotCardTop}>
            <span className={styles.snapshotLink}>Snapshot #{snapshot.id}</span>
            <StatusBadge status={snapshot.status} />
          </div>
          <div className={styles.metaGrid}>
            <MetaItem label="Captured At" value={formatDate(snapshot.captured_at)} />
            <MetaItem
              label="Rows"
              value={
                snapshot.total_rows_collected !== null
                  ? String(snapshot.total_rows_collected)
                  : "-"
              }
            />
            <MetaItem label="Note" value={snapshot.note ?? "-"} />
          </div>
        </Link>
      ))}
    </div>
  );
}

export function SummaryCards({
  summary,
  snapshot,
}: {
  summary: RankingSnapshotSummary;
  snapshot: RankingSnapshot;
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Snapshot Summary</h2>
        <StatusBadge status={summary.status} />
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="Snapshot ID" value={String(summary.snapshot_id)} />
        <StatCard label="Season ID" value={String(summary.season_id)} />
        <StatCard label="Captured At" value={formatDate(summary.captured_at)} />
        <StatCard
          label="Rows Collected"
          value={
            summary.total_rows_collected !== null
              ? String(summary.total_rows_collected)
              : "-"
          }
        />
        <StatCard label="Valid Entries" value={String(summary.valid_entry_count)} />
        <StatCard
          label="Invalid Entries"
          value={String(summary.invalid_entry_count)}
        />
        <StatCard
          label="Highest Score"
          value={formatNullableNumber(summary.highest_score)}
        />
        <StatCard
          label="Lowest Score"
          value={formatNullableNumber(summary.lowest_score)}
        />
        <StatCard label="Source Type" value={snapshot.source_type} />
        <StatCard label="Note" value={snapshot.note ?? "-"} />
      </div>
    </section>
  );
}

export function CutoffTable({
  cutoffs,
}: {
  cutoffs: RankingSnapshotCutoffs;
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Cutoffs</h2>
        <span className={styles.muted}>유효한 entry 기준</span>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {cutoffs.cutoffs.map((cutoff) => (
              <tr key={cutoff.rank}>
                <td>{cutoff.rank.toLocaleString()}</td>
                <td>{formatNullableNumber(cutoff.score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function DistributionPanel({
  distribution,
}: {
  distribution: RankingSnapshotDistribution;
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Distribution</h2>
        <span className={styles.muted}>유효한 entry 기준 요약</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="Count" value={String(distribution.count)} />
        <StatCard
          label="Min Score"
          value={formatNullableNumber(distribution.min_score)}
        />
        <StatCard
          label="Max Score"
          value={formatNullableNumber(distribution.max_score)}
        />
        <StatCard
          label="Average"
          value={formatNullableNumber(distribution.avg_score)}
        />
        <StatCard
          label="Median"
          value={formatNullableNumber(distribution.median_score)}
        />
      </div>
    </section>
  );
}

export function CutoffSeriesPanel({
  series,
}: {
  series: SeasonCutoffSeries;
}) {
  const maxScore =
    series.points.reduce((currentMax, point) => {
      if (point.score === null) {
        return currentMax;
      }
      return Math.max(currentMax, point.score);
    }, 0) || 1;

  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Rank {series.rank.toLocaleString()} Cutoff Series</h2>
        <span className={styles.muted}>completed snapshot 기준</span>
      </div>
      {series.points.length === 0 ? (
        <EmptyBox message="completed 상태의 snapshot이 아직 없습니다." />
      ) : (
        <>
          <div className={styles.seriesChart}>
            {series.points.map((point) => {
              const heightPercent = point.score
                ? Math.max((point.score / maxScore) * 100, 12)
                : 10;
              return (
                <div key={point.snapshot_id} className={styles.seriesBar}>
                  <div className={styles.seriesBarTrack}>
                    <div
                      className={`${styles.seriesBarFill} ${
                        point.score === null ? styles.seriesBarMuted : ""
                      }`}
                      style={{ height: `${heightPercent}%` }}
                    />
                  </div>
                  <span className={styles.seriesBarValue}>
                    {formatNullableNumber(point.score)}
                  </span>
                  <span className={styles.seriesBarLabel}>
                    {formatDate(point.captured_at)}
                  </span>
                </div>
              );
            })}
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Snapshot</th>
                  <th>Captured At</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {series.points.map((point) => (
                  <tr key={point.snapshot_id}>
                    <td>
                      <Link href={`/snapshots/${point.snapshot_id}`}>
                        #{point.snapshot_id}
                      </Link>
                    </td>
                    <td>{formatDate(point.captured_at)}</td>
                    <td>{formatNullableNumber(point.score)}</td>
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

export function SnapshotEntryTable({
  entries,
}: {
  entries: RankingEntry[];
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Score</th>
            <th>Player</th>
            <th>Valid</th>
            <th>OCR</th>
            <th>Issue</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>{entry.rank.toLocaleString()}</td>
              <td>{entry.score.toLocaleString()}</td>
              <td>{entry.player_name ?? "-"}</td>
              <td className={entry.is_valid ? styles.entryValid : styles.entryInvalid}>
                {entry.is_valid ? "valid" : "invalid"}
              </td>
              <td>
                {entry.ocr_confidence !== null
                  ? entry.ocr_confidence.toFixed(2)
                  : "-"}
              </td>
              <td>{entry.validation_issue ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.statCard}>
      <span className={styles.metaLabel}>{label}</span>
      <div className={styles.statValue}>{value}</div>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metaItem}>
      <span className={styles.metaLabel}>{label}</span>
      <span className={styles.metaValue}>{value}</span>
    </div>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatNullableNumber(value: number | null) {
  if (value === null) {
    return "-";
  }

  return value.toLocaleString();
}
