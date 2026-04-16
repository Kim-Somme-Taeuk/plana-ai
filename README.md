# plana-ai

블루 아카이브 총력전/대결전 랭킹 데이터를 수집, 저장, 검증, 통계화하고 웹 대시보드로 확인하는 풀스택 프로젝트입니다.

이 저장소는 단순 CRUD 앱이 아니라 아래 흐름 전체를 포함하는 데이터 파이프라인 서비스입니다.

1. 시즌 메타데이터 생성
2. 특정 시점의 ranking snapshot 생성
3. snapshot 안의 ranking entries 저장
4. entry validation 적용
5. snapshot 상태를 `collecting / completed / failed`로 관리
6. valid entry 기준 통계 계산
7. frontend 대시보드에서 시즌/스냅샷/통계/엔트리 탐색
8. mock collector 및 image capture import로 전체 시스템 검증

## 목표

- 시즌별 랭킹 데이터를 저장할 수 있어야 함
- 특정 시점(snapshot)의 순위표를 저장할 수 있어야 함
- 개별 ranking entry를 저장하고 검증할 수 있어야 함
- snapshot 및 season 단위의 통계를 계산할 수 있어야 함
- frontend 대시보드에서 데이터를 탐색할 수 있어야 함
- 실제 OCR/ADB 기반 collector 이전에 mock/capture 기반으로 전체 파이프라인을 검증할 수 있어야 함
- invalid 데이터도 버리지 않고 저장하되, 통계에서는 제외할 수 있어야 함

## 저장소 구조

- `backend/`
  FastAPI + SQLAlchemy + PostgreSQL 기반 API 서버
- `frontend/`
  Next.js App Router 기반 대시보드
- `collector/`
  mock import와 image capture import를 포함한 collector 실험 영역
- `docs/`
  프로젝트 보조 문서
- `infra/`
  인프라 관련 설정 확장 공간

## 핵심 데이터 모델

### `seasons`

시즌 메타데이터를 저장합니다.

- `event_type`
- `server`
- `boss_name`
- `armor_type`
- `terrain`
- `season_label`
- `started_at`
- `ended_at`

주의:

- `season_label`은 unique 입니다.
- 현재 스키마에는 별도 “시즌 번호” 컬럼이 없고, 사람이 읽는 시즌 식별은 `season_label`에 담는 구조입니다.

### `ranking_snapshots`

특정 season 안의 특정 수집 시점을 저장합니다.

- `season_id`
- `captured_at`
- `source_type`
- `status`
- `total_rows_collected`
- `note`

상태 정책:

- `collecting -> completed` 허용
- `collecting -> failed` 허용
- `completed -> collecting` 금지
- `failed -> collecting` 금지
- `completed -> failed` 금지
- 같은 상태로 다시 PATCH 하는 no-op 요청은 허용
- `completed` 전이 시 entry 개수로 `total_rows_collected`를 갱신

### `ranking_entries`

특정 snapshot 안의 개별 랭킹 row 를 저장합니다.

- `ranking_snapshot_id`
- `rank`
- `score`
- `player_name`
- `ocr_confidence`
- `raw_text`
- `image_path`
- `is_valid`
- `validation_issue`

제약:

- `(ranking_snapshot_id, rank)` unique
- invalid entry도 저장 가능
- 통계 계산에서는 `is_valid=true`만 사용

## 현재 구현 범위

### 완료된 작업 요약

현재 저장소 기준으로 아래 단계가 완료된 상태입니다.

1. `ranking_entries` 저장/조회 API 구현
2. `ranking_snapshots` 상태 전이 workflow 구현
3. snapshot/season 통계 API 1차 구현
4. frontend 대시보드 1차 구현
5. mock collector import pipeline 구현
6. validation 1차 및 actual capture import 1차 구현
7. validation report API 및 dashboard 2차 가시성 보강

최근 단계별 의미는 아래와 같습니다.

- 1단계
  `POST /ranking-snapshots/{snapshot_id}/entries`,
  `GET /ranking-snapshots/{snapshot_id}/entries`,
  `GET /ranking-entries/{entry_id}` 및 조회 옵션 구현
- 2단계
  snapshot status workflow, `completed` 시 `total_rows_collected` 반영, terminal 상태 보호
- 3단계
  `summary`, `cutoffs`, `distribution`, `cutoff-series` 통계 API 구현
- 4단계
  시즌 목록 / 시즌 상세 / snapshot 상세 대시보드 구현
- 5단계
  JSON 기반 mock import와 sample data, 실행 문서 추가
- 6단계
  entry validation 코드 체계, invalid 저장 정책, capture manifest 기반 실제 collector 1차 추가
- 7단계
  snapshot validation report API, integrated capture pipeline, duplicate-frame 조기 종료, dashboard validation report 표시 추가

