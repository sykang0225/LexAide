# FN Review Checklist

목적: 현재 평가셋에서 위험 케이스인데 PASS로 빠진 문구를 사람이 검수해, 실제로 트리/패턴/LLM 프롬프트를 조정할지 결정합니다.

판단 기준:
- `WARNING 유지`: 법적으로 단정 위반은 아니지만 준법관리자 검토 대상이면 선택
- `VIOLATION 상향`: 명시적 금지 표현 또는 필수 정보 누락이 명확하면 선택
- `PASS 변경`: 테스트셋 라벨이 과도했고 실무상 통과 가능한 문구라면 선택
- `LLM 전용`: 룰로 잡기에는 넓어서 오탐이 커질 가능성이 있으면 선택

| ID | Suite | 현재 | 기대 | 유형 | 문구 | 검수 질문 | 네 판단 | 후속 조치 |
|---|---|---|---|---|---|---|---|---|
| KO_WARN_008 | ko | PASS | WARNING | 빠른 심사 강조 | 최대 1시간 이내 빠른 심사로 필요한 자금을 바로 확인하세요. | WARNING 이상으로 올릴까? | 미검수 |  |
| KO_WARN_011 | ko | PASS | WARNING | 고객 선택 표현 | 많은 고객이 선택한 인기 상품으로 편리하게 자산을 관리하세요. | WARNING 이상으로 올릴까? | 미검수 |  |
| KO_WARN_013 | ko | PASS | WARNING | 낮은 부담 강조 | 매월 부담을 낮춘 합리적인 대출 상품입니다. | WARNING 이상으로 올릴까? | 미검수 |  |
| KO_WARN_015 | ko | PASS | WARNING | 한정성 권유 | 이번 달 특별 혜택으로 더 좋은 조건을 확인해보세요. | WARNING 이상으로 올릴까? | 미검수 |  |
| KO_WARN_018 | ko | PASS | WARNING | 대상 조건 부족 | 직장인 누구나 가능한 간편 대출, 지금 한도를 확인하세요. | WARNING 이상으로 올릴까? | 미검수 |  |
| KO_WARN_020 | ko | PASS | WARNING | 근거 없는 추천 | 초보 투자자에게 가장 적합한 상품으로 추천드립니다. | WARNING 이상으로 올릴까? | 미검수 |  |
| ID_VIOL_005 | ojk | PASS | VIOLATION | guaranteed monthly profit | Keuntungan bulanan dijamin tanpa risiko kerugian. | WARNING 이상으로 올릴까? | 미검수 |  |
| ID_VIOL_007 | ojk | PASS | VIOLATION | no loss | Nasabah tidak mungkin mengalami kerugian dari produk ini. | WARNING 이상으로 올릴까? | 미검수 |  |

## 검수 우선순위

1. `ID_VIOL_005`, `ID_VIOL_007`: OJK 명시 위반인데 PASS로 빠진 케이스라 우선 수정 대상입니다.
2. `KO_WARN_018`, `KO_WARN_020`: 실제 광고에서 자주 나올 수 있는 표현이라 WARNING 유지 여부를 먼저 판단해야 합니다.
3. `KO_WARN_008`, `KO_WARN_011`, `KO_WARN_013`, `KO_WARN_015`: 넓게 잡으면 오탐이 늘 수 있어 LLM 전용 또는 약한 WARNING 룰이 적절합니다.

CSV 편집용 파일: `fn_review_checklist.csv`