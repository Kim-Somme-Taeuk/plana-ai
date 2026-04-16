# frontend

`plana-ai`의 Next.js 기반 대시보드입니다.

현재 frontend는 backend API를 직접 읽어서 시즌, snapshot, 통계, entry 데이터를 탐색하는 1차 화면을 제공합니다.

## 현재 구현 화면

### `/`

시즌 목록 페이지입니다.

- `GET /seasons`
- 시즌 카드 표시
- 로딩 / 에러 / 빈 상태 처리

### `/seasons/[seasonId]`

시즌 상세 페이지입니다.

- `GET /seasons/{season_id}`
- `GET /seasons/{season_id}/ranking-snapshots`
- `GET /seasons/{season_id}/cutoff-series?rank=...`
- `GET /seasons/{season_id}/validation-overview`
- `GET /seasons/{season_id}/validation-series`
- 시즌 요약
- season validation overview / validation series / issue 집계
- season validation overview / validation series에서 collector 진단 집계와 stop 힌트 표시
- season 상세에서 `collector=with_diagnostics|capture_stop|hard_ocr_stop` 필터로 품질 패널과 compare 후보를 좁혀볼 수 있음
- season validation overview에서 capture stop / OCR stop / ignored OCR reason 집계를 테이블로 확인 가능
- snapshot 목록
- snapshot 목록에서 invalid ratio / top issue 표시
- snapshot status / source 필터
- snapshot compare 패널
- snapshot compare에서 validation issue delta 비교
- snapshot compare에서 collector stop / ignored OCR line 비교
- snapshot compare에서 left/right invalid, top issue drilldown 링크 제공
- validation series에서 바로 이전 snapshot과 compare 링크 제공
- validation series에서 invalid entry / top issue / snapshot 상세로 바로 drilldown
- season validation overview / validation series는 현재 선택된 `status` / `source` 필터와 같이 움직임
- snapshot compare 후보와 cutoff-series도 현재 선택된 `source` 필터 기준으로 좁혀짐
- cutoff-series 표시
- 로딩 / 에러 / 빈 상태 처리

### `/snapshots/[snapshotId]`

snapshot 상세 페이지입니다.

- `GET /ranking-snapshots/{snapshot_id}`
- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
- `GET /ranking-snapshots/{snapshot_id}/entries`
- summary / cutoffs / distribution / entries 표시
- validation report 표시
- validation report에 collector 진단 요약 표시
- `is_valid`, `validation_issue`, `sort_by`, `order`, `limit`, `offset` 기반 entry 조회 제어
- validation issue 집계 패널 표시
- snapshot 상세에서 issue code 클릭 시 해당 issue로 바로 필터링
- 로딩 / 에러 / 빈 상태 처리

## API 연결 방식

frontend는 server component 기반 fetch helper를 사용합니다.

우선순위:

1. `BACKEND_INTERNAL_URL`
2. `API_BASE_URL`
3. `http://localhost:8000`
4. `http://backend:8000`

즉:

- 로컬 host 개발 환경에서는 기본적으로 `localhost:8000`
- docker compose 환경에서는 `backend:8000`
를 사용할 수 있습니다.

## 실행

```bash
cd frontend
npm install
npm run dev
```

브라우저:

- `http://localhost:3000`

## 품질 확인

```bash
cd frontend
npm run lint
npm run build
```

루트 기준 smoke 검증:

```bash
bash scripts/smoke.sh
```

빈 DB를 seed한 뒤 docker 경로까지 확인하는 CI용 smoke:

```bash
bash scripts/ci_smoke.sh
```

## 구조

- `app/page.tsx`
  시즌 목록 페이지
- `app/seasons/[seasonId]/page.tsx`
  시즌 상세 페이지
- `app/snapshots/[snapshotId]/page.tsx`
  snapshot 상세 페이지
- `app/components/dashboard.tsx`
  공통 대시보드 UI 컴포넌트
- `app/lib/api.ts`
  backend fetch helper
- `app/lib/types.ts`
  frontend API 타입 정의

## 주의사항

- 이 frontend는 현재 backend API 스펙에 강하게 맞춰져 있습니다.
- 통계 정책은 backend를 따르므로, invalid entry는 표시될 수 있어도 통계 계산에서는 제외됩니다.
- 별도 상태관리 라이브러리는 도입하지 않았고, 1차 버전은 단순한 서버 렌더링 중심 구조입니다.
