# frontend

`plana-ai`의 Next.js 기반 운영 대시보드입니다.

현재 frontend는 backend API를 직접 읽어서 시즌, snapshot, 통계, validation, collector diagnostics를 탐색하는 운영용 화면을 제공합니다.

## 현재 구현 화면

### `/`

시즌 목록 페이지입니다.

- `GET /seasons`
- 시즌 카드 표시
- 로딩 / 에러 / 빈 상태 처리

### `/seasons/[seasonId]`

시즌 상세 페이지입니다.

사용 API:

- `GET /seasons/{season_id}`
- `GET /seasons/{season_id}/ranking-snapshots`
- `GET /seasons/{season_id}/cutoff-series?rank=...`
- `GET /seasons/{season_id}/validation-overview`
- `GET /seasons/{season_id}/validation-series`

주요 UI:

- 시즌 요약
- validation overview
- validation series
- validation issue 집계
- page quality signal 집계
- collector stop / ignored OCR / pipeline stop 집계
- snapshot 목록
- snapshot compare
- cutoff series
- 빠른 이동

현재 drilldown 범위:

- `status`
- `source`
- `collector`
- `captureStopReason`
- `ocrStopReason`
- `pipelineStopReason`
- `pipelineStopSource`
- `pipelineStopLevel`
- `ignoredReason`
- `ignoredGroup`
- `pageSignal`
- `ocrStopLevel`

즉, season 상세 하나에서 validation/collector 품질 신호를 여러 기준으로 계속 좁혀볼 수 있습니다.

### `/snapshots/[snapshotId]`

snapshot 상세 페이지입니다.

사용 API:

- `GET /ranking-snapshots/{snapshot_id}`
- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
- `GET /ranking-snapshots/{snapshot_id}/entries`

주요 UI:

- summary
- validation report
- collector diagnostics
- page quality signal
- cutoffs
- distribution
- entries table
- `is_valid`, `validation_issue`, `limit`, `offset`, `sort_by`, `order` 기반 탐색

snapshot 상세에서는 issue code, collector stop, ignored group, page signal 기준으로 다시 시즌 상세 drilldown도 가능합니다.

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

## smoke

로컬 smoke:

```bash
bash scripts/smoke.sh
```

CI/빈 DB smoke:

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
- `app/dashboard.module.css`
  dashboard 전용 스타일

## 현재 UX 성격

현재 화면은 일반 사용자 소비형 UI보다 운영자/개발자용 탐색 UI에 가깝습니다.

즉, 아래를 우선합니다.

- 스냅샷 품질 비교
- invalid issue drilldown
- collector stop/ignored OCR 신호 확인
- 모바일 포함 기본 반응형 운영 화면

## 주의사항

- 이 frontend는 현재 backend API 응답 구조에 직접 의존합니다.
- 통계 정책은 backend를 따르므로 invalid entry는 표시될 수 있어도 통계 계산에서는 제외됩니다.
- 별도 상태관리 라이브러리는 도입하지 않았고, 서버 렌더링 중심 구조입니다.
