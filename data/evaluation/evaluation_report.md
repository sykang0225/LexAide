# Cross-Check AI Evaluation Report

> **Note.** This report is an **internal regression benchmark**: 105 synthetic cases, **LLM layer OFF** (rule-first baseline).
> It is a separate evaluation from the field-case set cited in the proposal/spec deck — **106 cases (20 real enforcement + 86 statutory), violation recall 0.842 / precision 0.931, LLM ON** — which measures end-to-end performance on real regulator-detected cases. The two sets serve different purposes and their numbers are not comparable.

- Generated: 2026-07-01 02:18
- LLM layer: OFF
- Total cases: 105

## Executive Summary

This report evaluates the system as a compliance risk radar. Exact label matching is tracked, but the key safety metric is risk recall: whether expected WARNING/VIOLATION cases are at least escalated for human review.

## Metrics

| Suite | Cases | Exact Acc. | Risk Recall | Risk Precision | Risk FPR | Violation Recall | TP/FP/FN/TN |
|---|---:|---:|---:|---:|---:|---:|---|
| overall | 105 | 0.800 | 1.000 | 0.921 | 0.171 | 1.000 | 70/6/0/29 |
| ko | 60 | 0.900 | 1.000 | 0.930 | 0.150 | 1.000 | 40/3/0/17 |
| ko_17 | 15 | 0.733 | 1.000 | 0.909 | 0.200 | 1.000 | 10/1/0/4 |
| ojk | 30 | 0.633 | 1.000 | 0.909 | 0.200 | 1.000 | 20/2/0/8 |

## Confusion Matrix

### overall

| Expected \ Predicted | PASS | WARNING | VIOLATION |
|---|---:|---:|---:|
| PASS | 29 | 2 | 4 |
| WARNING | 0 | 20 | 15 |
| VIOLATION | 0 | 0 | 35 |

### ko

| Expected \ Predicted | PASS | WARNING | VIOLATION |
|---|---:|---:|---:|
| PASS | 17 | 2 | 1 |
| WARNING | 0 | 17 | 3 |
| VIOLATION | 0 | 0 | 20 |

### ko_17

| Expected \ Predicted | PASS | WARNING | VIOLATION |
|---|---:|---:|---:|
| PASS | 4 | 0 | 1 |
| WARNING | 0 | 2 | 3 |
| VIOLATION | 0 | 0 | 5 |

### ojk

| Expected \ Predicted | PASS | WARNING | VIOLATION |
|---|---:|---:|---:|
| PASS | 8 | 0 | 2 |
| WARNING | 0 | 1 | 9 |
| VIOLATION | 0 | 0 | 10 |

## Error Review

- Risk false negatives: 0
- Risk false positives: 6
- Exact-label mismatches: 21

### Risk False Negatives

No risk false negatives.

### Risk False Positives

| ID | Suite | Expected | Predicted | Category | Top reason |
|---|---|---|---|---|---|
| KO_PASS_003 | ko | PASS | VIOLATION | 수수료 고지 | 투자성 상품 광고에 원금손실 가능성 미고지 |
| KO_PASS_010 | ko | PASS | WARNING | 한도 조건 | 최대한도만 강조될 경우 실제 적용 가능 범위·심사기준 안내가 충분한지 확인이 필요합니다. |
| KO_PASS_011 | ko | PASS | WARNING | 금리 조건 | 최저금리 적용 조건·우대조건·심사기준 안내가 충분한지 확인이 필요합니다. |
| KO17_PASS_002 | ko_17 | PASS | VIOLATION | 위험등급 고지 | 투자성 상품 광고에 원금손실 가능성 미고지 |
| ID_PASS_003 | ojk | PASS | VIOLATION | loan condition | 수익률·금리·한도 등 유리한 조건을 표시하면서 비용·조건 정보를 충분히 제공하지 않으면 POJK 22/2023상 핵심정보 제공 의무 위반 소지가 있습니다. |
| ID_PASS_010 | ojk | PASS | VIOLATION | neutral wording | 수익률·금리·한도 등 유리한 조건을 표시하면서 비용·조건 정보를 충분히 제공하지 않으면 POJK 22/2023상 핵심정보 제공 의무 위반 소지가 있습니다. |

## Interpretation

- VIOLATION recall is the primary safety metric for regulatory risk. Missed violations can lead to actual non-compliant content distribution.
- WARNING recall is intentionally harder because many caution cases depend on visual salience, missing-condition analysis, or product/customer context.
- The system is designed as a Human-in-the-loop Regulatory Radar: AI escalates likely risks, and compliance officers make final approval decisions.
- Next tuning should focus on reducing WARNING false negatives while preserving violation recall.
