import {
  FeaturedSeasonPanel,
  PublicCutoffHighlightPanel,
  PublicDistributionPanel,
  PublicEmptyBox,
  PublicErrorBox,
  PublicSeasonGrid,
  PublicShell,
  PublicTrendPanel,
} from "./components/public-dashboard";
import {
  getSeasons,
  getSeasonSnapshots,
  getSeasonCutoffSeries,
  getSnapshotCutoffs,
  getSnapshotDistribution,
  getSnapshotSummary,
} from "./lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const seasonsResult = await getSeasons();
  const seasons =
    seasonsResult.data?.slice().sort((left, right) => {
      const leftTimestamp = left.started_at ? new Date(left.started_at).getTime() : 0;
      const rightTimestamp = right.started_at ? new Date(right.started_at).getTime() : 0;

      if (leftTimestamp !== rightTimestamp) {
        return rightTimestamp - leftTimestamp;
      }

      return right.id - left.id;
    }) ?? [];
  const featuredSeason = seasons[0] ?? null;
  const featuredSnapshotsResult = featuredSeason
    ? await getSeasonSnapshots(featuredSeason.id)
    : { data: null, error: null, status: 200 };
  const featuredSnapshots = (featuredSnapshotsResult.data ?? []).sort(
    (left, right) =>
      new Date(right.captured_at).getTime() - new Date(left.captured_at).getTime(),
  );
  const latestCompletedSnapshot =
    featuredSnapshots.find((snapshot) => snapshot.status === "completed") ?? null;
  const [summaryResult, cutoffsResult, distributionResult, seriesResult] =
    featuredSeason && latestCompletedSnapshot
      ? await Promise.all([
          getSnapshotSummary(latestCompletedSnapshot.id),
          getSnapshotCutoffs(latestCompletedSnapshot.id),
          getSnapshotDistribution(latestCompletedSnapshot.id),
          getSeasonCutoffSeries(featuredSeason.id, 1000),
        ])
      : [
          { data: null, error: null, status: 200 },
          { data: null, error: null, status: 200 },
          { data: null, error: null, status: 200 },
          featuredSeason
            ? await getSeasonCutoffSeries(featuredSeason.id, 1000)
            : { data: null, error: null, status: 200 },
        ];

  return (
    <PublicShell
      eyebrow="Blue Archive Ranking"
      title="블루 아카이브 시즌 대시보드"
      subtitle="일반 사용자가 최근 컷오프와 시즌 흐름을 빠르게 볼 수 있게 정리한 공개용 홈입니다."
    >
      {seasonsResult.error ? (
        <PublicErrorBox
          message={`시즌 목록을 불러오지 못했습니다. ${seasonsResult.error}`}
        />
      ) : featuredSeason ? (
        <>
          <FeaturedSeasonPanel
            season={featuredSeason}
            latestSnapshot={latestCompletedSnapshot}
            summary={summaryResult.data}
          />

          {latestCompletedSnapshot && summaryResult.data && cutoffsResult.data ? (
            <PublicCutoffHighlightPanel
              seasonId={featuredSeason.id}
              snapshot={latestCompletedSnapshot}
              summary={summaryResult.data}
              cutoffs={cutoffsResult.data.cutoffs}
            />
          ) : (
            <PublicEmptyBox message="대표 컷오프를 보여줄 완료 스냅샷이 아직 없습니다." />
          )}

          {distributionResult.data ? (
            <PublicDistributionPanel distribution={distributionResult.data} />
          ) : null}

          {seriesResult.data ? (
            <PublicTrendPanel
              title="순위 1,000 컷오프 흐름"
              description="최근 시즌의 완료 스냅샷 기준으로 대표 컷오프 흐름을 보여줍니다."
              series={seriesResult.data}
            />
          ) : null}

          <PublicSeasonGrid seasons={seasons} />
        </>
      ) : (
        <PublicEmptyBox message="표시할 시즌이 아직 없습니다." />
      )}
    </PublicShell>
  );
}
