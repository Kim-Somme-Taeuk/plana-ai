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