### 현재 안정 상태

현재 인수인계 시점에서 신뢰할 수 있는 상태는 다음과 같습니다.

- backend API, collector, frontend가 서로 연결된 상태입니다.
- invalid entry는 저장되지만 statistics에서는 제외됩니다.
- snapshot status는 `collecting / completed / failed` 정책으로 동작합니다.
- mock import와 image capture import 둘 다 backend API를 재사용합니다.
- frontend는 현재 backend API 응답 구조를 그대로 소비합니다.
- backend + collector 테스트와 frontend lint/build가 통과 가능한 상태입니다.

### backend API

기본 저장/조회 API:

- `POST /seasons`
- `GET /seasons`
- `GET /seasons/{season_id}`
- `POST /seasons/{season_id}/ranking-snapshots`
- `GET /seasons/{season_id}/ranking-snapshots`
- `GET /ranking-snapshots/{snapshot_id}`
- `PATCH /ranking-snapshots/{snapshot_id}/status`
- `POST /ranking-snapshots/{snapshot_id}/entries`
- `GET /ranking-snapshots/{snapshot_id}/entries`
- `GET /ranking-entries/{entry_id}`

entry 조회 사용성:

- `is_valid` 필터
- `limit / offset`
- `sort_by=rank|score`
- `order=asc|desc`
- 기본 정렬은 `rank ASC`

통계 API:

- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
- `GET /seasons/{season_id}/cutoff-series`
- `GET /seasons/{season_id}/validation-overview`

통계 정책:

- snapshot 통계는 snapshot이 존재하면 status와 관계없이 조회 가능
- 통계 계산에는 `ranking_entries.is_valid=true`만 사용
- `cutoff-series`는 `ranking_snapshots.status=completed` snapshot만 사용

### validation 1차

entry 생성 시 backend가 `is_valid` / `validation_issue`를 재계산합니다.

현재 코드:

- `invalid_rank`
- `invalid_score`
- `missing_player_name`
- `low_ocr_confidence`
- `duplicate_rank`
- `rank_order_violation`

현재 자동 적용 규칙:

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`

정책:

- invalid entry도 저장됩니다.
- `validation_issue`는 backend가 표준 코드 기준으로 결정합니다.
- statistics는 invalid entry를 제외합니다.

### frontend 대시보드 1차

현재 구현 화면:

- 시즌 목록 페이지
- 시즌 상세 페이지
- snapshot 상세 페이지

현재 제공 UI:

- 시즌 목록 탐색
- snapshot 목록과 상태/source 필터링
- 시즌 validation overview / issue 집계 표시
- 시즌 상세에서 snapshot 비교 패널 제공
- snapshot 비교에서 validation issue delta 확인 가능
- summary / cutoffs / distribution 표시
- validation report / issue 집계 표시
- entry 목록 표시
- `is_valid`, `validation_issue`, `limit`, `offset`, `sort/order` 기반 entry 탐색
- 로딩 / 에러 / 빈 상태 처리

### collector

#### 1. mock import

JSON 파일만으로 아래 흐름을 검증합니다.

1. season 생성
2. snapshot 생성
3. entries 생성
4. snapshot completed 처리
5. `total_rows_collected` 반영 확인

#### 2. image capture import

이미지 파일을 입력으로 season -> snapshot -> entries -> completed 흐름을 적재하는 1차 실제 collector 입니다.

흐름:

1. capture manifest 로드
2. 페이지별 이미지/sidecar 텍스트 확인 또는 OCR 실행
3. OCR line 파싱
4. backend API로 season / snapshot / entries / completed 적재

현재 범위:

- tab-separated 또는 whitespace fallback 텍스트 파싱
- duplicate rank 사전 검증
- rank order 이상 시 경고 출력
- `sidecar` / `tesseract` OCR provider 지원
- OCR 잡음 줄 ignored line 집계
- ignored line reason(`blank_line`, `separator_line`, `non_entry_line`) 집계
- page별 OCR parse summary 출력
- backend validation 및 통계 정책 재사용

#### 3. ADB capture / integrated pipeline

실제 기기 화면을 캡처해서 바로 import 흐름으로 넘길 수 있는 1차 수집 도구가 있습니다.

현재 범위:

- `adb_capture.py`
  - 단일 페이지 screenshot 캡처
  - multi-page `capture -> swipe -> capture` 반복
  - capture manifest 자동 생성
- `run_capture_pipeline.py`
  - `adb_capture -> capture_import -> backend import`를 한 번에 실행
  - `ocr_stop_hints`로 sparse/noisy 마지막 페이지 힌트 제공
  - `ocr_stop_recommendation`으로 후속 자동화가 바로 쓸 수 있는 stop 판단 제공
  - OCR provider override, ADB command override, device serial override 지원

제약:

- 페이지 중복 제거, 마지막 페이지 판정, OCR 품질 보정은 아직 1차 수준입니다.
- 실제 운영용 collector라기보다 개발/검증용 실제 입력 파이프라인에 가깝습니다.

## 실행 방법

### 1. Docker Compose

루트에서 실행합니다.

```bash
docker compose up -d --build
docker compose ps
```

기본 포트:

- backend: `http://localhost:8000`
- frontend: `http://localhost:3000`

