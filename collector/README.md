# collector

개발용 데이터 주입기와 실제 collector 확장 실험 코드를 두는 디렉터리입니다.

현재 collector는 네 경로를 제공합니다.

1. `mock_import.py`
   JSON 기반 mock 데이터 주입기
2. `capture_import.py`
   이미지 파일 + OCR 추출 기반 1차 실제 collector
3. `adb_capture.py`
   ADB screenshot을 capture manifest 디렉터리로 저장하는 1차 캡처 도구
4. `run_capture_pipeline.py`
   ADB capture부터 OCR import까지 한 번에 실행하는 상위 파이프라인

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
`ignored_line_count`, `ignored_line_reasons`, `page_summaries`, `ignored_lines`도 함께 출력해서 OCR header/footer/blank line 잡음 줄과 페이지별 파싱 상태를 확인할 수 있습니다.

### 주의사항

- `sidecar` provider는 이미지 파일과 OCR sidecar 파일이 둘 다 있어야 합니다.
- `tesseract` provider는 로컬에 `tesseract` 명령이 있어야 합니다.
- `source_type`을 생략하면 OCR provider에 맞는 기본값으로 기록됩니다.
- 같은 capture를 다시 넣으면 `season_label` 중복으로 실패합니다.
- OCR line 파싱에 실패하면 import를 중단합니다.
- 숫자 토큰은 흔한 OCR 오인식에 대해 보정합니다.
  - 예: `O -> 0`, `l -> 1`, trailing `.` 제거
- whitespace fallback의 confidence token도 같은 보정 규칙을 적용합니다.
- whitespace fallback에서는 `12 345 678`처럼 공백으로 분리된 score token도 보수적으로 합쳐서 파싱합니다.
- `player_name`은 앞뒤 공백을 제거하고 내부 연속 공백을 한 칸으로 정리합니다.
- rank로 시작하지 않는 OCR 잡음 줄은 import 전에 무시하고 결과에 `ignored_lines`로 남깁니다.
- 빈 줄도 `blank_line` reason으로 집계합니다.
- 구분선처럼 보이는 줄은 `separator_line` reason으로 집계합니다.
- duplicate rank는 upload 전에 `duplicate_rank`로 실패합니다.
- rank 순서 이상은 경고만 출력하고 import는 계속 진행합니다.

## 2. ADB screenshot capture

`adb_capture.py`는 Android 기기에서 현재 화면을 PNG로 캡처하고, 나중에
`capture_import.py`가 바로 읽을 수 있는 capture 디렉터리를 생성합니다.

현재 1차 범위:

- 한 번 또는 여러 번의 screenshot 캡처
- `manifest.json` 자동 생성
- OCR provider 설정 전달
- multi-page일 때 `capture -> swipe -> capture` 반복
- 실제 import는 별도 단계로 유지

### 요청 파일 형식

```json
{
  "season": {
    "event_type": "total_assault",
    "server": "kr",
    "boss_name": "Binah",
    "armor_type": "heavy",
    "terrain": "outdoor",
    "season_label": "adb-capture-sample-season-20260416-a"
  },
  "snapshot": {
    "captured_at": "2026-04-16T12:00:00Z",
    "note": "sample adb screenshot capture"
  },
  "ocr": {
    "provider": "tesseract",
    "language": "eng",
    "psm": 6
  },
  "adb": {
    "output_dir": "../capture_runs/sample_adb_capture"
  }
}
```

샘플 파일:

- [adb_data/sample_request.json](adb_data/sample_request.json)
- [adb_data/sample_scroll_request.json](adb_data/sample_scroll_request.json)

### multi-page scroll 설정

여러 페이지를 캡처하려면 `adb.page_count`와 `adb.swipe`를 함께 지정합니다.

```json
{
  "adb": {
    "output_dir": "../capture_runs/sample_scroll_capture",
    "page_count": 3,
    "stop_on_duplicate_frame": true,
    "swipe": {
      "start_x": 500,
      "start_y": 1600,
      "end_x": 500,
      "end_y": 600,
      "duration_ms": 200,
      "settle_delay_ms": 800
    }
  }
}
```

정책:

