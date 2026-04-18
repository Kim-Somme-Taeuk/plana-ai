# collector

개발용 데이터 주입기와 실제 collector 실험 코드를 두는 디렉터리입니다.

현재 collector는 아래 네 경로를 제공합니다.

1. `mock_import.py`
   JSON 기반 mock 데이터 주입기
2. `capture_import.py`
   이미지 파일 + OCR 추출 기반 실제 import
3. `adb_capture.py`
   ADB screenshot 캡처 및 multi-page swipe
4. `run_capture_pipeline.py`
   `adb_capture -> capture_import -> backend import`를 한 번에 실행하는 상위 파이프라인

Windows 단일 실행파일용 통합 진입점:

- `launcher.py`
  `mock`, `capture`, `adb`, `pipeline`를 하나의 실행파일에서 고르는 통합 CLI
- `plana_collector.spec`
  PyInstaller one-file 빌드 spec
- `../scripts/build_collector.ps1`
  Windows에서 `dist/plana-collector.exe`를 만드는 빌드 스크립트
- `../scripts/run_collector_pipeline.ps1`
  Windows에서 `adb`, `tesseract`, `python` 경로를 변수로 묶어서 pipeline을 짧게 실행하는 헬퍼

프로젝트 전체 개요는 [README.md](../README.md)를 먼저 참고하세요.

## 1. mock import

실제 OCR/ADB 없이 JSON 파일만으로 아래 흐름을 주입합니다.

1. season 생성
2. ranking snapshot 생성
3. ranking entries 생성
4. snapshot status를 `completed`로 변경
5. `total_rows_collected` 반영 확인

실행:

```bash
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_valid_snapshot.json
backend/.venv/bin/python collector/mock_import.py collector/mock_data/sample_invalid_entries_snapshot.json
```

주의:

- backend API를 그대로 호출합니다.
- 같은 `season_label`이 이미 있으면 해당 시즌을 재사용해 새 snapshot을 추가합니다.
- 다만 같은 `season_label`인데 시즌 메타데이터가 다르면 안전하게 실패합니다.
- 같은 snapshot 식별자(`captured_at`, `source_type`, `note`)가 이미 있으면 해당 snapshot을 재사용합니다.
- 재실행 시 기존 snapshot이 `collecting`이면 누락된 entry만 이어서 적재하고 `completed`까지 마무리합니다.
- 재실행 시 기존 snapshot entry 내용이 다르거나, `completed` snapshot에 entry가 누락돼 있으면 충돌로 간주하고 실패합니다.
- 같은 파일 안에 중복 `rank`가 있으면 import 전에 `duplicate_rank`로 실패합니다.
- season 생성 이후 entry 입력 또는 completed 처리 단계에서 실패하면 snapshot은 `failed`로 전환을 시도합니다.

## 2. capture import

이미지 파일을 입력으로 `season -> snapshot -> entries -> completed` 흐름을 적재하는 1차 실제 collector입니다.

현재 OCR provider:

1. `sidecar`
   이미지와 같은 basename의 `.txt` 사용
2. `tesseract`
   로컬 `tesseract` 명령 실행

흐름:

1. capture manifest 로드
2. page별 이미지 확인
3. sidecar 읽기 또는 OCR 실행
4. OCR line 파싱
5. backend API로 season / snapshot / entries / completed 적재

주의:

- 내부적으로 `mock_import.py` 재사용 로직을 타므로, 같은 season/snapshot으로 재실행해도 누락된 entry만 이어서 적재할 수 있습니다.
- 다만 기존 snapshot 내용과 새 입력이 충돌하면 안전하게 실패합니다.
- `tesseract` provider는 기본적으로 OCR 결과를 `.txt` sidecar로 저장합니다.
- 이후 `--reuse-tesseract-sidecar` 또는 manifest의 `ocr.reuse_cached_sidecar=true`로 기존 OCR 결과를 재사용할 수 있습니다.

### 입력 예시

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

실행:

```bash
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_valid_capture
backend/.venv/bin/python collector/capture_import.py collector/capture_data/sample_invalid_capture
```

`tesseract` override 예시:

