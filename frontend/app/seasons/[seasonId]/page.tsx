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
    ignoredReason?: string;
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
  const selectedIgnoredReason =
    resolvedSearchParams.ignoredReason && resolvedSearchParams.ignoredReason.trim()
      ? resolvedSearchParams.ignoredReason
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
        ignoredReason:
          selectedIgnoredReason === "all" ? undefined : selectedIgnoredReason,
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
        ignoredReason:
          selectedIgnoredReason === "all" ? undefined : selectedIgnoredReason,
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
        selectedIgnoredReason !== "all" ||
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

  return (
    <PageShell
      eyebrow="시즌 상세"
      title={season?.season_label ?? `시즌 #${seasonId}`}
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
        <div className={styles.grid}>
          <div className={`${styles.grid} ${styles.twoColumn}`}>
            <div className={`${styles.grid} ${styles.rightRail}`}>
            <SeasonSummary season={season} />

            {validationOverviewResult.error || !validationOverviewResult.data ? (
              <ErrorBox
                message={`검증 개요를 불러오지 못했습니다. ${
                  validationOverviewResult.error ?? "알 수 없는 오류입니다."
                }`}
              />
            ) : (
              <>
                <SeasonValidationOverviewPanel
                  overview={validationOverviewResult.data}
                  seasonId={numericSeasonId}
                  selectedStatus={selectedStatus}
                  selectedSource={selectedSource}
                  selectedCollector={selectedCollector}
                  selectedCaptureStopReason={selectedCaptureStopReason}
                  selectedOcrStopReason={selectedOcrStopReason}
                  selectedIgnoredReason={selectedIgnoredReason}
                  selectedOcrStopLevel={selectedOcrStopLevel}
                />
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
                    compareRank={seriesRank}
                    collectorFilter={selectedCollector}
                    selectedStatus={selectedStatus}
                    selectedSource={selectedSource}
                    captureStopReason={selectedCaptureStopReason}
                    ocrStopReason={selectedOcrStopReason}
                    ignoredReason={selectedIgnoredReason}
                    ocrStopLevel={selectedOcrStopLevel}
                  />
                )}
                <ValidationIssuesPanel
                  issues={validationOverviewResult.data.validation_issues}
                />
              </>
            )}

            <section className={styles.panel}>
              <div className={styles.panelTitle}>
                <h2>스냅샷</h2>
                <span className={styles.muted}>
                  수집 상태와 행 수를 빠르게 확인합니다.
                </span>
              </div>
              <form className={styles.controls}>
                <div className={styles.controlRow}>
                  <div className={styles.field}>
                    <label htmlFor="status">상태</label>
                    <select
                      id="status"
                      name="status"
                      defaultValue={selectedStatus}
                    >
                      <option value="all">전체</option>
                      <option value="completed">완료</option>
                      <option value="collecting">수집 중</option>
                      <option value="failed">실패</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="source">입력 소스</label>
                    <select
                      id="source"
                      name="source"
                      defaultValue={selectedSource}
                    >
                      <option value="all">전체</option>
                      {sourceOptions.map((sourceType) => (
                        <option key={sourceType} value={sourceType}>
                          {formatSourceTypeLabel(sourceType)}
                        </option>
                      ))}
                    </select>
                  </div>
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
                  <input type="hidden" name="rank" value={String(seriesRank)} />
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
                  <button type="submit" className={styles.button}>
                    적용
                  </button>
                </div>
              </form>
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

            <div className={styles.grid}>
              <section className={styles.panel}>
                <div className={styles.panelTitle}>
                  <h2>컷오프 시계열 설정</h2>
                </div>
                <form className={styles.controls}>
                  <div className={styles.controlRow}>
                    <div className={styles.field}>
                      <label htmlFor="rank">순위</label>
                      <select id="rank" name="rank" defaultValue={String(seriesRank)}>
                        {SERIES_RANK_OPTIONS.map((rank) => (
                          <option key={rank} value={rank}>
                            {rank.toLocaleString()}
                          </option>
                        ))}
                      </select>
                    </div>
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
                      name="ignoredReason"
                      value={selectedIgnoredReason}
                    />
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
                    <button type="submit" className={styles.button}>
                      갱신
                    </button>
                  </div>
                </form>
                <p className={styles.muted}>
                  완료된 스냅샷만 시계열에 포함됩니다.
                </p>
              </section>

              <section className={styles.panel}>
                <div className={styles.panelTitle}>
                  <h2>스냅샷 비교 설정</h2>
                  <span className={styles.muted}>
                    최근 스냅샷 두 개를 기본 비교 대상으로 잡습니다.
                  </span>
                </div>
                {filteredCompareCandidates.length < 2 ? (
                  <EmptyBox message="비교하려면 스냅샷이 두 개 이상 필요합니다." />
                ) : (
                  <form className={styles.controls}>
                    <div className={styles.controlRow}>
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
                      <input type="hidden" name="rank" value={String(seriesRank)} />
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
                        name="ignoredReason"
                        value={selectedIgnoredReason}
                      />
                      <input
                        type="hidden"
                        name="ocrStopLevel"
                        value={selectedOcrStopLevel}
                      />
                      <button type="submit" className={styles.button}>
                        비교
                      </button>
                    </div>
                  </form>
                )}
              </section>

              {seriesResult.error ? (
                <ErrorBox
                  message={`컷오프 시계열을 불러오지 못했습니다. ${seriesResult.error}`}
                />
              ) : seriesResult.data ? (
                <CutoffSeriesPanel series={seriesResult.data} />
              ) : (
                <EmptyBox message="컷오프 시계열을 표시할 데이터가 없습니다." />
              )}

              <section className={styles.panel}>
                <div className={styles.panelTitle}>
                  <h2>빠른 이동</h2>
                </div>
                <div className={styles.panelBody}>
                  <p className={styles.muted}>
                    스냅샷 카드를 클릭하면 상세 통계와 엔트리 목록 화면으로 이동합니다.
                  </p>
                  <div className={styles.paginationLinks}>
                    <Link href="/" className={styles.linkButton}>
                      시즌 목록
                    </Link>
                  </div>
                </div>
              </section>
            </div>
          </div>

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
