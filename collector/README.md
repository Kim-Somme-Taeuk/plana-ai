# collector

개발용 데이터 주입기와 실제 collector 확장 실험 코드를 두는 디렉터리입니다.

현재 collector는 두 경로를 제공합니다.

1. `mock_import.py`
   JSON 기반 mock 데이터 주입기
2. `capture_import.py`
   이미지 파일 + OCR 추출 기반 1차 실제 collector

루트 개요 문서는 [README.md](../README.md)를 먼저 참고하세요.

## 1. image capture import

이미지 파일을 입력으로 `season -> snapshot -> entries -> completed` 흐름을 검증하는 1차 실제 collector입니다.

현재 OCR 입력 방식은 두 가지입니다.

1. `sidecar`
   이미지와 같은 basename의 `.txt` 파일을 읽음
2. `tesseract`
   로컬 `tesseract` 명령을 실행해 이미지에서 직접 텍스트를 추출

### 흐름

1. capture manifest 로드
2. page별 이미지 경로 확인
3. page별 OCR 텍스트 읽기 또는 OCR 엔진 실행
4. OCR line을 `rank / player_name / score / ocr_confidence`로 파싱
5. 기존 backend API로 season / snapshot / entries / completed 적재

### 입력 디렉터리 형식

디렉터리 기준 기본 파일은 `manifest.json` 입니다.

```json
{
  "season": {
    "event_type": "total_assault",
    "server": "kr",
    "boss_name": "Binah",
    "armor_type": "heavy",
    "terrain": "outdoor",
    "season_label": "capture-valid-season-20260416-a"
  },
  "snapshot": {
    "captured_at": "2026-04-16T10:20:00Z",
    "note": "sample valid capture import"
  },
  "ocr": {
    "provider": "sidecar"
  },
  "pages": [
    {
      "image_path": "page-001.png"
    }
  ]
}
```

`snapshot.source_type`을 생략하면 OCR provider에 맞춰 자동으로 채워집니다.

- `sidecar` -> `image_sidecar`
- `tesseract` -> `image_tesseract`

### OCR provider 설정

기본값은 `sidecar` 입니다.

```json
{
  "ocr": {
    "provider": "sidecar"
  }
}
```

`tesseract`를 직접 쓰려면:

```json
{
  "ocr": {
    "provider": "tesseract",
    "command": "tesseract",
    "language": "eng",
    "psm": 6
  }
}
```

CLI에서 manifest 설정을 override할 수도 있습니다.

```bash
backend/.venv/bin/python collector/capture_import.py \
  --ocr-provider tesseract \
  --ocr-command tesseract \
  --ocr-language eng \
  --ocr-psm 6 \
  collector/capture_data/sample_valid_capture
```

기본 OCR sidecar는 같은 basename의 `.txt` 파일입니다.

예시 `page-001.txt`:

```text
1	Plana	12345678	0.99
10	Arona	12000000	0.97
100	Sensei	11000000	0.95
```

지원하는 line 형식:

- tab-separated: `rank<TAB>player_name<TAB>score<TAB>ocr_confidence`
- whitespace fallback: `rank player_name score [ocr_confidence]`

### 실행 예시

```bash
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_valid_capture
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_invalid_capture
```

로컬 `tesseract`가 설치돼 있다면:

```bash
backend/.venv/bin/python collector/capture_import.py \
  --ocr-provider tesseract \
  collector/capture_data/sample_valid_capture
```

성공 시 `season_id`, `snapshot_id`, `page_count`, `entry_count`, `entry_ids`, `status`, `total_rows_collected`를 JSON으로 출력합니다.

### 주의사항

- `sidecar` provider는 이미지 파일과 OCR sidecar 파일이 둘 다 있어야 합니다.
- `tesseract` provider는 로컬에 `tesseract` 명령이 있어야 합니다.
- `source_type`을 생략하면 OCR provider에 맞는 기본값으로 기록됩니다.
- 같은 capture를 다시 넣으면 `season_label` 중복으로 실패합니다.
- OCR line 파싱에 실패하면 import를 중단합니다.
- duplicate rank는 upload 전에 `duplicate_rank`로 실패합니다.
- rank 순서 이상은 경고만 출력하고 import는 계속 진행합니다.

## 2. mock import

실제 OCR/ADB 없이 JSON 파일만으로 아래 흐름을 주입합니다.

1. season 생성
2. ranking snapshot 생성
3. ranking entries 생성
4. snapshot status를 `completed`로 변경
5. `total_rows_collected` 반영 확인

### 실행 예시

```bash
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_valid_snapshot.json
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_invalid_entries_snapshot.json
```

다른 API 주소를 쓰려면:

```bash
backend/.venv/bin/python collector/mock_import.py \
  --base-url http://localhost:8000 \
  collector/mock_data/sample_valid_snapshot.json
```

### 주의사항

- 기존 backend API를 그대로 호출합니다.
- 같은 파일을 다시 넣으면 `season_label` 중복으로 실패합니다.
- 같은 파일 안에 중복 `rank`가 있으면 import 전에 `duplicate_rank`로 실패합니다.
- 기본 동작은 덮어쓰기/업서트가 아닙니다.
- season 생성 이후 entry 입력 또는 completed 처리 단계에서 실패하면 snapshot은 `failed`로 전환을 시도합니다.

## validation 정책

collector는 backend validation 정책을 재사용합니다.

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`
- 보조 코드:
  - `duplicate_rank`
  - `rank_order_violation`

정책:

- invalid entry도 저장됩니다.
- invalid entry는 `is_valid=false`와 `validation_issue` 코드로 남습니다.
- collector 입력값의 `is_valid` / `validation_issue`보다 backend validation 결과가 우선합니다.
- statistics API는 `is_valid=false` entry를 제외합니다.

## 테스트

```bash
backend/.venv/bin/pytest collector/tests -q
```

backend까지 포함한 최소 회귀:

```bash
backend/.venv/bin/pytest backend/tests collector/tests -q
```

## 다음 세션에서 먼저 볼 파일

- [mock_import.py](mock_import.py)
- [capture_import.py](capture_import.py)
- [tests/test_mock_import.py](tests/test_mock_import.py)
- [tests/test_capture_import.py](tests/test_capture_import.py)
