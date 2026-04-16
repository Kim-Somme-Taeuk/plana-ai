import { LoadingBox, PageShell } from "../../components/dashboard";

export default function Loading() {
  return (
    <PageShell
      eyebrow="로딩 중"
      title="시즌 정보를 불러오는 중입니다"
      subtitle="스냅샷 목록과 컷오프 시계열을 준비하고 있습니다."
      backHref="/"
      backLabel="시즌 목록으로"
    >
      <LoadingBox message="시즌 상세 정보를 불러오는 중입니다." />
    </PageShell>
  );
}
