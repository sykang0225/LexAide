# Baseline Evaluation Notes

Date: 2026-05-25  
Dataset: `test_cases_ko.json`  
Cases: 60 total = 20 PASS / 20 WARNING / 20 VIOLATION  
Run: rule-first baseline, LLM OFF, embedding OFF

## Metrics

- Exact accuracy: 0.600
- Risk recall (expected WARNING or VIOLATION, predicted not PASS): 0.525
- Violation recall (expected VIOLATION, predicted not PASS): 0.900
- PASS specificity: 0.900

## Interpretation

The rule layer already catches most explicit violations. This supports the current architecture: deterministic rules are useful for clear prohibited expressions such as guaranteed returns, principal safety, no-loss claims, and unsupported superiority claims.

The weak area is WARNING detection. Many caution-level cases are intentionally contextual, such as insufficient conditions for minimum interest rates, visual salience concerns, and unsupported “popular/recommended” phrasing. These are expected to require LLM, layout-aware OCR review, or additional warning rules.

## Immediate Tuning Candidates

Do not tune thresholds yet. The first concrete improvement should be rule/pattern quality:

- False negative: `원금은 100% 안전하게 보장` was missed because the current principal-guarantee regex expects `원금` and `보장/안전` to be very close.
- False negative: `투자 손실이 나도 원금을 지켜드리는 상품` was missed because “원금을 지켜드림” is not covered.
- False positive: `법정 최고금리` was caught as unsupported “최고” wording. Add an exclusion for statutory/legal maximum-rate contexts.
- False positive: `펀드 가입 시 판매보수와 운용보수... 투자설명서 확인` was caught as missing loss disclosure. This is a borderline test case; either change expected label to WARNING or require investment-risk wording in PASS examples.

## Next Baseline Runs

- Run LLM-assisted sample evaluation on the 20 WARNING cases only.
- Add OCR image cases after OCR normalization is stable.
- After OJK citation correction, build a smaller Indonesian dataset: 10 PASS / 10 WARNING / 10 VIOLATION.

## Update: 2026-05-26

Added `금소법_17조_적합성원칙.yaml` to cover suitability-principle risks:

- 무차별 고위험상품 권유
- 취약고객 대상 고위험상품 권유
- 고위험상품 안전 오인 표현
- 투자성 상품에서 적합성 확인 없는 즉시 가입 유도

Current rule-first baseline after applying the 17조 tree:

- Exact accuracy: 0.650
- Risk recall (WARNING or VIOLATION): 0.575
- Violation recall (not PASS): 1.000
- PASS specificity: 0.950

The remaining false negatives are mainly contextual WARNING cases. This is expected because warning-level 판단 requires layout salience, missing-condition analysis, or LLM judgment rather than only deterministic phrase matching.

OCR quality guard was added. Low-resolution or compressed images are now classified as low OCR confidence and routed to manual review instead of being treated as reliable extracted text.