health check:

```bash
curl http://localhost:8000/health
```

### 2. backend 단독 실행

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger:

- `http://localhost:8000/docs`

### 3. frontend 단독 실행

```bash
cd frontend
npm install
npm run dev
```

개발 시 frontend는 기본적으로 backend를 다음 순서로 찾습니다.

1. `BACKEND_INTERNAL_URL`
2. `API_BASE_URL`
3. `http://localhost:8000`
4. `http://backend:8000`

## collector 사용 예시

### mock import

```bash
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_valid_snapshot.json
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_invalid_entries_snapshot.json
```

### image capture import

```bash
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_valid_capture
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_invalid_capture
```

### integrated capture pipeline

```bash
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_request.json
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_scroll_request.json
```

## 테스트

### backend + collector

```bash
backend/.venv/bin/pytest backend/tests collector/tests -q
```

### frontend

```bash
cd frontend
npm run lint
npm run build
```

### 빠른 전체 확인

```bash
docker compose up -d --build
curl http://localhost:8000/health
backend/.venv/bin/pytest backend/tests collector/tests -q
cd frontend && npm run lint && npm run build
```

반복 smoke 검증은 아래 스크립트로 실행할 수 있습니다.

```bash
bash scripts/smoke.sh
```

검증 대상 season/snapshot은 환경변수로 바꿀 수 있습니다.

```bash
SMOKE_SEASON_ID=33 SMOKE_SNAPSHOT_ID=41 bash scripts/smoke.sh
```

## 개발 시 주의사항

- DB 스키마와 Alembic migration은 함부로 수정하지 않습니다.
- invalid entry는 버리지 않고 저장하되, 통계에서는 제외하는 정책을 유지합니다.
- collector는 backend API 계약을 최대한 재사용합니다.
- snapshot이 terminal 상태(`completed`, `failed`)가 되면 entry 추가는 막혀야 합니다.
- 실제 collector를 추가하더라도 mock import는 회귀 검증 수단으로 유지하는 것이 좋습니다.

## 세션 인수인계 메모

다음 세션에서 작업을 이어갈 때는 아래 순서로 보면 가장 빠릅니다.

### 1. 먼저 확인할 파일

- backend 진입점:
  [backend/app/main.py](backend/app/main.py)
- snapshot/statistics/status workflow:
  [backend/app/api/routes/ranking_snapshots.py](backend/app/api/routes/ranking_snapshots.py)
- entry 저장/조회/validation 연결:
  [backend/app/api/routes/ranking_entries.py](backend/app/api/routes/ranking_entries.py)
- validation 규칙:
  [backend/app/core/ranking_entry_validation.py](backend/app/core/ranking_entry_validation.py)
- frontend API 소비:
  [frontend/app/lib/api.ts](frontend/app/lib/api.ts)
- collector 진입점:
  [collector/mock_import.py](collector/mock_import.py),
  [collector/capture_import.py](collector/capture_import.py)

### 2. 다음 세션 시작 전 체크리스트

- `git status`로 작업 트리 확인
- `docker compose up -d --build`로 서비스 기동
- backend health 확인
- `backend/.venv/bin/pytest backend/tests collector/tests -q` 실행
- 필요 시 sample import를 한 번 돌려 실제 데이터 흐름 확인

### 3. 현재 남아 있는 큰 작업 범주

- collector 상위 파이프라인 안정화
- OCR 품질 보정 및 이미지 전처리
- 스크롤 수집 중복 제거 / 마지막 페이지 판정
- frontend 2차 고도화
- validation 2차 이상 정교화
- 운영용 문서와 배포/모니터링 정리

### 4. 특히 주의할 점

- frontend는 backend 응답 구조에 직접 의존합니다.
- collector는 mock/capture 모두 backend API 계약을 재사용합니다.
- validation 정책을 바꾸면 statistics와 frontend 표시가 함께 영향을 받습니다.
- `source_type`, `status`, `is_valid`, `validation_issue`는 이후 기능 확장의 기준 필드이므로 의미를 깨지 말아야 합니다.

## 현재 문서 위치

- 전체 프로젝트 개요: 이 문서
- backend 상세: [backend/README.md](backend/README.md)
- collector 상세: [collector/README.md](collector/README.md)
- frontend 상세: [frontend/README.md](frontend/README.md)
