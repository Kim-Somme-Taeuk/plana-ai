# backend

FastAPI 백엔드입니다.

## 실행

source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## 엔드포인트

- /
- /health
- /docs

## ranking_entries API

Swagger `/docs`에서 `ranking_entries` 섹션으로 바로 테스트할 수 있습니다.

먼저 사용할 `snapshot_id`를 확인합니다.

```bash
curl http://localhost:8000/seasons
curl http://localhost:8000/seasons/{season_id}/ranking-snapshots
```

Entry 생성 예시입니다.

```bash
curl -X POST http://localhost:8000/ranking-snapshots/{snapshot_id}/entries \
  -H "Content-Type: application/json" \
  -d '{
    "rank": 1,
    "score": 123456,
    "player_name": "Shiroko",
    "ocr_confidence": 0.98,
    "raw_text": "1 Shiroko 123456",
    "image_path": "/tmp/shiroko.png",
    "is_valid": true,
    "validation_issue": null
  }'
```

목록 조회와 단건 조회 예시입니다.

```bash
curl http://localhost:8000/ranking-snapshots/{snapshot_id}/entries
curl http://localhost:8000/ranking-entries/{entry_id}
```

같은 `snapshot_id` 안에서 같은 `rank`를 다시 생성하면 `409 Conflict`를 반환합니다.

## ranking_entries validation

entry 생성 시 backend가 아래 규칙으로 `is_valid`와 `validation_issue`를 정리합니다.

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`
- snapshot 보조 검증 코드:
  - `duplicate_rank`
  - `rank_order_violation`

추가 정책:

- invalid entry도 저장됩니다.
- valid entry면 `validation_issue=null`로 저장됩니다.
- 요청의 `is_valid` / `validation_issue` 값보다 backend validation 결과가 우선합니다.
- statistics API는 기존처럼 `is_valid=false` entry를 제외합니다.

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