```bash
backend/.venv/bin/python collector/capture_import.py \
  --ocr-provider tesseract \
  --ocr-command tesseract \
  --ocr-language eng \
  --ocr-psm 6 \
  collector/capture_data/sample_valid_capture
```

### 현재 OCR 파싱/분류 범위

지원 입력 형식:

- tab-separated
- structured separator: `|`, `¦`, `｜`
- whitespace fallback

현재 보강된 파싱:

- grouped score 파싱
- localized confidence 파싱 (`0,87`, `87 %`, `87,5%`)
- OCR rank token 변형 (`No.2`, `#1`, `2위`)
- Unicode normalization
  - fullwidth
  - circled 숫자
  - zero-width 문자
- player name trim / 내부 공백 정리 / 감싸기 문자 제거

현재 ignored line / diagnostics 분류:

- `blank_line`
- `header_line`
- `pagination_line`
- `footer_line`
- `reward_line`
- `ui_control_line`
- `status_line`
- `metadata_line`
- `separator_line`
- `non_entry_line`
- `malformed_entry_line`

### OCR stop / quality 신호

현재 마지막 페이지 기준으로 아래 stop 힌트를 계산합니다.

- `empty_last_page`
- `sparse_last_page`
- `noisy_last_page`
- `overlapping_last_page`
- `stale_last_page`
- `duplicate_last_page`
- `overlay_last_page`
- `header_repeat_last_page`
- `malformed_last_page`

같이 출력되는 진단:

- `page_summaries`
- `ignored_line_count`
- `ignored_line_reasons`
- `ocr_stop_hints`
- `ocr_stop_recommendation`
- `pipeline_stop_recommendation`
- `stop_policy`

또한 import된 snapshot `note`에는:

- 요약용 `collector: ...`
- 상세용 `collector_json: ...`

가 함께 저장되어 backend/frontend 품질 화면에서도 다시 볼 수 있습니다.

## 3. ADB capture

`adb_capture.py`는 Android 기기에서 현재 화면을 PNG로 캡처하고, 나중에
`capture_import.py`가 바로 읽을 수 있는 capture 디렉터리를 생성합니다.

현재 범위:

- 한 번 또는 여러 번의 screenshot 캡처
- 캡처 전 `adb devices` 기반 사전 점검
- `manifest.json` 자동 생성
- OCR provider 설정 전달
- multi-page `capture -> swipe -> capture` 반복
- screenshot 바이트 동일 / 과거 프레임 재등장 시 조기 종료

사전 점검 규칙:

- 연결된 device가 없으면 캡처 전에 바로 실패합니다.
- device가 여러 대면 `--device-serial` 또는 `adb.device_serial` 지정이 필요합니다.
- 지정한 device가 `offline` / `unauthorized` 상태면 캡처 전에 바로 실패합니다.

샘플 요청:

- [adb_data/sample_request.json](adb_data/sample_request.json)
- [adb_data/sample_scroll_request.json](adb_data/sample_scroll_request.json)
- [adb_data/mumu_scroll_request.json](adb_data/mumu_scroll_request.json)

실행:

```bash
backend/.venv/bin/python collector/adb_capture.py collector/adb_data/sample_request.json
backend/.venv/bin/python collector/adb_capture.py collector/adb_data/sample_scroll_request.json
```

## 4. integrated capture pipeline

`run_capture_pipeline.py`는 아래를 한 번에 수행합니다.

1. `adb_capture.py`로 screenshot 캡처
2. `capture_import.py`로 OCR/파싱
3. backend API로 season / snapshot / entries / completed 적재

파이프라인 산출물:

- 성공 또는 import skip 시 output 디렉터리에 `pipeline-result.json`을 남깁니다.
- 캡처 이후 단계에서 실패하면 output 디렉터리에 `pipeline-error.json`을 남깁니다.
- 두 파일 모두 재개용 `collector/capture_import.py <output_dir>`와
  `collector/run_capture_pipeline.py --output-dir <output_dir> <request_path>` 명령을 함께 기록합니다.
