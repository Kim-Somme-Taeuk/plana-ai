import {
  PublicCutoffHighlightPanel,
  PublicDistributionPanel,
  PublicEmptyBox,
  PublicErrorBox,
  PublicShell,
  PublicSnapshotContextPanel,
  PublicRecentSnapshotPanel,
  PublicSnapshotSummaryPanel,
  PublicTrendPanel,
} from "../../../components/public-dashboard";
import {
  getSeason,
  getSeasonCutoffSeries,
  getSeasonSnapshots,
  getSnapshot,
  getSnapshotCutoffs,
  getSnapshotDistribution,
  getSnapshotSummary,
} from "../../../lib/api";

export const dynamic = "force-dynamic";

type PublicSnapshotPageProps = {
  params: Promise<{ snapshotId: string }>;
};

export default async function PublicSnapshotPage({
  params,
}: PublicSnapshotPageProps) {
  const { snapshotId } = await params;
  const numericSnapshotId = Number(snapshotId);
  const snapshotResult = await getSnapshot(numericSnapshotId);

  if (snapshotResult.error || !snapshotResult.data) {
    return (
      <PublicShell
        eyebrow="공개 스냅샷 상세"
        title={`스냅샷 #${snapshotId}`}
        subtitle="대표 컷오프와 통계를 중심으로 보는 공개용 스냅샷 상세 화면입니다."
      >
        <PublicErrorBox
          message={`스냅샷 정보를 불러오지 못했습니다. ${
            snapshotResult.error ?? "대상을 찾을 수 없습니다."
          }`}
        />
      </PublicShell>
    );
  }

  const snapshot = snapshotResult.data;
  const [
    seasonResult,
    seasonSnapshotsResult,
    summaryResult,
    cutoffsResult,
    distributionResult,
    seriesResult,
  ] =
    await Promise.all([
      getSeason(snapshot.season_id),
      getSeasonSnapshots(snapshot.season_id),
      getSnapshotSummary(snapshot.id),
      getSnapshotCutoffs(snapshot.id),
      getSnapshotDistribution(snapshot.id),
      getSeasonCutoffSeries(snapshot.season_id, 1000),
    ]);

  if (seasonResult.error || !seasonResult.data) {
    return (
      <PublicShell
        eyebrow="공개 스냅샷 상세"
        title={`스냅샷 #${snapshot.id}`}
        subtitle="대표 컷오프와 통계를 중심으로 보는 공개용 스냅샷 상세 화면입니다."
      >
        <PublicErrorBox
          message={`시즌 정보를 불러오지 못했습니다. ${
            seasonResult.error ?? "알 수 없는 오류입니다."
          }`}
        />
      </PublicShell>
    );
  }

  const season = seasonResult.data;
  const completedSnapshots = (seasonSnapshotsResult.data ?? [])
    .filter((item) => item.status === "completed")
    .sort((left, right) => new Date(right.captured_at).getTime() - new Date(left.captured_at).getTime());
  const currentIndex = completedSnapshots.findIndex((item) => item.id === snapshot.id);
  const newerSnapshot = currentIndex > 0 ? completedSnapshots[currentIndex - 1] : null;
  const olderSnapshot =
    currentIndex >= 0 && currentIndex < completedSnapshots.length - 1
      ? completedSnapshots[currentIndex + 1]
      : null;

  return (
    <PublicShell
      eyebrow="공개 스냅샷 상세"
      title={`스냅샷 #${snapshot.id}`}
      subtitle="운영 진단 정보 없이, 사용자에게 필요한 컷오프와 분포만 깔끔하게 보여줍니다."
    >
      {summaryResult.data ? (
        <PublicSnapshotSummaryPanel snapshot={snapshot} summary={summaryResult.data} />
      ) : (
        <PublicErrorBox
          message={`스냅샷 요약을 불러오지 못했습니다. ${
            summaryResult.error ?? "알 수 없는 오류입니다."
          }`}
        />
      )}

      <PublicSnapshotContextPanel
        season={season}
        snapshot={snapshot}
        currentIndex={currentIndex >= 0 ? currentIndex : null}
        completedSnapshotCount={completedSnapshots.length}
        newerSnapshot={newerSnapshot}
        olderSnapshot={olderSnapshot}
      />

      {summaryResult.data && cutoffsResult.data ? (
        <PublicCutoffHighlightPanel
          seasonId={season.id}
          snapshot={snapshot}
          summary={summaryResult.data}
          cutoffs={cutoffsResult.data.cutoffs}
        />
      ) : (
        <PublicEmptyBox message="대표 컷오프를 아직 표시할 수 없습니다." />
      )}

      {distributionResult.data ? (
        <PublicDistributionPanel distribution={distributionResult.data} />
      ) : (
        <PublicErrorBox
          message={`분포 요약을 불러오지 못했습니다. ${
            distributionResult.error ?? "알 수 없는 오류입니다."
          }`}
        />
      )}

      {seriesResult.data ? (
        <PublicTrendPanel
          title="순위 1,000 컷오프 흐름"
          description="이 스냅샷이 속한 시즌의 대표 컷오프 시계열입니다."
          series={seriesResult.data}
          snapshotHrefBuilder={(id) => `/rankings/snapshots/${id}`}
          currentSnapshotId={snapshot.id}
        />
      ) : (
        <PublicErrorBox
          message={`시즌 컷오프 시계열을 불러오지 못했습니다. ${
            seriesResult.error ?? "알 수 없는 오류입니다."
          }`}
        />
      )}

      <PublicRecentSnapshotPanel
        snapshots={completedSnapshots.slice(0, 8)}
        snapshotHrefBuilder={(id) => `/rankings/snapshots/${id}`}
        currentSnapshotId={snapshot.id}
      />
    </PublicShell>
  );
}