- `page_count=1`이면 swipe 설정이 필요 없습니다.
- `page_count>=2`이면 `adb.swipe`가 필수입니다.
- `stop_on_duplicate_frame=true`면 이전 페이지와 screenshot 바이트가 동일할 때 조기 종료합니다.
- 같은 옵션이 켜져 있으면 직전 페이지와 같을 때뿐 아니라, 이전에 본 프레임이 다시 나타나도 `repeated_frame`으로 조기 종료합니다.
- 마지막 페이지 뒤에는 swipe를 실행하지 않습니다.
- swipe 뒤에는 `settle_delay_ms`만큼 대기합니다.
- `adb.output_dir`의 상대경로 기준은 요청 JSON 파일이 있는 디렉터리입니다.
- 기존 파일이 남아 있는 output 디렉터리에는 새 캡처를 쓰지 않습니다. 매 실행마다 빈 디렉터리나 새 경로를 사용하세요.

### 실행 예시

```bash
backend/.venv/bin/python collector/adb_capture.py collector/adb_data/sample_request.json
backend/.venv/bin/python collector/adb_capture.py collector/adb_data/sample_scroll_request.json
```

serial이나 adb 경로를 override하려면:

```bash
backend/.venv/bin/python collector/adb_capture.py \
  --adb-command adb \
  --device-serial emulator-5554 \
  --output-dir /tmp/plana-adb-capture \
  collector/adb_data/sample_request.json
```

성공 시 `output_dir`, `manifest_path`, `image_paths`, `ocr_provider`, `device_serial`,
`requested_page_count`, `captured_page_count`, `stopped_reason`,
`ignored_line_count`, `ignored_line_reasons`, `page_summaries`, `ocr_stop_hints`를 JSON으로 출력합니다.

### 주의사항

- 로컬에 `adb` 명령이 있어야 합니다.
- 이 단계는 screenshot 캡처와 기본 scroll 반복까지만 수행합니다.
- 마지막 페이지 판정 2차는 screenshot 바이트 동일 또는 과거 프레임 재등장 여부 기반입니다.
- OCR import 이후에는 `ocr_stop_hints`로 `sparse_last_page`, `noisy_last_page` 같은 후속 종료 힌트를 남깁니다.
- OCR 실행과 backend import는 `capture_import.py`에서 이어집니다.
- 생성 결과는 `capture_import.py` 입력 포맷과 호환됩니다.

## 3. integrated capture pipeline

`run_capture_pipeline.py`는 아래 단계를 한 번에 수행합니다.

1. `adb_capture.py`로 screenshot 캡처
2. `capture_import.py`로 OCR/파싱
3. backend API로 season / snapshot / entries / completed 적재

### 실행 예시

```bash
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_request.json
backend/.venv/bin/python collector/run_capture_pipeline.py collector/adb_data/sample_scroll_request.json
```

override 예시:

```bash
backend/.venv/bin/python collector/run_capture_pipeline.py \
  --adb-command adb \
  --device-serial emulator-5554 \
  --ocr-provider tesseract \
  --ocr-language eng \
  --ocr-psm 6 \
  --output-dir /tmp/plana-pipeline-run \
  collector/adb_data/sample_request.json
```

성공 시 `output_dir`, `manifest_path`, `image_paths`, `season_id`, `snapshot_id`,
`entry_count`, `entry_ids`, `status`, `total_rows_collected`, `ocr_provider`,
`requested_page_count`, `captured_page_count`, `stopped_reason`, `ignored_line_count`를 JSON으로 출력합니다.

### 주의사항

- 이 파이프라인은 기존 `adb_capture.py`와 `capture_import.py`를 조합하는 얇은 orchestration 레이어입니다.
- 요청 파일에 `ocr.provider`를 생략하면 통합 파이프라인에서는 `tesseract`를 기본값으로 사용합니다.
- capture 자체가 성공해도 import 단계에서 실패할 수 있으며, 이 경우 생성된 capture 디렉터리는 디버깅용으로 그대로 남습니다.
- 운영용 안정화가 끝난 collector가 아니라 개발/검증용 실제 입력 파이프라인 1차입니다.

## 4. mock import

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
- [adb_capture.py](adb_capture.py)
- [tests/test_mock_import.py](tests/test_mock_import.py)
- [tests/test_capture_import.py](tests/test_capture_import.py)
- [tests/test_adb_capture.py](tests/test_adb_capture.py)
