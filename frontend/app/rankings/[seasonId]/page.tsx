import {
  FeaturedSeasonPanel,
  PublicCutoffHighlightPanel,
  PublicDistributionPanel,
  PublicEmptyBox,
  PublicErrorBox,
  PublicRecentSnapshotPanel,
  PublicRankSelector,
  PublicShell,
  PublicTrendPanel,
} from "../../components/public-dashboard";
import {
  getSeason,
  getSeasonCutoffSeries,
  getSeasonSnapshots,
  getSnapshotCutoffs,
  getSnapshotDistribution,
  getSnapshotSummary,
} from "../../lib/api";

export const dynamic = "force-dynamic";

type PublicSeasonPageProps = {
  params: Promise<{ seasonId: string }>;
  searchParams: Promise<{ rank?: string }>;
};

export default async function PublicSeasonPage({
  params,
  searchParams,
}: PublicSeasonPageProps) {
  const { seasonId } = await params;
  const resolvedSearchParams = await searchParams;
  const numericSeasonId = Number(seasonId);
  const selectedRank = Number(resolvedSearchParams.rank ?? "1000");
  const normalizedRank = Number.isNaN(selectedRank) ? 1000 : selectedRank;

  const [seasonResult, snapshotsResult] = await Promise.all([
    getSeason(numericSeasonId),
    getSeasonSnapshots(numericSeasonId),
  ]);

  if (seasonResult.error || !seasonResult.data) {
    return (
      <PublicShell
        eyebrow="공개 시즌 상세"
        title={`시즌 #${seasonId}`}
        subtitle="시즌 컷오프와 최근 완료 스냅샷 흐름을 보여주는 공개 화면입니다."
      >
        <PublicErrorBox
          message={`시즌 정보를 불러오지 못했습니다. ${
            seasonResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      </PublicShell>
    );
  }

  const season = seasonResult.data;
  const snapshots = (snapshotsResult.data ?? []).sort(
    (left, right) =>
      new Date(right.captured_at).getTime() - new Date(left.captured_at).getTime(),
  );
  const completedSnapshots = snapshots.filter((snapshot) => snapshot.status === "completed");
  const latestCompletedSnapshot = completedSnapshots[0] ?? null;

  const [summaryResult, cutoffsResult, distributionResult, seriesResult] =
    latestCompletedSnapshot
      ? await Promise.all([
          getSnapshotSummary(latestCompletedSnapshot.id),
          getSnapshotCutoffs(latestCompletedSnapshot.id),
          getSnapshotDistribution(latestCompletedSnapshot.id),
          getSeasonCutoffSeries(season.id, normalizedRank),
        ])
      : [
          { data: null, error: null, status: 200 },
          { data: null, error: null, status: 200 },
          { data: null, error: null, status: 200 },
          await getSeasonCutoffSeries(season.id, normalizedRank),
        ];

  return (
    <PublicShell
      eyebrow="공개 시즌 상세"
      title={season.season_label}
      subtitle="최근 완료 스냅샷 기준 대표 컷오프와 시즌 시계열을 중심으로 보여줍니다."
    >
      <FeaturedSeasonPanel
        season={season}
        latestSnapshot={latestCompletedSnapshot}
        summary={summaryResult.data}
        latestSnapshotHref={
          latestCompletedSnapshot
            ? `/rankings/snapshots/${latestCompletedSnapshot.id}`
            : null
        }
      />

      <PublicRankSelector seasonId={season.id} selectedRank={normalizedRank} />

      {latestCompletedSnapshot && summaryResult.data && cutoffsResult.data ? (
        <PublicCutoffHighlightPanel
          seasonId={season.id}
          snapshot={latestCompletedSnapshot}
          summary={summaryResult.data}
          cutoffs={cutoffsResult.data.cutoffs}
        />
      ) : (
        <PublicEmptyBox message="완료된 스냅샷이 없어 대표 컷오프를 아직 표시할 수 없습니다." />
      )}

      {distributionResult.data ? (
        <PublicDistributionPanel distribution={distributionResult.data} />
      ) : null}

      {seriesResult.error || !seriesResult.data ? (
        <PublicErrorBox
          message={`컷오프 시계열을 불러오지 못했습니다. ${
            seriesResult.error ?? "알 수 없는 오류입니다."
          }`}
        />
      ) : (
        <PublicTrendPanel
          title={`순위 ${normalizedRank.toLocaleString()} 컷오프 시계열`}
          description="완료된 스냅샷만 기준으로 컷오프 변화 흐름을 보여줍니다."
          series={seriesResult.data}
          snapshotHrefBuilder={(id) => `/rankings/snapshots/${id}`}
        />
      )}

      <PublicRecentSnapshotPanel
        snapshots={completedSnapshots.slice(0, 8)}
        snapshotHrefBuilder={(id) => `/rankings/snapshots/${id}`}
      />
    </PublicShell>
  );
}
