import { LoadingBox, PageShell } from "../../components/dashboard";

export default function Loading() {
  return (
    <PageShell
      eyebrow="Loading"
      title="시즌 정보를 불러오는 중입니다"
      subtitle="snapshot 목록과 cutoff-series를 준비하고 있습니다."
      backHref="/"
      backLabel="시즌 목록으로"
    >
      <LoadingBox message="시즌 상세 정보를 불러오는 중입니다." />
    </PageShell>
  );
}
