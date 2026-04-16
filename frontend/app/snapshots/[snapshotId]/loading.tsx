import { LoadingBox, PageShell } from "../../components/dashboard";

export default function Loading() {
  return (
    <PageShell
      eyebrow="Loading"
      title="snapshot 정보를 불러오는 중입니다"
      subtitle="summary, cutoffs, distribution, entries를 준비하고 있습니다."
      backHref="/"
      backLabel="시즌 목록으로"
    >
      <LoadingBox message="snapshot 상세 데이터를 불러오는 중입니다." />
    </PageShell>
  );
}
