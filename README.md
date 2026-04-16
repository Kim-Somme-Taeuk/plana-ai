# plana-ai

블루 아카이브 총력전/대결전 랭킹 데이터를 수집, 저장, 검증, 통계화하고 운영용 대시보드로 확인하는 풀스택 프로젝트입니다.

이 저장소는 단순 CRUD 앱이 아니라 아래 흐름 전체를 포함합니다.

1. 시즌 메타데이터 생성
2. 특정 시점의 랭킹 스냅샷 생성
3. 스냅샷 안의 엔트리 저장
4. validation 적용
5. snapshot 상태를 `collecting / completed / failed`로 관리
6. valid entry 기준 통계 계산
7. frontend 대시보드에서 시즌, 스냅샷, 품질 신호 탐색
8. mock / capture / ADB collector로 전체 파이프라인 검증

## 현재 프로젝트 성격

지금 frontend는 일반 공개 서비스라기보다 운영자/개발자용 대시보드에 가깝습니다.

- 시즌/스냅샷/엔트리 저장
- validation issue와 collector diagnostics 확인
- snapshot/season 품질 drilldown
- collector stop 신호와 OCR 품질 확인

즉, 현재 목표는 “예쁜 서비스”보다 “수집 품질과 통계 정합성을 빠르게 확인하는 운영 화면”입니다.

## 저장소 구조

- `backend/`
  FastAPI + SQLAlchemy + PostgreSQL API 서버
- `frontend/`
  Next.js App Router 기반 운영 대시보드
- `collector/`
  mock import, capture import, ADB capture, integrated pipeline
- `docs/`
  세션 인수인계/보조 문서
- `scripts/`
  smoke / seed / CI 보조 스크립트
- `.github/workflows/`
  GitHub Actions CI

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
- 현재 스키마에는 별도 “회차/시즌 번호” 컬럼이 없고, 사람이 읽는 식별은 `season_label`에 담는 구조입니다.

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
- terminal 상태(`completed`, `failed`)에서는 entry 추가를 거부

### `ranking_entries`

특정 snapshot 안의 개별 랭킹 row를 저장합니다.

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

### Backend

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

엔트리 조회 옵션:

- `is_valid`
- `validation_issue`
- `limit / offset`
- `sort_by=rank|score`
- `order=asc|desc`

통계/품질 API:

- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
- `GET /seasons/{season_id}/cutoff-series`
- `GET /seasons/{season_id}/validation-overview`
- `GET /seasons/{season_id}/validation-series`

시즌 품질 drilldown 필터:

- `status`
- `source_type`
- `collector_filter=with_diagnostics|capture_stop|hard_ocr_stop`
- `capture_stop_reason`
- `ocr_stop_reason`
- `pipeline_stop_reason`
- `pipeline_stop_source`
- `pipeline_stop_level`
- `ignored_reason`
- `ignored_group=overlay|header|malformed`
- `page_signal=empty|sparse|overlapping|stale|noisy`
- `ocr_stop_level=soft|hard`

### Validation