- output 디렉터리에 기존 `manifest.json`이 있으면 ADB 캡처를 건너뛰고 자동 resume합니다.
- 자동 resume 시 `tesseract` OCR 결과 `.txt`가 있으면 기본적으로 이를 재사용합니다.
- 새로 캡처부터 다시 하고 싶으면 빈 output 디렉터리를 쓰거나 다른 output 디렉터리를 지정해야 합니다.
- 강제로 처음부터 다시 캡처하려면 `--force-recapture`를 사용합니다.
- 기존 output만 사용해 import부터 재개하려면 `--resume-only`를 사용합니다.

실행:

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
  --stop-on-recommendation \
  collector/adb_data/sample_request.json
```

### 현재 stop 정책

- `pipeline_stop_recommendation`이 최종 stop 판단
- capture stop reason과 OCR stop recommendation을 통합
- `pipeline.stop_on_recommendation` 또는 CLI 옵션으로 import skip 가능
- hard recommendation은 capture loop에서 기본 반영
- soft recommendation은 반복 임계치 기반으로 더 보수적으로 반영

주요 정책 변수:

- `pipeline.min_pages_before_ocr_stop`
- `pipeline.soft_stop_repeat_threshold`

## validation 정책

collector는 backend validation 정책을 재사용합니다.

- `rank <= 0` -> `invalid_rank`
- `score <= 0` -> `invalid_score`
- `player_name`이 비어 있거나 공백뿐임 -> `missing_player_name`
- `ocr_confidence < 0.5` -> `low_ocr_confidence`

보조 코드:

- `duplicate_rank`
- `rank_order_violation`

정책:

- invalid entry도 저장됩니다.
- backend validation 결과가 collector 입력보다 우선합니다.
- statistics API는 invalid entry를 제외합니다.

## 테스트

collector만:

```bash
backend/.venv/bin/pytest collector/tests -q
```

Windows 단일 exe 빌드:

```powershell
.\scripts\build_collector.ps1
.\dist\plana-collector.exe mock collector\mock_data\sample_valid_snapshot.json
.\dist\plana-collector.exe capture collector\capture_data\sample_valid_capture
.\dist\plana-collector.exe adb collector\adb_data\sample_request.json
.\dist\plana-collector.exe pipeline collector\adb_data\sample_request.json
```

PowerShell에서 외부 툴 경로가 필요하면:

```powershell
.\dist\plana-collector.exe pipeline `
  --adb-command "C:\Users\<user>\AppData\Local\Android\Sdk\platform-tools\adb.exe" `
  --ocr-command "C:\Program Files\Tesseract-OCR\tesseract.exe" `
  collector\adb_data\sample_request.json
```

Windows PowerShell 헬퍼 스크립트:

```powershell
.\scripts\run_collector_pipeline.ps1
.\scripts\run_collector_pipeline.ps1 -DeviceSerial "127.0.0.1:16384"
.\scripts\run_collector_pipeline.ps1 -OutputDir .\collector\capture_runs\manual_test
.\scripts\run_collector_pipeline.ps1 -ResumeOnly -OutputDir .\collector\capture_runs\manual_test
```

Blue Archive fixture 정확도 평가:

```bash
backend/.venv/bin/python collector/evaluate_blue_archive_fixtures.py
```

Windows:

```powershell
.\.collector-venv\Scripts\python.exe collector\evaluate_blue_archive_fixtures.py --ocr-command "C:\Program Files\Tesseract-OCR\tesseract.exe"
.\scripts\evaluate_blue_archive_fixtures.ps1
```

backend 포함:

```bash
backend/.venv/bin/pytest backend/tests collector/tests -q
```

collector smoke:

```bash
bash scripts/collector_smoke.sh
```

CI/seed smoke:

```bash
bash scripts/ci_smoke.sh
```

## 다음 세션에서 먼저 볼 파일

- [mock_import.py](mock_import.py)
- [capture_import.py](capture_import.py)
- [adb_capture.py](adb_capture.py)
- [run_capture_pipeline.py](run_capture_pipeline.py)
- [tests/test_mock_import.py](tests/test_mock_import.py)
- [tests/test_capture_import.py](tests/test_capture_import.py)
- [tests/test_adb_capture.py](tests/test_adb_capture.py)
- [tests/test_run_capture_pipeline.py](tests/test_run_capture_pipeline.py)
