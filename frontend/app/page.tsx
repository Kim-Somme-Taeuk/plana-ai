export default function Home() {
  return (
    <main style={{ padding: "32px", fontFamily: "sans-serif" }}>
      <h1>plana-ai</h1>
      <p>블루 아카이브 총력전/대결전 통계 대시보드 프론트엔드</p>

      <section style={{ marginTop: "24px" }}>
        <h2>예정 기능</h2>
        <ul>
          <li>시즌 선택</li>
          <li>서버 선택</li>
          <li>컷라인 그래프</li>
          <li>점수 분포</li>
          <li>특정 순위 시계열</li>
        </ul>
      </section>
    </main>
  );
}
