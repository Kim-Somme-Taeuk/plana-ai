import Link from "next/link";

import styles from "../dashboard.module.css";
import type {
  CollectorDiagnostics,
  RankingEntry,
  RankingSnapshot,
  RankingSnapshotCutoffs,
  RankingSnapshotDistribution,
  RankingSnapshotSummary,
  RankingSnapshotValidationIssueCount,
  RankingSnapshotValidationReport,
  Season,
  SeasonCutoffSeries,
  SeasonValidationSeries,
  SeasonValidationSeriesPoint,
  SeasonValidationOverview,
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

export function SnapshotList({
  snapshots,
  validationPoints,
}: {
  snapshots: RankingSnapshot[];
  validationPoints?: Map<number, SeasonValidationSeriesPoint>;
}) {
  return (
    <div className={styles.snapshotList}>
      {snapshots.map((snapshot) => {
        const validationPoint = validationPoints?.get(snapshot.id);
        return (
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
              <MetaItem label="Source" value={snapshot.source_type} />
              <MetaItem
                label="Rows"
                value={
                  snapshot.total_rows_collected !== null
                    ? String(snapshot.total_rows_collected)
                    : "-"
                }
              />
              <MetaItem
                label="Invalid Ratio"
                value={
                  validationPoint
                    ? formatPercent(validationPoint.invalid_ratio)
                    : "-"
                }
              />
              <MetaItem
                label="Top Issue"
                value={validationPoint?.top_validation_issue?.code ?? "-"}
              />
              <MetaItem
                label="Collector Stop"
                value={formatCollectorStop(validationPoint?.collector_diagnostics ?? null)}
              />
              <MetaItem
                label="Ignored OCR"
                value={formatCollectorIgnoredCount(validationPoint?.collector_diagnostics ?? null)}
              />
              <MetaItem label="Note" value={snapshot.note ?? "-"} />
            </div>
          </Link>
        );
      })}
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

export function SnapshotValidationReportPanel({
  report,
  seasonId,
}: {
  report: RankingSnapshotValidationReport;
  seasonId: number;
}) {
  const collectorSummary = formatCollectorDiagnosticsSummary(
    report.collector_diagnostics,
  );
  const collectorDiagnostics = report.collector_diagnostics;
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Validation Report</h2>
        <span className={styles.muted}>snapshot 정합성 보조 정보</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="Total Entries" value={String(report.total_entry_count)} />
        <StatCard label="Valid Entries" value={String(report.valid_entry_count)} />
        <StatCard
          label="Invalid Entries"
          value={String(report.invalid_entry_count)}
        />
        <StatCard
          label="Excluded From Stats"
          value={String(report.excluded_from_statistics_count)}
        />
        <StatCard
          label="Invalid Ratio"
          value={formatPercent(report.invalid_ratio)}
        />
        <StatCard
          label="Duplicate Ranks"
          value={String(report.duplicate_rank_count)}
        />
        <StatCard
          label="Rank Order"
          value={report.has_rank_order_violation ? "violation" : "normal"}
        />
        <StatCard
          label="Top Issue"
          value={report.top_validation_issue?.code ?? "-"}
        />
        <StatCard
          label="Collector Pages"
          value={
            report.collector_diagnostics
              ? formatCollectorPages(report.collector_diagnostics)
              : "-"
          }
        />
        <StatCard
          label="Collector Stop"
          value={collectorSummary.stop}
        />
        <StatCard
          label="Ignored OCR Lines"
          value={collectorSummary.ignored}
        />
        <StatCard
          label="Collector Raw"
          value={report.collector_diagnostics?.raw_summary ?? "-"}
        />
      </div>
      {collectorDiagnostics ? (
        <>
          <div className={styles.threeColumnGrid}>
            <div className={styles.subPanel}>
              <div className={styles.panelTitle}>
                <h3>Collector Stop Drilldown</h3>
              </div>
              <div className={styles.paginationLinks}>
                {collectorDiagnostics.capture_stop_reason ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=capture_stop&captureStopReason=${encodeURIComponent(
                      collectorDiagnostics.capture_stop_reason,
                    )}`}
                    className={styles.linkButton}
                  >
                    capture:{collectorDiagnostics.capture_stop_reason}
                  </Link>
                ) : null}
                {collectorDiagnostics.ocr_stop_reason ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=with_diagnostics&ocrStopReason=${encodeURIComponent(
                      collectorDiagnostics.ocr_stop_reason,
                    )}${
                      collectorDiagnostics.ocr_stop_level
                        ? `&ocrStopLevel=${encodeURIComponent(collectorDiagnostics.ocr_stop_level)}`
                        : ""
                    }`}
                    className={styles.linkButton}
                  >
                    ocr:{collectorDiagnostics.ocr_stop_reason}
                    {collectorDiagnostics.ocr_stop_level
                      ? ` (${collectorDiagnostics.ocr_stop_level})`
                      : ""}
                  </Link>
                ) : null}
                {!collectorDiagnostics.capture_stop_reason &&
                !collectorDiagnostics.ocr_stop_reason ? (
                  <span className={styles.muted}>collector stop signal이 없습니다.</span>
                ) : null}
              </div>
            </div>
            <ReasonSummaryPanel
              title="Ignored OCR Reason Drilldown"
              rows={collectorDiagnostics.ignored_reasons}
              emptyMessage="ignored OCR reason이 없습니다."
              getHref={(reason) =>
                `/seasons/${seasonId}?collector=with_diagnostics&ignoredReason=${encodeURIComponent(reason)}`
              }
            />
            <div className={styles.subPanel}>
              <div className={styles.panelTitle}>
                <h3>OCR Stop Recommendation</h3>
              </div>
              {collectorDiagnostics.ocr_stop_recommendation ? (
                <div className={styles.keyValueList}>
                  <div className={styles.keyValueRow}>
                    <span>Should Stop</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.should_stop
                        ? "yes"
                        : "no"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>Level</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.level ?? "-"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>Primary Reason</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.primary_reason ??
                        "-"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>Reasons</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.reasons.length > 0
                        ? collectorDiagnostics.ocr_stop_recommendation.reasons.join(
                            ", ",
                          )
                        : "-"}
                    </strong>
                  </div>
                </div>
              ) : (
                <EmptyBox message="저장된 OCR stop recommendation이 없습니다." />
              )}
            </div>
          </div>
          {collectorDiagnostics.page_summaries.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Page</th>
                    <th>Entries</th>
                    <th>Ignored OCR</th>
                    <th>Rank Range</th>
                    <th>New Ranks</th>
                    <th>Overlap</th>
                  </tr>
                </thead>
                <tbody>
                  {collectorDiagnostics.page_summaries.map((pageSummary) => (
                    <tr key={pageSummary.page_index}>
                      <td>#{pageSummary.page_index}</td>
                      <td>{pageSummary.entry_count.toLocaleString()}</td>
                      <td>
                        {pageSummary.ignored_line_count.toLocaleString()}
                        {pageSummary.ignored_line_reasons.length > 0
                          ? ` (${pageSummary.ignored_line_reasons
                              .map((row) => `${row.reason}=${row.count}`)
                              .join(", ")})`
                          : ""}
                      </td>
                      <td>
                        {formatRankRange(
                          pageSummary.first_rank,
                          pageSummary.last_rank,
                        )}
                      </td>
                      <td>
                        {pageSummary.new_rank_count.toLocaleString()} (
                        {formatPercent(pageSummary.new_rank_ratio)})
                      </td>
                      <td>
                        {pageSummary.overlap_with_previous_count.toLocaleString()} (
                        {formatPercent(pageSummary.overlap_with_previous_ratio)})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

export function ValidationIssuesPanel({
  issues,
  snapshotId,
}: {
  issues: RankingSnapshotValidationIssueCount[];
  snapshotId?: number;
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Validation Issues</h2>
        <span className={styles.muted}>invalid entry 사유 집계</span>
      </div>
      {issues.length === 0 ? (
        <EmptyBox message="현재 집계된 validation issue가 없습니다." />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Issue Code</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr key={issue.code}>
                  <td>
                    {snapshotId ? (
                      <Link
                        href={`/snapshots/${snapshotId}?validationIssue=${encodeURIComponent(issue.code)}&isValid=false`}
                        className={styles.issueCodeLink}
                      >
                        <span className={styles.issueCode}>{issue.code}</span>
                      </Link>
                    ) : (
                      <span className={styles.issueCode}>{issue.code}</span>
                    )}
                  </td>
                  <td>{issue.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function SeasonValidationOverviewPanel({
  overview,
  seasonId,
  selectedStatus,
  selectedSource,
  selectedCollector,
  selectedCaptureStopReason,
  selectedOcrStopReason,
  selectedIgnoredReason,
  selectedOcrStopLevel,
}: {
  overview: SeasonValidationOverview;
  seasonId: number;
  selectedStatus?: string;
  selectedSource?: string;
  selectedCollector?: string;
  selectedCaptureStopReason?: string;
  selectedOcrStopReason?: string;
  selectedIgnoredReason?: string;
  selectedOcrStopLevel?: string;
}) {
  const buildSeasonReasonHref = (
    reasonType: "capture" | "ocr" | "ignored",
    reason: string,
  ) => {
    const params = new URLSearchParams();

    if (selectedStatus && selectedStatus !== "all") {
      params.set("status", selectedStatus);
    }
    if (selectedSource && selectedSource !== "all") {
      params.set("source", selectedSource);
    }

    if (reasonType === "capture") {
      params.set("collector", "capture_stop");
      params.set("captureStopReason", reason);
      if (selectedOcrStopReason && selectedOcrStopReason !== "all") {
        params.set("ocrStopReason", selectedOcrStopReason);
      }
      if (selectedIgnoredReason && selectedIgnoredReason !== "all") {
        params.set("ignoredReason", selectedIgnoredReason);
      }
      if (selectedOcrStopLevel && selectedOcrStopLevel !== "all") {
        params.set("ocrStopLevel", selectedOcrStopLevel);
      }
    } else if (reasonType === "ocr") {
      params.set(
        "collector",
        selectedCollector && selectedCollector !== "all"
          ? selectedCollector
          : "with_diagnostics",
      );
      params.set("ocrStopReason", reason);
      if (selectedCaptureStopReason && selectedCaptureStopReason !== "all") {
        params.set("captureStopReason", selectedCaptureStopReason);
      }
      if (selectedIgnoredReason && selectedIgnoredReason !== "all") {
        params.set("ignoredReason", selectedIgnoredReason);
      }
      if (selectedOcrStopLevel && selectedOcrStopLevel !== "all") {
        params.set("ocrStopLevel", selectedOcrStopLevel);
      }
    } else {
      params.set(
        "collector",
        selectedCollector && selectedCollector !== "all"
          ? selectedCollector
          : "with_diagnostics",
      );
      params.set("ignoredReason", reason);
      if (selectedCaptureStopReason && selectedCaptureStopReason !== "all") {
        params.set("captureStopReason", selectedCaptureStopReason);
      }
      if (selectedOcrStopReason && selectedOcrStopReason !== "all") {
        params.set("ocrStopReason", selectedOcrStopReason);
      }
      if (selectedOcrStopLevel && selectedOcrStopLevel !== "all") {
        params.set("ocrStopLevel", selectedOcrStopLevel);
      }
    }

    const query = params.toString();
    return `/seasons/${seasonId}${query ? `?${query}` : ""}`;
  };

  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Season Validation Overview</h2>
        <span className={styles.muted}>시즌 전체 품질 요약</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="Snapshots" value={String(overview.snapshot_count)} />
        <StatCard
          label="Completed"
          value={String(overview.completed_snapshot_count)}
        />
        <StatCard
          label="Collecting"
          value={String(overview.collecting_snapshot_count)}
        />
        <StatCard label="Failed" value={String(overview.failed_snapshot_count)} />
        <StatCard label="Entries" value={String(overview.total_entry_count)} />
        <StatCard label="Valid" value={String(overview.valid_entry_count)} />
        <StatCard label="Invalid" value={String(overview.invalid_entry_count)} />
        <StatCard
          label="Excluded From Stats"
          value={String(overview.excluded_from_statistics_count)}
        />
        <StatCard
          label="Invalid Ratio"
          value={formatPercent(overview.invalid_ratio)}
        />
        <StatCard
          label="Top Issue"
          value={overview.top_validation_issue?.code ?? "-"}
        />
        <StatCard
          label="Collector Snapshots"
          value={String(overview.snapshots_with_collector_diagnostics_count)}
        />
        <StatCard
          label="Capture Stops"
          value={String(overview.snapshots_with_capture_stop_count)}
        />
        <StatCard
          label="Hard OCR Stops"
          value={String(overview.snapshots_with_hard_ocr_stop_count)}
        />
        <StatCard
          label="Ignored OCR Lines"
          value={String(overview.total_ignored_line_count)}
        />
      </div>
      <div className={styles.threeColumnGrid}>
        <ReasonSummaryPanel
          title="Capture Stop Reasons"
          rows={overview.capture_stop_reasons}
          emptyMessage="집계된 capture stop reason이 없습니다."
          getHref={(reason) => buildSeasonReasonHref("capture", reason)}
        />
        <ReasonSummaryPanel
          title="OCR Stop Reasons"
          rows={overview.ocr_stop_reasons}
          emptyMessage="집계된 OCR stop reason이 없습니다."
          getHref={(reason) => buildSeasonReasonHref("ocr", reason)}
        />
        <ReasonSummaryPanel
          title="Ignored OCR Reasons"
          rows={overview.ignored_reasons}
          emptyMessage="집계된 ignored OCR reason이 없습니다."
          getHref={(reason) => buildSeasonReasonHref("ignored", reason)}
        />
      </div>
    </section>
  );
}

export function SeasonValidationSeriesPanel({
  series,
  selectedCompareLeftId,
  selectedCompareRightId,
  compareRank,
  collectorFilter,
  selectedStatus,
  selectedSource,
  captureStopReason,
  ocrStopReason,
  ignoredReason,
  ocrStopLevel,
}: {
  series: SeasonValidationSeries;
  selectedCompareLeftId?: number | null;
  selectedCompareRightId?: number | null;
  compareRank?: number;
  collectorFilter?: string;
  selectedStatus?: string;
  selectedSource?: string;
  captureStopReason?: string;
  ocrStopReason?: string;
  ignoredReason?: string;
  ocrStopLevel?: string;
}) {
  const maxInvalidRatio =
    series.points.reduce((currentMax, point) => {
      return Math.max(currentMax, point.invalid_ratio);
    }, 0) || 1;

  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Validation Series</h2>
        <span className={styles.muted}>snapshot별 invalid 비율과 주요 issue</span>
      </div>
      {series.points.length === 0 ? (
        <EmptyBox message="validation series를 표시할 snapshot이 없습니다." />
      ) : (
        <>
          <div className={styles.seriesChart}>
            {series.points.map((point) => {
              const heightPercent =
                point.invalid_ratio > 0
                  ? Math.max((point.invalid_ratio / maxInvalidRatio) * 100, 12)
                  : 10;
              return (
                <div key={point.snapshot_id} className={styles.seriesBar}>
                  <div className={styles.seriesBarTrack}>
                    <div
                      className={`${styles.seriesBarFill} ${
                        point.invalid_ratio === 0 ? styles.seriesBarMuted : ""
                      }`}
                      style={{ height: `${heightPercent}%` }}
                    />
                  </div>
                  <span className={styles.seriesBarValue}>
                    {formatPercent(point.invalid_ratio)}
                  </span>
                  <span className={styles.seriesBarLabel}>
                    #{point.snapshot_id}
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
                  <th>Status</th>
                  <th>Captured At</th>
                  <th>Invalid Ratio</th>
                  <th>Invalid Entries</th>
                  <th>Top Issue</th>
                  <th>Collector Stop</th>
                  <th>Ignored OCR</th>
                  <th>Compare</th>
                </tr>
              </thead>
              <tbody>
                {series.points.map((point, index) => {
                  const previousPoint = index > 0 ? series.points[index - 1] : null;
                  const isCurrentCompare =
                    selectedCompareLeftId === previousPoint?.snapshot_id &&
                    selectedCompareRightId === point.snapshot_id;

                  return (
                    <tr key={point.snapshot_id}>
                      <td>
                        <Link href={`/snapshots/${point.snapshot_id}`}>
                          #{point.snapshot_id}
                        </Link>
                      </td>
                      <td>
                        <StatusBadge status={point.status} />
                      </td>
                      <td>{formatDate(point.captured_at)}</td>
                      <td>{formatPercent(point.invalid_ratio)}</td>
                      <td>
                        {point.invalid_entry_count > 0 ? (
                          <Link
                            href={`/snapshots/${point.snapshot_id}?isValid=false`}
                            className={styles.linkButton}
                          >
                            {point.invalid_entry_count.toLocaleString()}
                          </Link>
                        ) : (
                          "0"
                        )}
                      </td>
                      <td>
                        {point.top_validation_issue ? (
                          <Link
                            href={`/snapshots/${point.snapshot_id}?validationIssue=${encodeURIComponent(
                              point.top_validation_issue.code,
                            )}&isValid=false`}
                            className={styles.issueCodeLink}
                          >
                            <span className={styles.issueCode}>
                              {point.top_validation_issue.code}
                            </span>
                          </Link>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>{formatCollectorStop(point.collector_diagnostics)}</td>
                      <td>
                        {point.collector_diagnostics
                          ? point.collector_diagnostics.ignored_line_count.toLocaleString()
                          : "-"}
                      </td>
                      <td>
                        <div className={styles.compareTableActions}>
                          {previousPoint ? (
                            <>
                              <Link
                                href={`/seasons/${series.season_id}?compareLeft=${previousPoint.snapshot_id}&compareRight=${point.snapshot_id}${
                                  compareRank ? `&rank=${compareRank}` : ""
                                }${
                                  selectedStatus && selectedStatus !== "all"
                                    ? `&status=${selectedStatus}`
                                    : ""
                                }${
                                  selectedSource && selectedSource !== "all"
                                    ? `&source=${encodeURIComponent(selectedSource)}`
                                    : ""
                                }${
                                  collectorFilter && collectorFilter !== "all"
                                    ? `&collector=${collectorFilter}`
                                    : ""
                                }${
                                  captureStopReason && captureStopReason !== "all"
                                    ? `&captureStopReason=${encodeURIComponent(captureStopReason)}`
                                    : ""
                                }${
                                  ocrStopReason && ocrStopReason !== "all"
                                    ? `&ocrStopReason=${encodeURIComponent(ocrStopReason)}`
                                    : ""
                                }${
                                  ignoredReason && ignoredReason !== "all"
                                    ? `&ignoredReason=${encodeURIComponent(ignoredReason)}`
                                    : ""
                                }${
                                  ocrStopLevel && ocrStopLevel !== "all"
                                    ? `&ocrStopLevel=${encodeURIComponent(ocrStopLevel)}`
                                    : ""
                                }`}
                                className={styles.linkButton}
                              >
                                이전과 비교
                              </Link>
                              {isCurrentCompare ? (
                                <span className={styles.inlineChip}>현재 비교</span>
                              ) : null}
                            </>
                          ) : (
                            <span className={styles.muted}>-</span>
                          )}
                          <Link
                            href={`/snapshots/${point.snapshot_id}`}
                            className={styles.linkButton}
                          >
                            상세
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function SnapshotComparisonPanel({
  leftSnapshot,
  rightSnapshot,
  leftSummary,
  rightSummary,
  leftCutoffs,
  rightCutoffs,
  leftDistribution,
  rightDistribution,
  leftValidationReport,
  rightValidationReport,
}: {
  leftSnapshot: RankingSnapshot;
  rightSnapshot: RankingSnapshot;
  leftSummary: RankingSnapshotSummary;
  rightSummary: RankingSnapshotSummary;
  leftCutoffs: RankingSnapshotCutoffs;
  rightCutoffs: RankingSnapshotCutoffs;
  leftDistribution: RankingSnapshotDistribution;
  rightDistribution: RankingSnapshotDistribution;
  leftValidationReport: RankingSnapshotValidationReport;
  rightValidationReport: RankingSnapshotValidationReport;
}) {
  const leftCutoffMap = new Map(
    leftCutoffs.cutoffs.map((cutoff) => [cutoff.rank, cutoff.score]),
  );
  const rightCutoffMap = new Map(
    rightCutoffs.cutoffs.map((cutoff) => [cutoff.rank, cutoff.score]),
  );
  const leftIssueMap = new Map(
    leftSummary.validation_issues.map((issue) => [issue.code, issue.count]),
  );
  const rightIssueMap = new Map(
    rightSummary.validation_issues.map((issue) => [issue.code, issue.count]),
  );
  const cutoffRanks = Array.from(
    new Set([...leftCutoffMap.keys(), ...rightCutoffMap.keys()]),
  ).sort((left, right) => left - right);
  const issueCodes = Array.from(
    new Set([...leftIssueMap.keys(), ...rightIssueMap.keys()]),
  ).sort();
  const leftTopIssue = getTopValidationIssue(leftSummary.validation_issues);
  const rightTopIssue = getTopValidationIssue(rightSummary.validation_issues);
  const leftCollectorDiagnostics = leftValidationReport.collector_diagnostics;
  const rightCollectorDiagnostics = rightValidationReport.collector_diagnostics;

  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>Snapshot Compare</h2>
        <span className={styles.muted}>두 snapshot의 품질과 점수 차이를 나란히 봅니다.</span>
      </div>

      <div className={styles.compareHeaderGrid}>
        <SnapshotCompareHeader snapshot={leftSnapshot} sideLabel="Left" />
        <SnapshotCompareHeader snapshot={rightSnapshot} sideLabel="Right" />
      </div>

      <div className={styles.compareActions}>
        <Link href={`/snapshots/${leftSnapshot.id}`} className={styles.linkButton}>
          Left 상세
        </Link>
        <Link href={`/snapshots/${rightSnapshot.id}`} className={styles.linkButton}>
          Right 상세
        </Link>
        <Link
          href={`/snapshots/${leftSnapshot.id}?isValid=false`}
          className={styles.linkButton}
        >
          Left invalid
        </Link>
        <Link
          href={`/snapshots/${rightSnapshot.id}?isValid=false`}
          className={styles.linkButton}
        >
          Right invalid
        </Link>
        {leftTopIssue ? (
          <Link
            href={`/snapshots/${leftSnapshot.id}?validationIssue=${encodeURIComponent(
              leftTopIssue.code,
            )}&isValid=false`}
            className={styles.linkButton}
          >
            Left top issue
          </Link>
        ) : null}
        {rightTopIssue ? (
          <Link
            href={`/snapshots/${rightSnapshot.id}?validationIssue=${encodeURIComponent(
              rightTopIssue.code,
            )}&isValid=false`}
            className={styles.linkButton}
          >
            Right top issue
          </Link>
        ) : null}
      </div>

      <div className={styles.statsGrid}>
        <StatCard
          label="Left Issue Types"
          value={String(leftSummary.validation_issues.length)}
        />
        <StatCard
          label="Right Issue Types"
          value={String(rightSummary.validation_issues.length)}
        />
        <StatCard
          label="Left Top Issue"
          value={leftTopIssue?.code ?? "-"}
        />
        <StatCard
          label="Right Top Issue"
          value={rightTopIssue?.code ?? "-"}
        />
        <StatCard
          label="Left Invalid Ratio"
          value={formatPercent(calculateInvalidRatio(leftSummary))}
        />
        <StatCard
          label="Right Invalid Ratio"
          value={formatPercent(calculateInvalidRatio(rightSummary))}
        />
        <StatCard
          label="Left Collector Stop"
          value={formatCollectorStop(leftCollectorDiagnostics)}
        />
        <StatCard
          label="Right Collector Stop"
          value={formatCollectorStop(rightCollectorDiagnostics)}
        />
        <StatCard
          label="Left Ignored OCR"
          value={formatCollectorIgnoredCount(leftCollectorDiagnostics)}
        />
        <StatCard
          label="Right Ignored OCR"
          value={formatCollectorIgnoredCount(rightCollectorDiagnostics)}
        />
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Left</th>
              <th>Right</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            <CompareRow
              label="Rows Collected"
              leftValue={leftSummary.total_rows_collected}
              rightValue={rightSummary.total_rows_collected}
            />
            <CompareRow
              label="Valid Entries"
              leftValue={leftSummary.valid_entry_count}
              rightValue={rightSummary.valid_entry_count}
            />
            <CompareRow
              label="Invalid Entries"
              leftValue={leftSummary.invalid_entry_count}
              rightValue={rightSummary.invalid_entry_count}
            />
            <CompareRow
              label="Highest Score"
              leftValue={leftSummary.highest_score}
              rightValue={rightSummary.highest_score}
            />
            <CompareRow
              label="Lowest Score"
              leftValue={leftSummary.lowest_score}
              rightValue={rightSummary.lowest_score}
            />
            <CompareRow
              label="Average Score"
              leftValue={leftDistribution.avg_score}
              rightValue={rightDistribution.avg_score}
            />
            <CompareRow
              label="Median Score"
              leftValue={leftDistribution.median_score}
              rightValue={rightDistribution.median_score}
            />
            <CompareRow
              label="Ignored OCR Lines"
              leftValue={leftCollectorDiagnostics?.ignored_line_count ?? null}
              rightValue={rightCollectorDiagnostics?.ignored_line_count ?? null}
            />
            <CompareTextRow
              label="Collector Pages"
              leftValue={leftCollectorDiagnostics ? formatCollectorPages(leftCollectorDiagnostics) : "-"}
              rightValue={rightCollectorDiagnostics ? formatCollectorPages(rightCollectorDiagnostics) : "-"}
            />
            <CompareTextRow
              label="Collector Stop"
              leftValue={formatCollectorStop(leftCollectorDiagnostics)}
              rightValue={formatCollectorStop(rightCollectorDiagnostics)}
            />
          </tbody>
        </table>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Cutoff Rank</th>
              <th>Left</th>
              <th>Right</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {cutoffRanks.map((rank) => (
              <CompareRow
                key={rank}
                label={`#${rank.toLocaleString()}`}
                leftValue={leftCutoffMap.get(rank) ?? null}
                rightValue={rightCutoffMap.get(rank) ?? null}
              />
            ))}
          </tbody>
        </table>
      </div>

      {issueCodes.length === 0 ? (
        <EmptyBox message="두 snapshot 모두 집계된 validation issue가 없습니다." />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Validation Issue</th>
                <th>Left</th>
                <th>Right</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              {issueCodes.map((code) => (
                <tr key={code}>
                  <td>{code}</td>
                  <td>
                    {leftIssueMap.get(code) ? (
                      <Link
                        href={`/snapshots/${leftSnapshot.id}?validationIssue=${encodeURIComponent(code)}&isValid=false`}
                        className={styles.linkButton}
                      >
                        {formatNullableNumber(leftIssueMap.get(code) ?? 0)}
                      </Link>
                    ) : (
                      "0"
                    )}
                  </td>
                  <td>
                    {rightIssueMap.get(code) ? (
                      <Link
                        href={`/snapshots/${rightSnapshot.id}?validationIssue=${encodeURIComponent(code)}&isValid=false`}
                        className={styles.linkButton}
                      >
                        {formatNullableNumber(rightIssueMap.get(code) ?? 0)}
                      </Link>
                    ) : (
                      "0"
                    )}
                  </td>
                  <td>
                    {formatSignedNumber(
                      (rightIssueMap.get(code) ?? 0) - (leftIssueMap.get(code) ?? 0),
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function getValidationIssueOptions(
  issues: RankingSnapshotValidationIssueCount[],
  currentValue?: string,
) {
  const knownCodes = [
    "invalid_rank",
    "invalid_score",
    "missing_player_name",
    "low_ocr_confidence",
    "duplicate_rank",
    "rank_order_violation",
  ];
  const values = new Set<string>(knownCodes);

  for (const issue of issues) {
    if (issue.code.trim()) {
      values.add(issue.code);
    }
  }

  if (currentValue && currentValue !== "all" && currentValue.trim()) {
    values.add(currentValue);
  }

  return Array.from(values).map((value) => ({
    value,
    label: value,
  }));
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

function ReasonSummaryPanel({
  title,
  rows,
  emptyMessage,
  getHref,
}: {
  title: string;
  rows: Array<{ reason: string; count: number }>;
  emptyMessage: string;
  getHref?: (reason: string) => string;
}) {
  return (
    <div className={styles.subPanel}>
      <div className={styles.panelTitle}>
        <h3>{title}</h3>
      </div>
      {rows.length === 0 ? (
        <div className={styles.muted}>{emptyMessage}</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Reason</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.reason}>
                  <td>
                    {getHref ? (
                      <Link href={getHref(row.reason)} className={styles.issueCodeLink}>
                        <span className={styles.issueCode}>{row.reason}</span>
                      </Link>
                    ) : (
                      row.reason
                    )}
                  </td>
                  <td>{row.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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

function SnapshotCompareHeader({
  snapshot,
  sideLabel,
}: {
  snapshot: RankingSnapshot;
  sideLabel: string;
}) {
  return (
    <div className={styles.compareHeaderCard}>
      <div className={styles.panelTitle}>
        <h3>
          {sideLabel} #{snapshot.id}
        </h3>
        <StatusBadge status={snapshot.status} />
      </div>
      <div className={styles.metaGrid}>
        <MetaItem label="Captured At" value={formatDate(snapshot.captured_at)} />
        <MetaItem label="Source" value={snapshot.source_type} />
        <MetaItem label="Rows" value={formatNullableNumber(snapshot.total_rows_collected)} />
        <MetaItem label="Note" value={snapshot.note ?? "-"} />
      </div>
    </div>
  );
}

function CompareRow({
  label,
  leftValue,
  rightValue,
}: {
  label: string;
  leftValue: number | null;
  rightValue: number | null;
}) {
  const delta =
    leftValue === null || rightValue === null ? null : rightValue - leftValue;

  return (
    <tr>
      <td>{label}</td>
      <td>{formatNullableNumber(leftValue)}</td>
      <td>{formatNullableNumber(rightValue)}</td>
      <td>{formatSignedNumber(delta)}</td>
    </tr>
  );
}

function CompareTextRow({
  label,
  leftValue,
  rightValue,
}: {
  label: string;
  leftValue: string;
  rightValue: string;
}) {
  return (
    <tr>
      <td>{label}</td>
      <td>{leftValue}</td>
      <td>{rightValue}</td>
      <td>{leftValue === rightValue ? "same" : "-"}</td>
    </tr>
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

function formatSignedNumber(value: number | null) {
  if (value === null) {
    return "-";
  }

  if (value === 0) {
    return "0";
  }

  return `${value > 0 ? "+" : ""}${value.toLocaleString()}`;
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
    minimumFractionDigits: value === 0 ? 0 : 1,
  }).format(value);
}

function formatRankRange(firstRank: number | null, lastRank: number | null) {
  if (firstRank === null && lastRank === null) {
    return "-";
  }
  if (firstRank === lastRank) {
    return firstRank?.toLocaleString() ?? "-";
  }
  return `${firstRank?.toLocaleString() ?? "?"} - ${
    lastRank?.toLocaleString() ?? "?"
  }`;
}

function getTopValidationIssue(
  issues: RankingSnapshotValidationIssueCount[],
) {
  if (issues.length === 0) {
    return null;
  }

  return [...issues].sort((left, right) => right.count - left.count)[0];
}

function calculateInvalidRatio(summary: RankingSnapshotSummary) {
  const total =
    summary.valid_entry_count + summary.invalid_entry_count;
  if (total === 0) {
    return 0;
  }

  return summary.invalid_entry_count / total;
}

function formatCollectorPages(diagnostics: CollectorDiagnostics) {
  if (
    diagnostics.captured_page_count === null ||
    diagnostics.requested_page_count === null
  ) {
    return "-";
  }

  return `${diagnostics.captured_page_count}/${diagnostics.requested_page_count}`;
}

function formatCollectorStop(diagnostics: CollectorDiagnostics | null) {
  if (!diagnostics) {
    return "-";
  }

  if (diagnostics.capture_stop_reason) {
    return `capture:${diagnostics.capture_stop_reason}`;
  }

  if (diagnostics.ocr_stop_reason) {
    const level = diagnostics.ocr_stop_level
      ? `(${diagnostics.ocr_stop_level})`
      : "";
    return `ocr:${diagnostics.ocr_stop_reason}${level}`;
  }

  return "-";
}

function formatCollectorIgnoredCount(diagnostics: CollectorDiagnostics | null) {
  if (!diagnostics) {
    return "-";
  }

  return diagnostics.ignored_line_count.toLocaleString();
}

function formatCollectorDiagnosticsSummary(
  diagnostics: CollectorDiagnostics | null,
) {
  if (!diagnostics) {
    return {
      stop: "-",
      ignored: "-",
    };
  }

  const ignoredReasons =
    diagnostics.ignored_reasons.length > 0
      ? ` (${diagnostics.ignored_reasons
          .map((row) => `${row.reason}=${row.count}`)
          .join(", ")})`
      : "";

  return {
    stop: formatCollectorStop(diagnostics),
    ignored: `${diagnostics.ignored_line_count.toLocaleString()}${ignoredReasons}`,
  };
}
