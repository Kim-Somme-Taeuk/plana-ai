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
- 시즌 요약
- snapshot 목록
- cutoff-series 표시
- 로딩 / 에러 / 빈 상태 처리

### `/snapshots/[snapshotId]`

snapshot 상세 페이지입니다.

- `GET /ranking-snapshots/{snapshot_id}`
- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
- `GET /ranking-snapshots/{snapshot_id}/entries`
- summary / cutoffs / distribution / entries 표시
- `is_valid`, `validation_issue`, `sort_by`, `order` 기반 entry 조회 제어
- validation issue 집계 패널 표시
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
