import Link from "next/link";

import styles from "../../dashboard.module.css";
import {
  CutoffSeriesPanel,
  EmptyBox,
  ErrorBox,
  PageShell,
  SeasonValidationOverviewPanel,
  SeasonValidationSeriesPanel,
  SeasonSummary,
  SnapshotComparisonPanel,
  SnapshotList,
  ValidationIssuesPanel,
} from "../../components/dashboard";
import {
  getSeason,
  getSnapshotCutoffs,
  getSnapshotDistribution,
  getSnapshotSummary,
  getSnapshotValidationReport,
  getSeasonCutoffSeries,
  getSeasonSnapshots,
  getSeasonValidationSeries,
  getSeasonValidationOverview,
} from "../../lib/api";

export const dynamic = "force-dynamic";

type SeasonPageProps = {
  params: Promise<{ seasonId: string }>;
  searchParams: Promise<{
    rank?: string;
    status?: string;
    source?: string;
    collector?: string;
    captureStopReason?: string;
    ocrStopReason?: string;
    pipelineStopReason?: string;
    pipelineStopSource?: string;
    pipelineStopLevel?: string;
    ignoredReason?: string;
    ignoredGroup?: string;
    pageSignal?: string;
    ocrStopLevel?: string;
    compareLeft?: string;
    compareRight?: string;
  }>;
};

