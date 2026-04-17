# Blue Archive OCR Fixtures

실기기 캡처 이미지를 이 디렉터리에 넣으면 collector OCR 회귀 테스트에 바로 연결할 수 있습니다.

권장 파일 구성:

- `lunatic-page-001.png`
- `lunatic-page-001.expected.json`
- `torment-page-001.png`
- `torment-page-001.expected.json`
- `insane-page-001.png`
- `insane-page-001.expected.json`

`*.expected.json` 형식:

```json
[
  {"rank": 1, "difficulty": "Lunatic", "score": 53404105},
  {"rank": 2, "difficulty": "Lunatic", "score": 53393930},
  {"rank": 3, "difficulty": "Lunatic", "score": 53393544}
]
```

주의:

- 순위표 본문이 보이는 원본 캡처 이미지를 그대로 넣습니다.
- 파일명은 난이도와 페이지를 드러내도록 유지하는 편이 좋습니다.
- 동점이어도 rank는 화면 표시 순서 기준으로 기대값을 적습니다.
- 현재 Blue Archive collector는 `rank / difficulty / score`만 회귀 대상으로 봅니다.
