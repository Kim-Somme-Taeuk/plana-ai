import { LoadingBox, PageShell } from "../../components/dashboard";

export default function Loading() {
  return (
    <PageShell
      eyebrow="로딩 중"
      title="스냅샷 정보를 불러오는 중입니다"
      subtitle="요약, 컷오프, 분포, 엔트리를 준비하고 있습니다."
      backHref="/"
      backLabel="시즌 목록으로"
    >
      <LoadingBox message="스냅샷 상세 데이터를 불러오는 중입니다." />
    </PageShell>
  );
}
