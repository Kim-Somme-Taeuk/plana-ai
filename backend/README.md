# backend

`plana-ai`의 FastAPI + SQLAlchemy + PostgreSQL 기반 API 서버입니다.

이 backend는 단순 저장소가 아니라 아래 책임을 가집니다.

- season / snapshot / entry 저장
- snapshot 상태 전이 관리
- entry validation 적용
- snapshot / season 통계 계산
- frontend와 collector가 사용할 API 제공

루트 개요 문서는 [README.md](../README.md)를 먼저 참고하세요.

## 실행

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

엔드포인트:

- `/`
- `/health`
- `/docs`

## 현재 주요 API

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

통계:

- `GET /ranking-snapshots/{snapshot_id}/summary`
- `GET /ranking-snapshots/{snapshot_id}/validation-report`
- `GET /ranking-snapshots/{snapshot_id}/cutoffs`
- `GET /ranking-snapshots/{snapshot_id}/distribution`
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
- `completed` 전이 시 `total_rows_collected`를 실제 entry 개수로 반영
- terminal 상태(`completed`, `failed`)가 되면 새 entry 입력은 거부

## ranking_entries 조회 옵션

`GET /ranking-snapshots/{snapshot_id}/entries`

- `is_valid`
- `validation_issue`
- `limit`
- `offset`
- `sort_by=rank|score`
- `order=asc|desc`

기본 동작:

- `rank ASC`

## ranking_entries validation

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
- 요청의 `is_valid` / `validation_issue`보다 backend validation 결과가 우선합니다.
- statistics API는 `is_valid=false` entry를 제외합니다.
- `GET /ranking-snapshots/{snapshot_id}/entries`는 `validation_issue` 문자열로도 필터링할 수 있습니다.
- `GET /ranking-snapshots/{snapshot_id}/summary`는 `validation_issues` 배열로 issue별 count를 함께 반환합니다.
- `GET /ranking-snapshots/{snapshot_id}/validation-report`는 invalid 제외 수, invalid 비율, top issue, duplicate rank 수, rank order violation 여부를 함께 반환합니다.
- `GET /seasons/{season_id}/validation-overview`는 시즌 단위 snapshot 상태 분포, valid/invalid 비율, top issue, issue 집계를 함께 반환합니다.
  - optional query: `status`, `source_type`
- `GET /seasons/{season_id}/validation-series`는 snapshot별 invalid 비율과 top issue를 시간순으로 반환합니다.
  - optional query: `status`, `source_type`

예시:

```bash
curl -X POST http://localhost:8000/ranking-snapshots/{snapshot_id}/entries \
  -H "Content-Type: application/json" \
  -d '{
    "rank": 10,
    "score": 9654321,
    "player_name": "Yuzu",
    "ocr_confidence": 0.41,
    "raw_text": "10 Yuzu 9654321",
    "image_path": "/tmp/yuzu.png",
    "is_valid": true,
    "validation_issue": null
  }'
```

응답 예시:

```json
{
  "id": 12,
  "ranking_snapshot_id": 3,
  "rank": 10,
  "score": 9654321,
  "player_name": "Yuzu",
  "ocr_confidence": 0.41,
  "raw_text": "10 Yuzu 9654321",
  "image_path": "/tmp/yuzu.png",
  "is_valid": false,
  "validation_issue": "low_ocr_confidence"
}
```

## 테스트

```bash
backend/.venv/bin/pytest backend/tests -q
```

collector까지 포함한 최소 회귀:

```bash
backend/.venv/bin/pytest backend/tests collector/tests -q
```

## 다음 세션에서 먼저 볼 파일

- [app/main.py](app/main.py)
- [app/api/routes/ranking_snapshots.py](app/api/routes/ranking_snapshots.py)
- [app/api/routes/ranking_entries.py](app/api/routes/ranking_entries.py)
- [app/core/ranking_entry_validation.py](app/core/ranking_entry_validation.py)
