import {
  EmptyBox,
  ErrorBox,
  PageShell,
  SeasonList,
} from "./components/dashboard";
import { getSeasons } from "./lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const seasonsResult = await getSeasons();

  return (
    <PageShell
      eyebrow="Season Dashboard"
      title="시즌 목록"
      subtitle="현재 저장된 시즌을 확인하고, 시즌별 snapshot과 통계를 탐색할 수 있습니다."
    >
      {seasonsResult.error ? (
        <ErrorBox
          message={`시즌 목록을 불러오지 못했습니다. ${seasonsResult.error}`}
        />
      ) : seasonsResult.data && seasonsResult.data.length > 0 ? (
        <SeasonList seasons={seasonsResult.data} />
      ) : (
        <EmptyBox message="표시할 시즌이 아직 없습니다." />
      )}
    </PageShell>
  );
}
