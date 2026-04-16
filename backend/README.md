# backend

`plana-ai`의 FastAPI + SQLAlchemy + PostgreSQL 기반 API 서버입니다.

이 backend는 단순 저장소가 아니라 아래 책임을 가집니다.

- season / snapshot / entry 저장
- snapshot 상태 전이 관리
- entry validation 적용
- snapshot / season 통계 계산
- collector diagnostics 구조화
- frontend와 collector가 사용할 API 제공

프로젝트 전체 개요는 [README.md](../README.md)를 먼저 참고하세요.

## 실행

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

주요 경로:

- `/`
- `/health`
- `/docs`

## 주요 API

기본 저장/조회:

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

snapshot 통계/품질:

- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`

season 통계/품질:

- `GET /seasons/{season_id}/cutoff-series`
- `GET /seasons/{season_id}/validation-overview`
- `GET /seasons/{season_id}/validation-series`

## ranking_snapshot 상태 정책

- `collecting -> completed` 허용
- `collecting -> failed` 허용
- `completed -> collecting` 금지
- `failed -> collecting` 금지
- `completed -> failed` 금지
- 같은 상태로 다시 PATCH 하는 no-op 요청은 허용
- `completed` 전이 시 `total_rows_collected`를 실제 entry 개수로 갱신
- terminal 상태(`completed`, `failed`)가 되면 새 entry 입력은 거부

## ranking_entries 조회 옵션

`GET /ranking-snapshots/{snapshot_id}/entries`

- `is_valid`
- `validation_issue`
- `limit`
- `offset`
- `sort_by=rank|score`
- `order=asc|desc`

기본 정렬:

- `rank ASC`

## validation 정책

entry 생성 시 backend가 `is_valid`와 `validation_issue`를 재계산합니다.

현재 자동 규칙:

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`

보조 코드:

- `duplicate_rank`
- `rank_order_violation`

정책:

- invalid entry도 저장됩니다.
- 요청 payload의 `is_valid` / `validation_issue`보다 backend validation 결과가 우선합니다.
- statistics API는 `is_valid=false` entry를 제외합니다.

## snapshot validation / statistics

`GET /ranking-snapshots/{snapshot_id}/summary`

- valid/invalid entry 수
- highest / lowest valid score
- validation issue 집계

`GET /ranking-snapshots/{snapshot_id}/validation-report`

- total / valid / invalid entry 수
- excluded count
- invalid ratio
- duplicate rank count
- rank order violation 여부
- top validation issue
- validation issue 집계
- collector diagnostics

## collector diagnostics 노출

collector가 snapshot `note`에 남긴 `collector:` / `collector_json:`를 backend가 구조화해서 다시 반환합니다.

현재 노출 범위:

- `capture_stop_reason`
- `ocr_stop_reason`
- `ocr_stop_level`
- `ocr_stop_recommendation`
- `pipeline_stop_recommendation`
- `stop_policy`
- `ignored_reasons`
- `page_summaries`
- `empty_page_count`
- `sparse_page_count`
- `overlapping_page_count`
- `stale_page_count`
- `noisy_page_count`
- `overlay_ignored_line_count`
- `header_ignored_line_count`
- `malformed_entry_line_count`

즉, collector 품질 신호를 backend API에서 validation/통계와 함께 볼 수 있습니다.

## season validation overview / series

`GET /seasons/{season_id}/validation-overview`

반환:

- snapshot 상태 분포
- total / valid / invalid entry 수
- invalid ratio
- top validation issue
- validation issue 집계
- collector diagnostics 집계
- page quality signal 집계
- ignored OCR 집계
- capture / OCR / pipeline stop 집계

지원 query:

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

`GET /seasons/{season_id}/validation-series`

반환:

- snapshot별 invalid ratio
- snapshot별 top validation issue
- snapshot별 collector diagnostics

지원 query는 overview와 동일합니다.

## cutoff-series 정책

`GET /seasons/{season_id}/cutoff-series`

- completed snapshot만 사용
- optional `source_type` 필터 지원

## 테스트

backend만:

```bash
backend/.venv/bin/pytest backend/tests -q
```

collector 포함 최소 회귀:

```bash
backend/.venv/bin/pytest backend/tests collector/tests -q
```

docker 기반 smoke:

```bash
bash scripts/ci_smoke.sh
```

## 다음 세션에서 먼저 볼 파일

- [app/main.py](app/main.py)
- [app/api/routes/ranking_snapshots.py](app/api/routes/ranking_snapshots.py)
- [app/api/routes/ranking_entries.py](app/api/routes/ranking_entries.py)
- [app/core/ranking_entry_validation.py](app/core/ranking_entry_validation.py)
- [app/core/collector_diagnostics.py](app/core/collector_diagnostics.py)
