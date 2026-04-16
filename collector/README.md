# collector

개발용 mock 데이터 주입기와 이후 실제 collector 실험 코드를 두는 디렉터리입니다.

## mock import

실제 OCR/ADB 없이 JSON 파일만으로 아래 흐름을 주입합니다.

1. season 생성
2. ranking snapshot 생성
3. ranking entries 생성
4. snapshot status를 `completed`로 변경
5. `total_rows_collected` 반영 확인

### 입력 파일 형식

```json
{
  "season": {
    "event_type": "total_assault",
    "server": "kr",
    "boss_name": "Binah",
    "armor_type": "heavy",
    "terrain": "outdoor",
    "season_label": "mock-valid-season-20260416-a",
    "started_at": "2026-04-16T09:00:00Z",
    "ended_at": "2026-04-23T09:00:00Z"
  },
  "snapshot": {
    "captured_at": "2026-04-16T10:15:00Z",
    "source_type": "mock_json",
    "note": "valid-only sample snapshot"
  },
  "entries": [
    {
      "rank": 1,
      "score": 12345678,
      "player_name": "Plana",
      "ocr_confidence": 0.99,
      "raw_text": "1 Plana 12345678",
      "image_path": "/mock/valid/plana.png",
      "is_valid": true,
      "validation_issue": null
    }
  ]
}
```

### 실행 예시

```bash
python3 collector/mock_import.py collector/mock_data/sample_valid_snapshot.json
python3 collector/mock_import.py collector/mock_data/sample_invalid_entries_snapshot.json
```

다른 API 주소를 쓰려면:

```bash
python3 collector/mock_import.py \
  --base-url http://localhost:8000 \
  collector/mock_data/sample_valid_snapshot.json
```

성공 시 `season_id`, `snapshot_id`, `entry_ids`, `status`, `total_rows_collected`를 JSON으로 출력합니다.

### 주의사항

- 이 스크립트는 기존 backend API를 그대로 호출합니다.
- 같은 파일을 다시 넣으면 `season_label` 중복으로 실패합니다.
- 같은 파일 안에 중복 `rank`가 있으면 import 전에 `duplicate_rank`로 실패합니다.
- 기본 동작은 덮어쓰기/업서트가 아닙니다.
- season 생성 이후 entry 입력 또는 completed 처리 단계에서 실패하면 snapshot은 `failed`로 전환을 시도합니다.
- season 생성 이후 snapshot 생성 전 단계에서 실패하면 일부 데이터가 남지 않습니다.
- 실제 OCR, ADB, 스크롤 자동화는 이번 단계에서 구현하지 않습니다.

## validation 정책

mock import는 entry를 그대로 저장하지 않고 backend entry validation을 통과시킵니다.

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`
- snapshot 보조 검증 코드:
  - `duplicate_rank`
  - `rank_order_violation`

추가 정책:

- invalid entry도 저장됩니다.
- invalid entry는 `is_valid=false`와 `validation_issue` 코드로 남습니다.
- mock 파일의 `is_valid` / `validation_issue`보다 backend validation 결과가 우선합니다.
- statistics API는 `is_valid=false` entry를 제외합니다.