현재 자동 validation 규칙:

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`

보조 코드:

- `duplicate_rank`
- `rank_order_violation`

정책:

- invalid entry도 저장
- statistics는 invalid entry 제외
- backend가 `is_valid` / `validation_issue`를 최종 재계산

### Frontend

현재 구현 화면:

- `/`
  시즌 목록
- `/seasons/[seasonId]`
  시즌 상세, validation overview, validation series, cutoff series, snapshot compare
- `/snapshots/[snapshotId]`
  snapshot summary, validation report, distribution, cutoffs, entries

현재 UI 범위:

- 시즌/스냅샷/collector diagnostics 기반 탐색
- validation issue drilldown
- season compare용 snapshot 선택 및 비교
- collector stop / ignored OCR / page quality signal 확인
- 모바일 포함 운영 대시보드용 반응형 1차 대응

### Collector

현재 collector는 네 경로를 제공합니다.

1. `collector/mock_import.py`
   JSON 기반 mock 데이터 주입
2. `collector/capture_import.py`
   이미지 + sidecar/tesseract OCR import
3. `collector/adb_capture.py`
   ADB screenshot 캡처 및 multi-page swipe
4. `collector/run_capture_pipeline.py`
   `adb_capture -> capture_import -> backend import` 통합 실행

현재 collector 진척도:

- mock import 완료
- actual capture import 완료
- tesseract 연동 완료
- multi-page ADB capture 완료
- stop hint / recommendation / skip policy / diagnostics 저장 완료
- 실전 운영 안정화는 계속 진행 중

## Collector 품질 신호

현재 collector는 snapshot `note`에 요약용 `collector:` 라인과 상세용 `collector_json:` 라인을 남깁니다.

backend는 이를 파싱해서 아래 정보로 다시 노출합니다.

- `capture_stop_reason`
- `ocr_stop_reason`
- `ocr_stop_recommendation`
- `pipeline_stop_recommendation`
- `stop_policy`
- `ignored_reasons`
- `overlay_ignored_line_count`
- `header_ignored_line_count`
- `malformed_entry_line_count`
- `page_summaries`
- `empty_page_count`
- `sparse_page_count`
- `overlapping_page_count`
- `stale_page_count`
- `noisy_page_count`

즉, 품질 문제는 collector -> backend API -> frontend 대시보드까지 이어집니다.

## 실행 방법

### Docker Compose

```bash
docker compose up -d --build
docker compose ps
curl http://localhost:8000/health
```

기본 포트:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8000`
- db host bind: `localhost:5432`

포트 충돌 시:

```bash
POSTGRES_HOST_PORT=55432 BACKEND_PORT=58000 FRONTEND_PORT=53000 docker compose up -d --build
```

### Backend 단독 실행

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger:

- `http://localhost:8000/docs`

### Frontend 단독 실행

```bash
cd frontend
npm install
npm run dev
```

frontend는 아래 순서로 backend를 찾습니다.

1. `BACKEND_INTERNAL_URL`
2. `API_BASE_URL`
3. `http://localhost:8000`
4. `http://backend:8000`

## 자주 쓰는 collector 명령

### Mock import

```bash
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_valid_snapshot.json
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_invalid_entries_snapshot.json
```

### Capture import

```bash
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_valid_capture
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_invalid_capture
```

### Integrated pipeline

```bash
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_request.json
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_scroll_request.json
```

## 테스트 / 검증

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

### smoke

```bash
bash scripts/smoke.sh
bash scripts/collector_smoke.sh
bash scripts/ci_smoke.sh
```

### GitHub Actions

`.github/workflows/ci.yml`에서 아래를 자동 검증합니다.

- backend + collector pytest
- frontend lint
- frontend build
- docker 기반 seeded smoke

## 다음 세션에서 먼저 볼 파일

- [backend/app/api/routes/ranking_snapshots.py](backend/app/api/routes/ranking_snapshots.py)
- [backend/app/api/routes/ranking_entries.py](backend/app/api/routes/ranking_entries.py)
- [backend/app/core/ranking_entry_validation.py](backend/app/core/ranking_entry_validation.py)
- [backend/app/core/collector_diagnostics.py](backend/app/core/collector_diagnostics.py)
- [frontend/app/components/dashboard.tsx](frontend/app/components/dashboard.tsx)
- [frontend/app/seasons/[seasonId]/page.tsx](frontend/app/seasons/[seasonId]/page.tsx)
- [frontend/app/snapshots/[snapshotId]/page.tsx](frontend/app/snapshots/[snapshotId]/page.tsx)
- [collector/capture_import.py](collector/capture_import.py)
- [collector/run_capture_pipeline.py](collector/run_capture_pipeline.py)

## 문서 위치

- backend 상세: [backend/README.md](backend/README.md)
- frontend 상세: [frontend/README.md](frontend/README.md)
- collector 상세: [collector/README.md](collector/README.md)
- 보조 문서: [docs/README.md](docs/README.md)