const SERIES_RANK_OPTIONS = [1, 10, 100, 1000, 5000, 10000];
const SEASON_STATUS_FILTERS = ["completed", "collecting", "failed"] as const;
const SEASON_COLLECTOR_FILTERS = [
  "with_diagnostics",
  "capture_stop",
  "hard_ocr_stop",
] as const;

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
  const selectedCollector =
    resolvedSearchParams.collector && resolvedSearchParams.collector.trim()
      ? resolvedSearchParams.collector
      : "all";
  const selectedCaptureStopReason =
    resolvedSearchParams.captureStopReason &&
    resolvedSearchParams.captureStopReason.trim()
      ? resolvedSearchParams.captureStopReason
      : "all";
  const selectedOcrStopReason =
    resolvedSearchParams.ocrStopReason && resolvedSearchParams.ocrStopReason.trim()
      ? resolvedSearchParams.ocrStopReason
      : "all";
  const selectedPipelineStopReason =
    resolvedSearchParams.pipelineStopReason &&
    resolvedSearchParams.pipelineStopReason.trim()
      ? resolvedSearchParams.pipelineStopReason
      : "all";
  const selectedPipelineStopSource =
    resolvedSearchParams.pipelineStopSource &&
    resolvedSearchParams.pipelineStopSource.trim()
      ? resolvedSearchParams.pipelineStopSource
      : "all";
  const selectedPipelineStopLevel =
    resolvedSearchParams.pipelineStopLevel &&
    resolvedSearchParams.pipelineStopLevel.trim()
      ? resolvedSearchParams.pipelineStopLevel
      : "all";
  const selectedIgnoredReason =
    resolvedSearchParams.ignoredReason && resolvedSearchParams.ignoredReason.trim()
      ? resolvedSearchParams.ignoredReason
      : "all";
  const selectedIgnoredGroup =
    resolvedSearchParams.ignoredGroup && resolvedSearchParams.ignoredGroup.trim()
      ? resolvedSearchParams.ignoredGroup
      : "all";
  const selectedPageSignal =
    resolvedSearchParams.pageSignal && resolvedSearchParams.pageSignal.trim()
      ? resolvedSearchParams.pageSignal
      : "all";
  const selectedOcrStopLevel =
    resolvedSearchParams.ocrStopLevel && resolvedSearchParams.ocrStopLevel.trim()
      ? resolvedSearchParams.ocrStopLevel
      : "all";
  const requestedCompareLeft = Number(resolvedSearchParams.compareLeft ?? "");
  const requestedCompareRight = Number(resolvedSearchParams.compareRight ?? "");
  const selectedStatusFilter = SEASON_STATUS_FILTERS.includes(
    selectedStatus as (typeof SEASON_STATUS_FILTERS)[number],
  )
    ? (selectedStatus as (typeof SEASON_STATUS_FILTERS)[number])
    : undefined;
  const selectedCollectorFilter = SEASON_COLLECTOR_FILTERS.includes(
    selectedCollector as (typeof SEASON_COLLECTOR_FILTERS)[number],
  )
    ? (selectedCollector as (typeof SEASON_COLLECTOR_FILTERS)[number])
    : undefined;

  const [
    seasonResult,
    snapshotsResult,
    seriesResult,
    validationOverviewResult,
    validationSeriesResult,
  ] =
    await Promise.all([
      getSeason(numericSeasonId),
      getSeasonSnapshots(numericSeasonId),
      getSeasonCutoffSeries(numericSeasonId, Number.isNaN(seriesRank) ? 10 : seriesRank, {
        sourceType: selectedSource === "all" ? undefined : selectedSource,
      }),
      getSeasonValidationOverview(numericSeasonId, {
        status: selectedStatusFilter,
        sourceType: selectedSource === "all" ? undefined : selectedSource,
        collectorFilter: selectedCollectorFilter,
        captureStopReason:
          selectedCaptureStopReason === "all"
            ? undefined
            : selectedCaptureStopReason,
        ocrStopReason:
          selectedOcrStopReason === "all" ? undefined : selectedOcrStopReason,
        pipelineStopReason:
          selectedPipelineStopReason === "all"
            ? undefined
            : selectedPipelineStopReason,
        pipelineStopSource:
          selectedPipelineStopSource === "all"
            ? undefined
            : (selectedPipelineStopSource as "capture" | "ocr"),
        pipelineStopLevel:
          selectedPipelineStopLevel === "all"
            ? undefined
            : (selectedPipelineStopLevel as "soft" | "hard"),
        ignoredReason:
          selectedIgnoredReason === "all" ? undefined : selectedIgnoredReason,
        ignoredGroup:
          selectedIgnoredGroup === "all"
            ? undefined
            : (selectedIgnoredGroup as "overlay" | "header" | "malformed"),
        pageSignal:
          selectedPageSignal === "all"
            ? undefined
            : (selectedPageSignal as
                | "empty"
                | "sparse"
                | "overlapping"
                | "stale"
                | "noisy"),
        ocrStopLevel:
          selectedOcrStopLevel === "all"
            ? undefined
            : (selectedOcrStopLevel as "soft" | "hard"),
      }),
      getSeasonValidationSeries(numericSeasonId, {
        status: selectedStatusFilter,
        sourceType: selectedSource === "all" ? undefined : selectedSource,
        collectorFilter: selectedCollectorFilter,
        captureStopReason:
          selectedCaptureStopReason === "all"
            ? undefined
            : selectedCaptureStopReason,
        ocrStopReason:
          selectedOcrStopReason === "all" ? undefined : selectedOcrStopReason,
        pipelineStopReason:
          selectedPipelineStopReason === "all"
            ? undefined
            : selectedPipelineStopReason,
        pipelineStopSource:
          selectedPipelineStopSource === "all"
            ? undefined
            : (selectedPipelineStopSource as "capture" | "ocr"),
        pipelineStopLevel:
          selectedPipelineStopLevel === "all"
            ? undefined
            : (selectedPipelineStopLevel as "soft" | "hard"),
        ignoredReason:
          selectedIgnoredReason === "all" ? undefined : selectedIgnoredReason,
        ignoredGroup:
          selectedIgnoredGroup === "all"
            ? undefined
            : (selectedIgnoredGroup as "overlay" | "header" | "malformed"),
        pageSignal:
          selectedPageSignal === "all"
            ? undefined
            : (selectedPageSignal as
                | "empty"
                | "sparse"
                | "overlapping"
                | "stale"
                | "noisy"),
        ocrStopLevel:
          selectedOcrStopLevel === "all"
            ? undefined
            : (selectedOcrStopLevel as "soft" | "hard"),
      }),
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
    if (
      (selectedCollector !== "all" ||
        selectedCaptureStopReason !== "all" ||
        selectedOcrStopReason !== "all" ||
        selectedPipelineStopReason !== "all" ||
        selectedPipelineStopSource !== "all" ||
        selectedPipelineStopLevel !== "all" ||
        selectedIgnoredReason !== "all" ||
        selectedIgnoredGroup !== "all" ||
        selectedPageSignal !== "all" ||
        selectedOcrStopLevel !== "all") &&
      validationSeriesResult.data &&
      !validationSeriesResult.data.points.some(
        (point) => point.snapshot_id === snapshot.id,
      )
    ) {
      return false;
    }
    return true;
  });
  const filteredCompareCandidates = [...filteredSnapshots].sort(
    (left, right) =>
      new Date(right.captured_at).getTime() - new Date(left.captured_at).getTime(),
  );
  const completedCompareCandidates = filteredCompareCandidates.filter(
    (snapshot) => snapshot.status === "completed",
  );
  const defaultCompareCandidates =
    completedCompareCandidates.length >= 2
      ? completedCompareCandidates
      : filteredCompareCandidates;
  const fallbackLeftSnapshot = defaultCompareCandidates[0] ?? null;
  const fallbackRightSnapshot =
    defaultCompareCandidates.find(
      (snapshot) => snapshot.id !== fallbackLeftSnapshot?.id,
    ) ?? null;
  const selectedCompareLeft =
    filteredCompareCandidates.find((snapshot) => snapshot.id === requestedCompareLeft) ??
    fallbackLeftSnapshot;
  const selectedCompareRight =
    filteredCompareCandidates.find((snapshot) => snapshot.id === requestedCompareRight) ??
    fallbackRightSnapshot;
  const validationPointsBySnapshotId = new Map(
    (validationSeriesResult.data?.points ?? []).map((point) => [
      point.snapshot_id,
      point,
    ]),
  );
  const canCompareSnapshots =
    selectedCompareLeft !== null &&
    selectedCompareRight !== null &&
    selectedCompareLeft.id !== selectedCompareRight.id;
  const compareResults = canCompareSnapshots
    ? await Promise.all([
        getSnapshotSummary(selectedCompareLeft.id),
        getSnapshotSummary(selectedCompareRight.id),
        getSnapshotCutoffs(selectedCompareLeft.id),
        getSnapshotCutoffs(selectedCompareRight.id),
        getSnapshotDistribution(selectedCompareLeft.id),
        getSnapshotDistribution(selectedCompareRight.id),
        getSnapshotValidationReport(selectedCompareLeft.id),
        getSnapshotValidationReport(selectedCompareRight.id),
      ])
    : null;
  const comparisonHasError =
    compareResults !== null && compareResults.some((result) => result.error || !result.data);
  const normalizedSeriesRank = Number.isNaN(seriesRank) ? 10 : seriesRank;
  const preservedSeasonParams = new URLSearchParams({
    rank: String(normalizedSeriesRank),
  });

  if (selectedCompareLeft) {
    preservedSeasonParams.set("compareLeft", String(selectedCompareLeft.id));
  }
  if (selectedCompareRight) {
    preservedSeasonParams.set("compareRight", String(selectedCompareRight.id));
  }

  const seasonResetHref = `/seasons/${numericSeasonId}?${preservedSeasonParams.toString()}`;
  const activeSeasonFilters = [
    selectedStatus !== "all" ? `상태: ${formatStatusLabel(selectedStatus)}` : null,
    selectedSource !== "all" ? `입력 소스: ${formatSourceTypeLabel(selectedSource)}` : null,
    selectedCollector !== "all"
      ? `수집 진단: ${formatCollectorFilterLabel(selectedCollector)}`
      : null,
    selectedCaptureStopReason !== "all"
      ? `캡처 중단: ${selectedCaptureStopReason}`
      : null,
    selectedOcrStopReason !== "all" ? `OCR 중단: ${selectedOcrStopReason}` : null,
    selectedPipelineStopReason !== "all"
      ? `파이프라인 중단: ${selectedPipelineStopReason}`
      : null,
    selectedPipelineStopSource !== "all"
      ? `파이프라인 소스: ${formatPipelineStopSourceLabel(selectedPipelineStopSource)}`
      : null,
    selectedPipelineStopLevel !== "all"
      ? `파이프라인 레벨: ${formatOcrStopLevelLabel(selectedPipelineStopLevel)}`
      : null,
    selectedIgnoredReason !== "all" ? `무시된 OCR: ${selectedIgnoredReason}` : null,
    selectedIgnoredGroup !== "all"
      ? `무시 그룹: ${formatIgnoredGroupLabel(selectedIgnoredGroup)}`
      : null,
    selectedPageSignal !== "all"
      ? `페이지 신호: ${formatPageSignalLabel(selectedPageSignal)}`
      : null,
    selectedOcrStopLevel !== "all"
      ? `OCR 레벨: ${formatOcrStopLevelLabel(selectedOcrStopLevel)}`
      : null,
  ].filter((value): value is string => Boolean(value));
  const hasAdvancedSeasonFilters =
    selectedCollector !== "all" ||
    selectedCaptureStopReason !== "all" ||
    selectedOcrStopReason !== "all" ||
    selectedPipelineStopReason !== "all" ||
    selectedPipelineStopSource !== "all" ||
    selectedPipelineStopLevel !== "all" ||
    selectedIgnoredReason !== "all" ||
    selectedIgnoredGroup !== "all" ||
    selectedPageSignal !== "all" ||
    selectedOcrStopLevel !== "all";
  const hasExplicitCompareSelection =
    Number.isFinite(requestedCompareLeft) || Number.isFinite(requestedCompareRight);
  const compareSelectionSummary =
    selectedCompareLeft && selectedCompareRight
      ? `#${selectedCompareLeft.id} ↔ #${selectedCompareRight.id}`
      : filteredCompareCandidates.length >= 2
        ? "최근 스냅샷 2개 자동 선택"
        : "비교 대상 부족";

  return (
    <PageShell
      eyebrow="시즌 상세"
      title={season?.season_label ?? `시즌 #${seasonId}`}
      subtitle="검증, 비교, cutoff 흐름을 한 화면에서 정리합니다."
      backHref="/admin"
      backLabel="관리 시즌 목록으로"
    >
      {seasonResult.error || !season ? (
        <ErrorBox
          message={`시즌 정보를 불러오지 못했습니다. ${
            seasonResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      ) : (
        <div className={styles.grid}>
          <div className={`${styles.grid} ${styles.twoColumn}`}>
	            <div className={`${styles.grid} ${styles.mainColumn}`}>
	              <div id="validation-overview" className={styles.anchorTarget}>
	                {validationOverviewResult.error || !validationOverviewResult.data ? (
	                  <ErrorBox
                    message={`검증 개요를 불러오지 못했습니다. ${
                      validationOverviewResult.error ?? "알 수 없는 오류입니다."
                    }`}
                  />
                ) : (
                  <SeasonValidationOverviewPanel
                    overview={validationOverviewResult.data}
                    seasonId={numericSeasonId}
                    selectedStatus={selectedStatus}
                    selectedSource={selectedSource}
                    selectedCollector={selectedCollector}
                    selectedCaptureStopReason={selectedCaptureStopReason}
                    selectedOcrStopReason={selectedOcrStopReason}
                    selectedPipelineStopReason={selectedPipelineStopReason}
                    selectedPipelineStopSource={selectedPipelineStopSource}
                    selectedPipelineStopLevel={selectedPipelineStopLevel}
                    selectedIgnoredReason={selectedIgnoredReason}
                    selectedIgnoredGroup={selectedIgnoredGroup}
                    selectedPageSignal={selectedPageSignal}
                    selectedOcrStopLevel={selectedOcrStopLevel}
	                  />
	                )}
	              </div>

	              <div id="validation-series" className={styles.anchorTarget}>
	                {validationSeriesResult.error || !validationSeriesResult.data ? (
	                  <ErrorBox
                    message={`검증 시계열을 불러오지 못했습니다. ${
                      validationSeriesResult.error ?? "알 수 없는 오류입니다."
                    }`}
                  />
                ) : (
                  <SeasonValidationSeriesPanel
                    series={validationSeriesResult.data}
                    selectedCompareLeftId={selectedCompareLeft?.id ?? null}
                    selectedCompareRightId={selectedCompareRight?.id ?? null}
                    compareRank={normalizedSeriesRank}
                    collectorFilter={selectedCollector}
                    selectedStatus={selectedStatus}
                    selectedSource={selectedSource}
                    captureStopReason={selectedCaptureStopReason}
                    ocrStopReason={selectedOcrStopReason}
                    pipelineStopReason={selectedPipelineStopReason}
                    pipelineStopSource={selectedPipelineStopSource}
                    pipelineStopLevel={selectedPipelineStopLevel}
                    ignoredReason={selectedIgnoredReason}
                    ignoredGroup={selectedIgnoredGroup}
                    pageSignal={selectedPageSignal}
                    ocrStopLevel={selectedOcrStopLevel}
                  />
                )}
              </div>

              <div id="snapshot-list" className={styles.anchorTarget}>
                <section className={styles.panel}>
                  <div className={styles.panelTitle}>
                    <h2>스냅샷 목록</h2>
                    <span className={styles.muted}>
                      현재 조건에 맞는 스냅샷 {filteredSnapshots.length.toLocaleString()}개
                    </span>
                  </div>
                  {activeSeasonFilters.length > 0 ? (
                    <div className={styles.filterSummary}>
                      {activeSeasonFilters.map((filter) => (
                        <span key={filter} className={styles.filterChip}>
                          {filter}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className={styles.panelLead}>
                      필터가 없을 때는 시즌에 포함된 스냅샷을 시간순으로 모두 보여줍니다.
                    </p>
                  )}
                  {snapshotsResult.error ? (
                    <ErrorBox
                      message={`스냅샷 목록을 불러오지 못했습니다. ${snapshotsResult.error}`}
                    />
                  ) : filteredSnapshots.length > 0 ? (
                    <SnapshotList
                      snapshots={filteredSnapshots}
                      validationPoints={validationPointsBySnapshotId}
                    />
                  ) : (
                    <EmptyBox message="조건에 맞는 스냅샷이 없습니다." />
                  )}
                </section>
              </div>
	            </div>

	            <div className={styles.sidebarColumn}>
	              <div className={`${styles.sidebarStack} ${styles.rightRail}`}>
	                <div id="season-summary" className={styles.anchorTarget}>
	                  <SeasonSummary season={season} />
	                </div>

                  <section className={styles.panel}>
                    <div className={styles.panelTitle}>
                      <h2>빠른 이동</h2>
                      <span className={styles.muted}>
                        자주 보는 구간을 오른쪽에서 바로 엽니다.
                      </span>
                    </div>
                    <div className={styles.quickLinkGrid}>
                      <Link href="#validation-overview" className={styles.linkButton}>
                        검증 개요
                      </Link>
                      <Link href="#validation-series" className={styles.linkButton}>
                        검증 시계열
                      </Link>
                      <Link href="#validation-issues" className={styles.linkButton}>
                        검증 이슈
                      </Link>
                      <Link href="#snapshot-list" className={styles.linkButton}>
                        스냅샷 목록
                      </Link>
                      <Link href="#cutoff-series" className={styles.linkButton}>
                        컷오프 시계열
                      </Link>
                      {filteredCompareCandidates.length >= 2 ? (
                        <Link href="#snapshot-compare" className={styles.linkButton}>
                          스냅샷 비교
                        </Link>
                      ) : null}
                    </div>
                  </section>

                  {validationOverviewResult.error || !validationOverviewResult.data ? null : (
                    <div id="validation-issues" className={styles.anchorTarget}>
                      <ValidationIssuesPanel
                        issues={validationOverviewResult.data.validation_issues}
                      />
                    </div>
                  )}

	                <section className={styles.panel}>
	                  <div className={styles.panelTitle}>
                    <h2>스냅샷 필터</h2>
                    <span className={styles.muted}>
                      compare, validation, diagnostics 흐름을 같은 조건으로 좁힙니다.
                    </span>
                  </div>
                  {activeSeasonFilters.length > 0 ? (
                    <div className={styles.filterSummary}>
                      {activeSeasonFilters.map((filter) => (
                        <span key={filter} className={styles.filterChip}>
                          {filter}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className={styles.panelLead}>
                      필터를 적용하면 검증 시계열과 스냅샷 목록이 같은 조건으로 함께 갱신됩니다.
                    </p>
                  )}
	                  <form className={styles.controls}>
	                    <details className={styles.detailsSection} open>
	                      <summary className={styles.detailsSummary}>
	                        <span>기본 필터</span>
	                        <span className={styles.muted}>상태와 입력 소스를 먼저 좁힙니다.</span>
	                      </summary>
	                      <div className={styles.detailsBody}>
	                        <div className={styles.filterGrid}>
	                          <div className={styles.field}>
	                            <label htmlFor="status">상태</label>
	                            <select id="status" name="status" defaultValue={selectedStatus}>
	                              <option value="all">전체</option>
	                              <option value="completed">완료</option>
	                              <option value="collecting">수집 중</option>
	                              <option value="failed">실패</option>
	                            </select>
	                          </div>
	                          <div className={styles.field}>
	                            <label htmlFor="source">입력 소스</label>
	                            <select id="source" name="source" defaultValue={selectedSource}>
	                              <option value="all">전체</option>
	                              {sourceOptions.map((sourceType) => (
	                                <option key={sourceType} value={sourceType}>
	                                  {formatSourceTypeLabel(sourceType)}
	                                </option>
	                              ))}
	                            </select>
	                          </div>
	                        </div>
	                      </div>
	                    </details>
	                    <details
	                      className={styles.detailsSection}
	                      {...(hasAdvancedSeasonFilters ? { open: true } : {})}
	                    >
	                      <summary className={styles.detailsSummary}>
	                        <span>수집 진단 필터</span>
	                        <span className={styles.muted}>
	                          collector 진단과 중단 사유를 필요할 때만 펼쳐 봅니다.
	                        </span>
	                      </summary>
	                      <div className={styles.detailsBody}>
	                        <div className={styles.filterGrid}>
	                        <div className={styles.field}>
	                          <label htmlFor="collector">수집 진단</label>
	                          <select
	                            id="collector"
	                            name="collector"
	                            defaultValue={selectedCollector}
	                          >
	                            <option value="all">전체</option>
	                            <option value="with_diagnostics">진단 포함</option>
	                            <option value="capture_stop">캡처 중단</option>
	                            <option value="hard_ocr_stop">강한 OCR 중단</option>
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="captureStopReason">캡처 중단 사유</label>
	                          <select
	                            id="captureStopReason"
	                            name="captureStopReason"
	                            defaultValue={selectedCaptureStopReason}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.capture_stop_reasons.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {row.reason}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="ocrStopReason">OCR 중단 사유</label>
	                          <select
	                            id="ocrStopReason"
	                            name="ocrStopReason"
	                            defaultValue={selectedOcrStopReason}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.ocr_stop_reasons.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {row.reason}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="pipelineStopReason">파이프라인 중단 사유</label>
	                          <select
	                            id="pipelineStopReason"
	                            name="pipelineStopReason"
	                            defaultValue={selectedPipelineStopReason}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.pipeline_stop_reasons.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {row.reason}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="pipelineStopSource">파이프라인 소스</label>
	                          <select
	                            id="pipelineStopSource"
	                            name="pipelineStopSource"
	                            defaultValue={selectedPipelineStopSource}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.pipeline_stop_sources.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {formatPipelineStopSourceLabel(row.reason)}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="pipelineStopLevel">파이프라인 레벨</label>
	                          <select
	                            id="pipelineStopLevel"
	                            name="pipelineStopLevel"
	                            defaultValue={selectedPipelineStopLevel}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.pipeline_stop_levels.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {formatOcrStopLevelLabel(row.reason)}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="ignoredReason">무시된 OCR 사유</label>
	                          <select
	                            id="ignoredReason"
	                            name="ignoredReason"
	                            defaultValue={selectedIgnoredReason}
	                          >
	                            <option value="all">전체</option>
	                            {validationOverviewResult.data?.ignored_reasons.map((row) => (
	                              <option key={row.reason} value={row.reason}>
	                                {row.reason}
	                              </option>
	                            ))}
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="ignoredGroup">무시된 OCR 그룹</label>
	                          <select
	                            id="ignoredGroup"
	                            name="ignoredGroup"
	                            defaultValue={selectedIgnoredGroup}
	                          >
	                            <option value="all">전체</option>
	                            <option value="overlay">오버레이</option>
	                            <option value="header">헤더/페이지</option>
	                            <option value="malformed">비정상 엔트리</option>
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="pageSignal">페이지 품질 신호</label>
	                          <select
	                            id="pageSignal"
	                            name="pageSignal"
	                            defaultValue={selectedPageSignal}
	                          >
	                            <option value="all">전체</option>
	                            <option value="empty">빈 페이지</option>
	                            <option value="sparse">Sparse</option>
	                            <option value="overlapping">중복</option>
	                            <option value="stale">Stale</option>
	                            <option value="noisy">Noise</option>
	                          </select>
	                        </div>
	                        <div className={styles.field}>
	                          <label htmlFor="ocrStopLevel">OCR 중단 레벨</label>
	                          <select
	                            id="ocrStopLevel"
	                            name="ocrStopLevel"
	                            defaultValue={selectedOcrStopLevel}
	                          >
	                            <option value="all">전체</option>
	                            <option value="soft">약함</option>
	                            <option value="hard">강함</option>
	                          </select>
	                        </div>
	                        </div>
	                      </div>
	                    </details>
	                    <input type="hidden" name="rank" value={String(normalizedSeriesRank)} />
	                    {selectedCompareLeft ? (
                      <input
                        type="hidden"
                        name="compareLeft"
                        value={String(selectedCompareLeft.id)}
                      />
                    ) : null}
                    {selectedCompareRight ? (
                      <input
                        type="hidden"
                        name="compareRight"
                        value={String(selectedCompareRight.id)}
                      />
                    ) : null}
                    <div className={styles.filterActions}>
                      <button type="submit" className={styles.button}>
                        필터 적용
                      </button>
                      <Link href={seasonResetHref} className={styles.linkButton}>
                        필터 초기화
                      </Link>
                    </div>
                  </form>
                </section>

                <section className={styles.panel}>
                  <div className={styles.panelTitle}>
                    <h2>분석 설정</h2>
                    <span className={styles.muted}>
                      컷오프 시계열과 스냅샷 비교 설정을 필요할 때만 펼쳐서 조정합니다.
                    </span>
                  </div>
                  <div className={styles.controls}>
                    <details className={styles.detailsSection}>
                      <summary className={styles.detailsSummary}>
                        <span>컷오프 시계열 설정</span>
                        <span className={styles.muted}>
                          현재 기준 순위 {normalizedSeriesRank.toLocaleString()}
                        </span>
                      </summary>
                      <div className={styles.detailsBody}>
                        <form className={styles.controls}>
                          <div className={styles.filterGrid}>
                            <div className={styles.field}>
                              <label htmlFor="rank">순위</label>
                              <select
                                id="rank"
                                name="rank"
                                defaultValue={String(normalizedSeriesRank)}
                              >
                                {SERIES_RANK_OPTIONS.map((rank) => (
                                  <option key={rank} value={rank}>
                                    {rank.toLocaleString()}
                                  </option>
                                ))}
                              </select>
                            </div>
                          </div>
                          <input type="hidden" name="status" value={selectedStatus} />
                          <input type="hidden" name="source" value={selectedSource} />
                          <input type="hidden" name="collector" value={selectedCollector} />
                          <input
                            type="hidden"
                            name="captureStopReason"
                            value={selectedCaptureStopReason}
                          />
                          <input
                            type="hidden"
                            name="ocrStopReason"
                            value={selectedOcrStopReason}
                          />
                          <input
                            type="hidden"
                            name="pipelineStopReason"
                            value={selectedPipelineStopReason}
                          />
                          <input
                            type="hidden"
                            name="pipelineStopSource"
                            value={selectedPipelineStopSource}
                          />
                          <input
                            type="hidden"
                            name="pipelineStopLevel"
                            value={selectedPipelineStopLevel}
                          />
                          <input
                            type="hidden"
                            name="ignoredReason"
                            value={selectedIgnoredReason}
                          />
                          <input
                            type="hidden"
                            name="ignoredGroup"
                            value={selectedIgnoredGroup}
                          />
                          <input type="hidden" name="pageSignal" value={selectedPageSignal} />
                          <input
                            type="hidden"
                            name="ocrStopLevel"
                            value={selectedOcrStopLevel}
                          />
                          {selectedCompareLeft ? (
                            <input
                              type="hidden"
                              name="compareLeft"
                              value={String(selectedCompareLeft.id)}
                            />
                          ) : null}
                          {selectedCompareRight ? (
                            <input
                              type="hidden"
                              name="compareRight"
                              value={String(selectedCompareRight.id)}
                            />
                          ) : null}
                          <div className={styles.filterActions}>
                            <button type="submit" className={styles.button}>
                              컷오프 갱신
                            </button>
                          </div>
                        </form>
                      </div>
                    </details>

                    <details
                      className={styles.detailsSection}
                      {...(hasExplicitCompareSelection ? { open: true } : {})}
                    >
                      <summary className={styles.detailsSummary}>
                        <span>스냅샷 비교 설정</span>
                        <span className={styles.muted}>{compareSelectionSummary}</span>
                      </summary>
                      <div className={styles.detailsBody}>
                        {filteredCompareCandidates.length < 2 ? (
                          <EmptyBox message="비교하려면 스냅샷이 두 개 이상 필요합니다." />
                        ) : (
                          <form className={styles.controls}>
                            <div className={styles.filterGrid}>
                              <div className={styles.field}>
                                <label htmlFor="compareLeft">왼쪽 스냅샷</label>
                                <select
                                  id="compareLeft"
                                  name="compareLeft"
                                  defaultValue={String(selectedCompareLeft?.id ?? "")}
                                >
                                  {filteredCompareCandidates.map((snapshot) => (
                                    <option key={snapshot.id} value={snapshot.id}>
                                      #{snapshot.id} · {formatStatusLabel(snapshot.status)} ·{" "}
                                      {formatSourceTypeLabel(snapshot.source_type)}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <div className={styles.field}>
                                <label htmlFor="compareRight">오른쪽 스냅샷</label>
                                <select
                                  id="compareRight"
                                  name="compareRight"
                                  defaultValue={String(selectedCompareRight?.id ?? "")}
                                >
                                  {filteredCompareCandidates.map((snapshot) => (
                                    <option key={snapshot.id} value={snapshot.id}>
                                      #{snapshot.id} · {formatStatusLabel(snapshot.status)} ·{" "}
                                      {formatSourceTypeLabel(snapshot.source_type)}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            </div>
                            <input
                              type="hidden"
                              name="rank"
                              value={String(normalizedSeriesRank)}
                            />
                            <input type="hidden" name="status" value={selectedStatus} />
                            <input type="hidden" name="source" value={selectedSource} />
                            <input
                              type="hidden"
                              name="collector"
                              value={selectedCollector}
                            />
                            <input
                              type="hidden"
                              name="captureStopReason"
                              value={selectedCaptureStopReason}
                            />
                            <input
                              type="hidden"
                              name="ocrStopReason"
                              value={selectedOcrStopReason}
                            />
                            <input
                              type="hidden"
                              name="pipelineStopReason"
                              value={selectedPipelineStopReason}
                            />
                            <input
                              type="hidden"
                              name="pipelineStopSource"
                              value={selectedPipelineStopSource}
                            />
                            <input
                              type="hidden"
                              name="pipelineStopLevel"
                              value={selectedPipelineStopLevel}
                            />
                            <input
                              type="hidden"
                              name="ignoredReason"
                              value={selectedIgnoredReason}
                            />
                            <input
                              type="hidden"
                              name="ignoredGroup"
                              value={selectedIgnoredGroup}
                            />
                            <input
                              type="hidden"
                              name="pageSignal"
                              value={selectedPageSignal}
                            />
                            <input
                              type="hidden"
                              name="ocrStopLevel"
                              value={selectedOcrStopLevel}
                            />
                            <div className={styles.filterActions}>
                              <button type="submit" className={styles.button}>
                                비교 반영
                              </button>
                            </div>
                          </form>
                        )}
                      </div>
                    </details>
                  </div>
                </section>

                <div id="cutoff-series" className={styles.anchorTarget}>
                  {seriesResult.error ? (
                    <ErrorBox
                      message={`컷오프 시계열을 불러오지 못했습니다. ${seriesResult.error}`}
                    />
                  ) : seriesResult.data ? (
                    <CutoffSeriesPanel series={seriesResult.data} />
                  ) : (
                    <EmptyBox message="컷오프 시계열을 표시할 데이터가 없습니다." />
                  )}
                </div>
              </div>
            </div>
          </div>

          <div id="snapshot-compare" className={styles.anchorTarget}>
            {filteredCompareCandidates.length < 2 ? null : !canCompareSnapshots ? (
              <ErrorBox message="같은 스냅샷 두 개는 비교할 수 없습니다." />
            ) : comparisonHasError || compareResults === null ? (
              <ErrorBox message="스냅샷 비교 데이터를 불러오지 못했습니다." />
            ) : (
              <SnapshotComparisonPanel
                leftSnapshot={selectedCompareLeft}
                rightSnapshot={selectedCompareRight}
                leftSummary={compareResults[0].data!}
                rightSummary={compareResults[1].data!}
                leftCutoffs={compareResults[2].data!}
                rightCutoffs={compareResults[3].data!}
                leftDistribution={compareResults[4].data!}
                rightDistribution={compareResults[5].data!}
                leftValidationReport={compareResults[6].data!}
                rightValidationReport={compareResults[7].data!}
              />
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}

function formatStatusLabel(status: string) {
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

function formatSourceTypeLabel(sourceType: string) {
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

function formatCollectorFilterLabel(value: string) {
  switch (value) {
    case "with_diagnostics":
      return "진단 포함";
    case "capture_stop":
      return "캡처 중단";
    case "hard_ocr_stop":
      return "강한 OCR 중단";
    default:
      return value;
  }
}

function formatPipelineStopSourceLabel(value: string) {
  switch (value) {
    case "capture":
      return "캡처";
    case "ocr":
      return "OCR";
    default:
      return value;
  }
}

function formatIgnoredGroupLabel(value: string) {
  switch (value) {
    case "overlay":
      return "오버레이";
    case "header":
      return "헤더/페이지";
    case "malformed":
      return "비정상 엔트리";
    default:
      return value;
  }
}

function formatPageSignalLabel(value: string) {
  switch (value) {
    case "empty":
      return "빈 페이지";
    case "sparse":
      return "Sparse";
    case "overlapping":
      return "중복";
    case "stale":
      return "Stale";
    case "noisy":
      return "Noise";
    default:
      return value;
  }
}

function formatOcrStopLevelLabel(value: string) {
  switch (value) {
    case "soft":
      return "약함";
    case "hard":
      return "강함";
    default:
      return value;
  }
}
