import { LoadingBox, PageShell } from "./components/dashboard";

export default function Loading() {
  return (
    <PageShell
      eyebrow="로딩 중"
      title="데이터를 불러오는 중입니다"
      subtitle="시즌 목록을 준비하고 있습니다."
    >
      <LoadingBox message="시즌 목록을 불러오는 중입니다." />
    </PageShell>
  );
}
