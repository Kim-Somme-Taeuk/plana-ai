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
    <span className={`${styles.statusBadge} ${className}`}>
      {formatStatusText(status)}
    </span>
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
            <MetaItem label="이벤트 유형" value={formatEventType(season.event_type)} />
            <MetaItem label="서버" value={season.server} />
            <MetaItem label="보스" value={season.boss_name} />
            <MetaItem label="방어 타입" value={season.armor_type ?? "-"} />
            <MetaItem label="지형" value={season.terrain} />
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
        <MetaItem label="시즌 라벨" value={season.season_label} />
        <MetaItem label="이벤트 유형" value={formatEventType(season.event_type)} />
        <MetaItem label="서버" value={season.server} />
        <MetaItem label="보스" value={season.boss_name} />
        <MetaItem label="방어 타입" value={season.armor_type ?? "-"} />
        <MetaItem label="지형" value={season.terrain} />
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
              <MetaItem label="수집 시각" value={formatDate(snapshot.captured_at)} />
              <MetaItem label="입력 소스" value={formatSourceType(snapshot.source_type)} />
              <MetaItem
                label="행 수"
                value={
                  snapshot.total_rows_collected !== null
                    ? String(snapshot.total_rows_collected)
                    : "-"
                }
              />
              <MetaItem
                label="무효 비율"
                value={
                  validationPoint
                    ? formatPercent(validationPoint.invalid_ratio)
                    : "-"
                }
              />
              <MetaItem
                label="주요 이슈"
                value={validationPoint?.top_validation_issue?.code ?? "-"}
              />
              <MetaItem
                label="수집 중단"
                value={formatCollectorStop(validationPoint?.collector_diagnostics ?? null)}
              />
              <MetaItem
                label="무시된 OCR"
                value={formatCollectorIgnoredCount(validationPoint?.collector_diagnostics ?? null)}
              />
              <MetaItem label="메모" value={formatSnapshotNote(snapshot.note)} />
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
        <h2>스냅샷 요약</h2>
        <StatusBadge status={summary.status} />
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="스냅샷 ID" value={String(summary.snapshot_id)} />
        <StatCard label="시즌 ID" value={String(summary.season_id)} />
        <StatCard label="수집 시각" value={formatDate(summary.captured_at)} />
        <StatCard
          label="수집 행 수"
          value={
            summary.total_rows_collected !== null
              ? String(summary.total_rows_collected)
              : "-"
          }
        />
        <StatCard label="유효 엔트리" value={String(summary.valid_entry_count)} />
        <StatCard
          label="무효 엔트리"
          value={String(summary.invalid_entry_count)}
        />
        <StatCard
          label="최고 점수"
          value={formatNullableNumber(summary.highest_score)}
        />
        <StatCard
          label="최저 점수"
          value={formatNullableNumber(summary.lowest_score)}
        />
        <StatCard label="입력 소스" value={formatSourceType(snapshot.source_type)} />
        <StatCard label="메모" value={formatSnapshotNote(snapshot.note)} />
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
        <h2>컷오프</h2>
        <span className={styles.muted}>유효 엔트리 기준</span>
      </div>
      <div className={`${styles.tableWrap} ${styles.compareTableSection}`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>순위</th>
              <th>점수</th>
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
        <h2>분포 요약</h2>
        <span className={styles.muted}>유효 엔트리 기준 요약</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="개수" value={String(distribution.count)} />
        <StatCard
          label="최소 점수"
          value={formatNullableNumber(distribution.min_score)}
        />
        <StatCard
          label="최대 점수"
          value={formatNullableNumber(distribution.max_score)}
        />
        <StatCard
          label="평균"
          value={formatNullableNumber(distribution.avg_score)}
        />
        <StatCard
          label="중앙값"
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
        <h2>검증 리포트</h2>
        <span className={styles.muted}>snapshot 정합성 보조 정보</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="전체 엔트리" value={String(report.total_entry_count)} />
        <StatCard label="유효 엔트리" value={String(report.valid_entry_count)} />
        <StatCard
          label="무효 엔트리"
          value={String(report.invalid_entry_count)}
        />
        <StatCard
          label="통계 제외 수"
          value={String(report.excluded_from_statistics_count)}
        />
        <StatCard
          label="무효 비율"
          value={formatPercent(report.invalid_ratio)}
        />
        <StatCard
          label="중복 순위"
          value={String(report.duplicate_rank_count)}
        />
        <StatCard
          label="순위 정렬"
          value={report.has_rank_order_violation ? "이상" : "정상"}
        />
        <StatCard
          label="주요 이슈"
          value={report.top_validation_issue?.code ?? "-"}
        />
        <StatCard
          label="수집 페이지"
          value={
            report.collector_diagnostics
              ? formatCollectorPages(report.collector_diagnostics)
              : "-"
          }
        />
        <StatCard
          label="수집 중단"
          value={collectorSummary.stop}
        />
        <StatCard
          label="무시된 OCR 줄"
          value={collectorSummary.ignored}
        />
        <StatCard
          label="오버레이 OCR 줄"
          value={collectorDiagnostics?.overlay_ignored_line_count.toLocaleString() ?? "-"}
        />
        <StatCard
          label="헤더 OCR 줄"
          value={collectorDiagnostics?.header_ignored_line_count.toLocaleString() ?? "-"}
        />
        <StatCard
          label="비정상 엔트리 OCR"
          value={collectorDiagnostics?.malformed_entry_line_count.toLocaleString() ?? "-"}
        />
        <StatCard
          label="수집 요약 원문"
          value={report.collector_diagnostics?.raw_summary ?? "-"}
        />
      </div>
      {collectorDiagnostics ? (
        <>
          <div className={styles.threeColumnGrid}>
            <div className={styles.subPanel}>
              <div className={styles.panelTitle}>
                <h3>수집 중단 드릴다운</h3>
              </div>
              <div className={styles.paginationLinks}>
                {collectorDiagnostics.overlay_ignored_line_count > 0 ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=with_diagnostics&ignoredGroup=overlay`}
                    className={styles.linkButton}
                  >
                    오버레이 OCR
                  </Link>
                ) : null}
                {collectorDiagnostics.header_ignored_line_count > 0 ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=with_diagnostics&ignoredGroup=header`}
                    className={styles.linkButton}
                  >
                    헤더 OCR
                  </Link>
                ) : null}
                {collectorDiagnostics.malformed_entry_line_count > 0 ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=with_diagnostics&ignoredGroup=malformed`}
                    className={styles.linkButton}
                  >
                    비정상 엔트리 OCR
                  </Link>
                ) : null}
              </div>
              <div className={styles.paginationLinks}>
                {collectorDiagnostics.capture_stop_reason ? (
                  <Link
                    href={`/seasons/${seasonId}?collector=capture_stop&captureStopReason=${encodeURIComponent(
                      collectorDiagnostics.capture_stop_reason,
                    )}`}
                    className={styles.linkButton}
                  >
                    캡처:{collectorDiagnostics.capture_stop_reason}
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
                    OCR:{collectorDiagnostics.ocr_stop_reason}
                    {collectorDiagnostics.ocr_stop_level
                      ? ` (${collectorDiagnostics.ocr_stop_level})`
                      : ""}
                  </Link>
                ) : null}
                {!collectorDiagnostics.capture_stop_reason &&
                !collectorDiagnostics.ocr_stop_reason ? (
                  <span className={styles.muted}>수집 중단 신호가 없습니다.</span>
                ) : null}
              </div>
            </div>
            <ReasonSummaryPanel
              title="무시된 OCR 사유 드릴다운"
              rows={collectorDiagnostics.ignored_reasons}
              emptyMessage="무시된 OCR 사유가 없습니다."
              getHref={(reason) =>
                `/seasons/${seasonId}?collector=with_diagnostics&ignoredReason=${encodeURIComponent(reason)}`
              }
            />
            <div className={styles.subPanel}>
              <div className={styles.panelTitle}>
                <h3>OCR 중단 권장</h3>
              </div>
              {collectorDiagnostics.ocr_stop_recommendation ? (
                <div className={styles.keyValueList}>
                  <div className={styles.keyValueRow}>
                    <span>중단 권장</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.should_stop
                        ? "예"
                        : "아니오"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>레벨</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.level ?? "-"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>주요 사유</span>
                    <strong>
                      {collectorDiagnostics.ocr_stop_recommendation.primary_reason ??
                        "-"}
                    </strong>
                  </div>
                  <div className={styles.keyValueRow}>
                    <span>사유 목록</span>
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
                <EmptyBox message="저장된 OCR 중단 권장 정보가 없습니다." />
              )}
            </div>
            <div className={styles.subPanel}>
              <div className={styles.panelTitle}>
                <h3>페이지 품질 신호</h3>
              </div>
              <div className={styles.keyValueList}>
                <div className={styles.keyValueRow}>
                  <span>빈 페이지</span>
                  <strong>{collectorDiagnostics.empty_page_count.toLocaleString()}</strong>
                </div>
                <div className={styles.keyValueRow}>
                  <span>Sparse 페이지</span>
                  <strong>{collectorDiagnostics.sparse_page_count.toLocaleString()}</strong>
                </div>
                <div className={styles.keyValueRow}>
                  <span>중복 페이지</span>
                  <strong>{collectorDiagnostics.overlapping_page_count.toLocaleString()}</strong>
                </div>
                <div className={styles.keyValueRow}>
                  <span>Stale 페이지</span>
                  <strong>{collectorDiagnostics.stale_page_count.toLocaleString()}</strong>
                </div>
                <div className={styles.keyValueRow}>
                  <span>Noise 페이지</span>
                  <strong>{collectorDiagnostics.noisy_page_count.toLocaleString()}</strong>
                </div>
              </div>
            </div>
          </div>
          {collectorDiagnostics.page_summaries.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>페이지</th>
                    <th>엔트리</th>
                    <th>무시된 OCR</th>
                    <th>순위 범위</th>
                    <th>새 순위</th>
                    <th>중복 비율</th>
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
        <h2>검증 이슈</h2>
        <span className={styles.muted}>무효 엔트리 사유 집계</span>
      </div>
      {issues.length === 0 ? (
        <EmptyBox message="현재 집계된 검증 이슈가 없습니다." />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>이슈 코드</th>
                <th>개수</th>
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
  selectedIgnoredGroup,
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
  selectedIgnoredGroup?: string;
  selectedOcrStopLevel?: string;
}) {
  const buildSeasonReasonHref = (
    reasonType: "capture" | "ocr" | "ignored" | "ignored-group",
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
      if (selectedIgnoredGroup && selectedIgnoredGroup !== "all") {
        params.set("ignoredGroup", selectedIgnoredGroup);
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
      if (selectedIgnoredGroup && selectedIgnoredGroup !== "all") {
        params.set("ignoredGroup", selectedIgnoredGroup);
      }
      if (selectedOcrStopLevel && selectedOcrStopLevel !== "all") {
        params.set("ocrStopLevel", selectedOcrStopLevel);
      }
    } else if (reasonType === "ignored-group") {
      params.set(
        "collector",
        selectedCollector && selectedCollector !== "all"
          ? selectedCollector
          : "with_diagnostics",
      );
      params.set("ignoredGroup", reason);
      if (selectedCaptureStopReason && selectedCaptureStopReason !== "all") {
        params.set("captureStopReason", selectedCaptureStopReason);
      }
      if (selectedOcrStopReason && selectedOcrStopReason !== "all") {
        params.set("ocrStopReason", selectedOcrStopReason);
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
      if (selectedIgnoredGroup && selectedIgnoredGroup !== "all") {
        params.set("ignoredGroup", selectedIgnoredGroup);
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
        <h2>시즌 검증 개요</h2>
        <span className={styles.muted}>시즌 전체 품질 요약</span>
      </div>
      <div className={styles.statsGrid}>
        <StatCard label="스냅샷" value={String(overview.snapshot_count)} />
        <StatCard
          label="완료"
          value={String(overview.completed_snapshot_count)}
        />
        <StatCard
          label="수집 중"
          value={String(overview.collecting_snapshot_count)}
        />
        <StatCard label="실패" value={String(overview.failed_snapshot_count)} />
        <StatCard label="엔트리" value={String(overview.total_entry_count)} />
        <StatCard label="유효" value={String(overview.valid_entry_count)} />
        <StatCard label="무효" value={String(overview.invalid_entry_count)} />
        <StatCard
          label="통계 제외 수"
          value={String(overview.excluded_from_statistics_count)}
        />
        <StatCard
          label="무효 비율"
          value={formatPercent(overview.invalid_ratio)}
        />
        <StatCard
          label="주요 이슈"
          value={overview.top_validation_issue?.code ?? "-"}
        />
        <StatCard
          label="진단 포함 스냅샷"
          value={String(overview.snapshots_with_collector_diagnostics_count)}
        />
        <StatCard
          label="캡처 중단"
          value={String(overview.snapshots_with_capture_stop_count)}
        />
        <StatCard
          label="강한 OCR 중단"
          value={String(overview.snapshots_with_hard_ocr_stop_count)}
        />
        <StatCard
          label="무시된 OCR 줄"
          value={String(overview.total_ignored_line_count)}
        />
        <StatCard
          label="오버레이 OCR 줄"
          value={String(overview.overlay_ignored_line_count)}
        />
        <StatCard
          label="헤더 OCR 줄"
          value={String(overview.header_ignored_line_count)}
        />
        <StatCard
          label="비정상 엔트리 OCR"
          value={String(overview.malformed_entry_line_count)}
        />
      </div>
      <div className={styles.paginationLinks}>
        {overview.overlay_ignored_line_count > 0 ? (
          <Link
            href={buildSeasonReasonHref("ignored-group", "overlay")}
            className={styles.linkButton}
          >
            오버레이 OCR 보기
          </Link>
        ) : null}
        {overview.header_ignored_line_count > 0 ? (
          <Link
            href={buildSeasonReasonHref("ignored-group", "header")}
            className={styles.linkButton}
          >
            헤더 OCR 보기
          </Link>
        ) : null}
        {overview.malformed_entry_line_count > 0 ? (
          <Link
            href={buildSeasonReasonHref("ignored-group", "malformed")}
            className={styles.linkButton}
          >
            비정상 엔트리 OCR 보기
          </Link>
        ) : null}
      </div>
      <div className={styles.threeColumnGrid}>
        <div className={styles.subPanel}>
          <div className={styles.panelTitle}>
            <h3>페이지 품질 신호</h3>
          </div>
          <div className={styles.keyValueList}>
            <div className={styles.keyValueRow}>
              <span>빈 페이지</span>
              <strong>{overview.empty_page_count.toLocaleString()}</strong>
            </div>
            <div className={styles.keyValueRow}>
              <span>Sparse 페이지</span>
              <strong>{overview.sparse_page_count.toLocaleString()}</strong>
            </div>
            <div className={styles.keyValueRow}>
              <span>중복 페이지</span>
              <strong>{overview.overlapping_page_count.toLocaleString()}</strong>
            </div>
            <div className={styles.keyValueRow}>
              <span>Stale 페이지</span>
              <strong>{overview.stale_page_count.toLocaleString()}</strong>
            </div>
            <div className={styles.keyValueRow}>
              <span>Noise 페이지</span>
              <strong>{overview.noisy_page_count.toLocaleString()}</strong>
            </div>
          </div>
        </div>
      </div>
      <div className={styles.threeColumnGrid}>
        <ReasonSummaryPanel
          title="캡처 중단 사유"
          rows={overview.capture_stop_reasons}
          emptyMessage="집계된 캡처 중단 사유가 없습니다."
          getHref={(reason) => buildSeasonReasonHref("capture", reason)}
        />
        <ReasonSummaryPanel
          title="OCR 중단 사유"
          rows={overview.ocr_stop_reasons}
          emptyMessage="집계된 OCR 중단 사유가 없습니다."
          getHref={(reason) => buildSeasonReasonHref("ocr", reason)}
        />
        <ReasonSummaryPanel
          title="무시된 OCR 사유"
          rows={overview.ignored_reasons}
          emptyMessage="집계된 무시된 OCR 사유가 없습니다."
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
  ignoredGroup,
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
  ignoredGroup?: string;
  ocrStopLevel?: string;
}) {
  const maxInvalidRatio =
    series.points.reduce((currentMax, point) => {
      return Math.max(currentMax, point.invalid_ratio);
    }, 0) || 1;

  return (
    <section className={styles.panel}>
      <div className={styles.panelTitle}>
        <h2>검증 시계열</h2>
        <span className={styles.muted}>스냅샷별 무효 비율과 주요 이슈</span>
      </div>
      {series.points.length === 0 ? (
        <EmptyBox message="검증 시계열을 표시할 스냅샷이 없습니다." />
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
                  <th>스냅샷</th>
                  <th>상태</th>
                  <th>수집 시각</th>
                  <th>무효 비율</th>
                  <th>무효 엔트리</th>
                  <th>주요 이슈</th>
                  <th>수집 중단</th>
                  <th>무시된 OCR</th>
                  <th>비교</th>
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
                                  ignoredGroup && ignoredGroup !== "all"
                                    ? `&ignoredGroup=${encodeURIComponent(ignoredGroup)}`
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
        <h2>스냅샷 비교</h2>
        <span className={styles.muted}>두 스냅샷의 품질과 점수 차이를 나란히 봅니다.</span>
      </div>

      <div className={styles.compareHeaderGrid}>
        <SnapshotCompareHeader snapshot={leftSnapshot} sideLabel="왼쪽" />
        <SnapshotCompareHeader snapshot={rightSnapshot} sideLabel="오른쪽" />
      </div>

      <div className={styles.compareActions}>
        <Link href={`/snapshots/${leftSnapshot.id}`} className={styles.linkButton}>
          왼쪽 상세
        </Link>
        <Link href={`/snapshots/${rightSnapshot.id}`} className={styles.linkButton}>
          오른쪽 상세
        </Link>
        <Link
          href={`/snapshots/${leftSnapshot.id}?isValid=false`}
          className={styles.linkButton}
        >
          왼쪽 무효
        </Link>
        <Link
          href={`/snapshots/${rightSnapshot.id}?isValid=false`}
          className={styles.linkButton}
        >
          오른쪽 무효
        </Link>
        {leftTopIssue ? (
          <Link
            href={`/snapshots/${leftSnapshot.id}?validationIssue=${encodeURIComponent(
              leftTopIssue.code,
            )}&isValid=false`}
            className={styles.linkButton}
          >
            왼쪽 주요 이슈
          </Link>
        ) : null}
        {rightTopIssue ? (
          <Link
            href={`/snapshots/${rightSnapshot.id}?validationIssue=${encodeURIComponent(
              rightTopIssue.code,
            )}&isValid=false`}
            className={styles.linkButton}
          >
            오른쪽 주요 이슈
          </Link>
        ) : null}
      </div>

      <div className={styles.statsGrid}>
        <StatCard
          label="왼쪽 이슈 유형"
          value={String(leftSummary.validation_issues.length)}
        />
        <StatCard
          label="오른쪽 이슈 유형"
          value={String(rightSummary.validation_issues.length)}
        />
        <StatCard
          label="왼쪽 주요 이슈"
          value={leftTopIssue?.code ?? "-"}
        />
        <StatCard
          label="오른쪽 주요 이슈"
          value={rightTopIssue?.code ?? "-"}
        />
        <StatCard
          label="왼쪽 무효 비율"
          value={formatPercent(calculateInvalidRatio(leftSummary))}
        />
        <StatCard
          label="오른쪽 무효 비율"
          value={formatPercent(calculateInvalidRatio(rightSummary))}
        />
        <StatCard
          label="왼쪽 수집 중단"
          value={formatCollectorStop(leftCollectorDiagnostics)}
        />
        <StatCard
          label="오른쪽 수집 중단"
          value={formatCollectorStop(rightCollectorDiagnostics)}
        />
        <StatCard
          label="왼쪽 무시된 OCR"
          value={formatCollectorIgnoredCount(leftCollectorDiagnostics)}
        />
        <StatCard
          label="오른쪽 무시된 OCR"
          value={formatCollectorIgnoredCount(rightCollectorDiagnostics)}
        />
      </div>

      <div className={`${styles.tableWrap} ${styles.compareTableSection}`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>항목</th>
              <th>왼쪽</th>
              <th>오른쪽</th>
              <th>차이</th>
            </tr>
          </thead>
          <tbody>
            <CompareRow
              label="수집 행 수"
              leftValue={leftSummary.total_rows_collected}
              rightValue={rightSummary.total_rows_collected}
            />
            <CompareRow
              label="유효 엔트리"
              leftValue={leftSummary.valid_entry_count}
              rightValue={rightSummary.valid_entry_count}
            />
            <CompareRow
              label="무효 엔트리"
              leftValue={leftSummary.invalid_entry_count}
              rightValue={rightSummary.invalid_entry_count}
            />
            <CompareRow
              label="최고 점수"
              leftValue={leftSummary.highest_score}
              rightValue={rightSummary.highest_score}
            />
            <CompareRow
              label="최저 점수"
              leftValue={leftSummary.lowest_score}
              rightValue={rightSummary.lowest_score}
            />
            <CompareRow
              label="평균 점수"
              leftValue={leftDistribution.avg_score}
              rightValue={rightDistribution.avg_score}
            />
            <CompareRow
              label="중앙값"
              leftValue={leftDistribution.median_score}
              rightValue={rightDistribution.median_score}
            />
            <CompareRow
              label="무시된 OCR 줄"
              leftValue={leftCollectorDiagnostics?.ignored_line_count ?? null}
              rightValue={rightCollectorDiagnostics?.ignored_line_count ?? null}
            />
            <CompareRow
              label="빈 페이지"
              leftValue={leftCollectorDiagnostics?.empty_page_count ?? null}
              rightValue={rightCollectorDiagnostics?.empty_page_count ?? null}
            />
            <CompareRow
              label="Sparse 페이지"
              leftValue={leftCollectorDiagnostics?.sparse_page_count ?? null}
              rightValue={rightCollectorDiagnostics?.sparse_page_count ?? null}
            />
            <CompareRow
              label="중복 페이지"
              leftValue={leftCollectorDiagnostics?.overlapping_page_count ?? null}
              rightValue={rightCollectorDiagnostics?.overlapping_page_count ?? null}
            />
            <CompareRow
              label="Stale 페이지"
              leftValue={leftCollectorDiagnostics?.stale_page_count ?? null}
              rightValue={rightCollectorDiagnostics?.stale_page_count ?? null}
            />
            <CompareRow
              label="Noise 페이지"
              leftValue={leftCollectorDiagnostics?.noisy_page_count ?? null}
              rightValue={rightCollectorDiagnostics?.noisy_page_count ?? null}
            />
            <CompareRow
              label="오버레이 OCR 줄"
              leftValue={leftCollectorDiagnostics?.overlay_ignored_line_count ?? null}
              rightValue={rightCollectorDiagnostics?.overlay_ignored_line_count ?? null}
            />
            <CompareRow
              label="헤더 OCR 줄"
              leftValue={leftCollectorDiagnostics?.header_ignored_line_count ?? null}
              rightValue={rightCollectorDiagnostics?.header_ignored_line_count ?? null}
            />
            <CompareRow
              label="비정상 엔트리 OCR"
              leftValue={leftCollectorDiagnostics?.malformed_entry_line_count ?? null}
              rightValue={rightCollectorDiagnostics?.malformed_entry_line_count ?? null}
            />
            <CompareTextRow
              label="수집 페이지"
              leftValue={leftCollectorDiagnostics ? formatCollectorPages(leftCollectorDiagnostics) : "-"}
              rightValue={rightCollectorDiagnostics ? formatCollectorPages(rightCollectorDiagnostics) : "-"}
            />
            <CompareTextRow
              label="수집 중단"
              leftValue={formatCollectorStop(leftCollectorDiagnostics)}
              rightValue={formatCollectorStop(rightCollectorDiagnostics)}
            />
          </tbody>
        </table>
      </div>

      <div className={`${styles.tableWrap} ${styles.compareTableSection}`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>컷오프 순위</th>
              <th>왼쪽</th>
              <th>오른쪽</th>
              <th>차이</th>
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
        <EmptyBox message="두 스냅샷 모두 집계된 검증 이슈가 없습니다." />
      ) : (
        <div className={`${styles.tableWrap} ${styles.compareTableSection}`}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>검증 이슈</th>
                <th>왼쪽</th>
                <th>오른쪽</th>
                <th>차이</th>
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
        <h2>순위 {series.rank.toLocaleString()} 컷오프 시계열</h2>
        <span className={styles.muted}>완료된 스냅샷 기준</span>
      </div>
      {series.points.length === 0 ? (
        <EmptyBox message="완료된 스냅샷이 아직 없습니다." />
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
                  <th>스냅샷</th>
                  <th>수집 시각</th>
                  <th>점수</th>
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
            <th>순위</th>
            <th>점수</th>
            <th>플레이어</th>
            <th>유효성</th>
            <th>OCR</th>
            <th>이슈</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>{entry.rank.toLocaleString()}</td>
              <td>{entry.score.toLocaleString()}</td>
              <td>{entry.player_name ?? "-"}</td>
              <td className={entry.is_valid ? styles.entryValid : styles.entryInvalid}>
                {entry.is_valid ? "유효" : "무효"}
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
                <th>사유</th>
                <th>개수</th>
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
        <MetaItem label="수집 시각" value={formatDate(snapshot.captured_at)} />
        <MetaItem label="입력 소스" value={formatSourceType(snapshot.source_type)} />
        <MetaItem label="행 수" value={formatNullableNumber(snapshot.total_rows_collected)} />
        <MetaItem label="메모" value={formatSnapshotNote(snapshot.note)} />
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
      <td>{leftValue === rightValue ? "같음" : "-"}</td>
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
    return `캡처:${diagnostics.capture_stop_reason}`;
  }

  if (diagnostics.ocr_stop_reason) {
    const level = diagnostics.ocr_stop_level
      ? `(${diagnostics.ocr_stop_level})`
      : "";
    return `OCR:${diagnostics.ocr_stop_reason}${level}`;
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

function formatSnapshotNote(note: string | null) {
  if (!note) {
    return "-";
  }

  const lines = note
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    return "-";
  }

  const visibleLines = lines.filter(
    (line) => !line.startsWith("collector_json:"),
  );
  if (visibleLines.length === 0) {
    return "collector 진단 정보 저장됨";
  }

  const summary = visibleLines.join(" / ");
  if (summary.length <= 160) {
    return summary;
  }

  return `${summary.slice(0, 157)}...`;
}

function formatStatusText(status: string) {
  switch (status) {
    case "completed":
      return "완료";
    case "collecting":
      return "수집 중";
    case "failed":
      return "실패";
    default:
      return status;
  }
}

function formatSourceType(sourceType: string) {
  switch (sourceType) {
    case "image_sidecar":
      return "이미지 사이드카";
    case "image_tesseract":
      return "이미지 Tesseract";
    case "mock_json":
      return "목업 JSON";
    default:
      return sourceType;
  }
}

function formatEventType(eventType: string) {
  switch (eventType) {
    case "total_assault":
      return "총력전";
    case "grand_assault":
      return "대결전";
    default:
      return eventType;
  }
}
