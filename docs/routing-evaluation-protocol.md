# Adaptive Routing 평가 프로토콜

> 버전: draft-2
> 기준일: 2026-07-18
> 대상: Claude Code와 Codex CLI를 고르는 routing 정책

## 1. 목적과 estimand

주 질문은 “두 agent를 같은 횟수 사용했는가?”가 아니다.

```text
목표 작업분포에서, 고정된 안전·자원 조건 아래 어떤 정책이
objective verified quality를 가장 높이는가?
```

두 보조 질문도 분리한다.

1. 같은 task를 양쪽에 맡겼을 때 agent 간 paired difference는 얼마인가?
2. 실제 auto traffic에서 새 정책은 baseline보다 나은가?

첫 질문은 격리된 paired experiment로 답한다. 현재 목표 workload 빈도가 측정되지
않았으므로 pilot primary estimand는 **사전 정의한 stratum별 paired effect**다.
20/20/20 quota의 비가중 평균을 실제 workload policy value라고 부르지 않는다.
둘째는 장기적으로 prospective
randomized overlap이 필요하지만 현재 traffic에서는 보류하고 paired 정책 replay로
가설만 좁힌다. manual 선택과 escalation은 다른 data-generating process이므로
분리한다.

## 2. 사전 등록할 것

첫 결과를 보기 전에 실험 manifest를 version control에 남긴다.

```text
protocol_version
task_set_version / task source
eligible agent/model/CLI/environment epoch
workspace base revision과 fixture hash
evaluator id/version/role/aggregation
primary/secondary metrics
strata와 minimum reporting cells
non-inferiority margin 또는 minimum useful improvement
confidence level과 interval method
maximum execution/resource budget
stopping, pause, exclusion rule
random seed와 order assignment rule
```

결과를 본 뒤 바꾼 분석은 금지하지 않지만 `exploratory`로 표시한다.

## 3. Cohort 분리

| Cohort | 생성 방식 | 쓸 수 있는 결론 |
|---|---|---|
| legacy | 과거 실행, propensity 없음 | schema/실패 유형 진단 |
| paired | 같은 task를 양쪽 agent가 독립 실행 | agent head-to-head |
| shadow | 실제 실행 없이 여러 정책이 결정 | eligibility/coverage/재현성 |
| prospective | 미래의 safe auto task에서 알려진 확률로 선택 | support가 있는 overlap region의 policy effect |
| manual | 사용자가 agent 지정 | 사용 패턴, 자동 정책 비교 제외 |
| escalation | outcome/task-analysis 이유 중 하나 이상으로 두 번째 실행 | reason-set 조건부 recovery 성능 |

cohort 간 row를 단순 합쳐 성공률을 만들지 않는다.

## 4. Task set과 층화

### 4.1 Pilot 구성

초기 paired pilot의 계획 단위는 60 task, 120 execution이다.

- instruction language: native Korean 20, native English 20, mixed 20;
- 주요 task category: implementation, debugging, testing, refactoring,
  repository analysis/planning;
- repository language: 현재 실제 사용 언어를 반영하되 Python 하나에만 몰리지 않게
  다음 round에서 확장;
- risk: low 중심. destructive, secret-bearing, production mutation task 제외;
- evaluator: task-specific objective evaluator가 있는 task만 포함.

60은 우열이나 language×category cell 순위를 보장하는 표본수가 아니라 pipeline,
discordant-pair rate, variance, 결측과 failure mode를 추정하는 pilot이다. 3개 언어와
5개 category를 완전 교차하면 cell당 평균 4개뿐이므로 cell별 결론을 내리지 않는다.
pilot 결과로 확증 round의 표본수와 보고 가능한 strata를 계산한다.
확증 round는 pilot에 없던 신규 task를 사용한다. 목표 workload aggregate가 필요하면
agent 선택과 독립적인 intake에서 stratum 빈도를 먼저 측정하고 weighting rule을
확증 전에 고정한다.

### 4.2 Native task 원칙

- Korean task는 English 원문을 단순 번역한 것만으로 구성하지 않는다.
- Korean README/issue/acceptance criteria가 자연스럽게 포함된 task를 둔다.
- mixed task는 코드·identifier는 English이고 설명·검증 기준은 Korean인 실제 작업
  형태를 포함한다.
- 동일 의미 번역쌍은 언어 민감도 측정용 별도 subset으로 두고 native set과 합치지
  않는다.
- 번역쌍은 agent 실행 전 `TaskAnalyzer`에도 통과시켜 inferred capability,
  difficulty, risk, uncertainty, escalation eligibility의 언어 대칭성을 검사한다.

### 4.3 최소 metadata

```text
task_id / task_set_version / source
instruction_language
repository_code_language / repository_doc_language
task_category / required_capabilities
risk / mutation_scope / read_only
objective evaluator id/version
fixture/base revision/hash
estimated time/resource bucket
```

개인 식별정보나 추론된 사용자 국적·문화권은 저장하지 않는다.

### 4.4 Target workload intake

paired quota는 agent 차이를 비교하기 위한 실험분포이며 실제 target workload의
빈도를 나타내지 않는다. Phase 0부터 agent 선택과 독립적인 intake에서 4.3의
metadata를 같은 schema/version으로 집계한다. raw prompt나 사용자 문화권을
저장하지 않고 unknown 비율과 관측 기간을 함께 보고한다.

이 intake는 Phase -1이나 stratum별 paired effect의 선행조건이 아니다. 다만
target-workload-weighted policy value, aggregate best-single, overall 개선 주장을
하려면 대표성 검토를 통과한 intake 빈도와 확증 시작 전에 고정한 weighting rule이
필요하다. 충분한 표본이 없으면 해당 aggregate를 계산하지 않는다.

## 5. Paired experiment 실행

각 task에서 다음을 지킨다.

1. 동일한 clean base revision으로 격리 workspace A/B를 만든다.
2. agent 실행 순서를 task별로 무작위화하고 assignment를 기록한다.
3. 두 agent는 상대 결과와 상대 prompt/output을 보지 못한다.
4. model, reasoning tier, CLI version, permission mode, time limit을 manifest대로
   고정한다.
5. network, secret, push, production 접근은 task fixture에서 제거한다.
6. 동일한 objective evaluator를 agent-blind하게 실행한다. evaluator와 golden
   fixture는 agent-writeable workspace 밖의 read-only 경로에 두며 실행 전후 hash를
   확인한다. 깨끗한 평가 checkout에 agent diff만 적용한다.
7. 실행 시작·종료·중단과 evaluator별 결과를 append-only event로 남긴다.
8. 한 실행이 중단돼도 다른 실행을 임의 제외하지 않는다. pair 상태를
   `complete`, `one-sided failure`, `incomplete`로 명시한다.

순서 효과가 발견되면 workspace 격리가 실패했는지 먼저 조사한다. 동일 저장소를
순차 실행해 첫 agent의 변경을 두 번째가 보는 방식은 paired experiment가 아니다.

## 6. 평가자

### 6.1 우선순위

1. task-specific deterministic acceptance test;
2. golden output/patch invariant;
3. 명시적 property/integration evaluator;
4. 독립 human rubric;
5. blind multi-judge panel.

lint, typecheck, command exit, process completion은 constraint/reliability 지표이지
그 자체로 objective quality가 아니다.

`testing` task에서는 agent가 작성한 test가 자기 자신을 증명하지 못하게 hidden
buggy implementation, mutation testing, 또는 외부 held-out test로 test quality를
평가한다. 이 평가자를 준비하지 못하면 해당 category를 확증 set에서 제외한다.

### 6.2 Subjective 평가가 필요한 경우

- agent/model 이름과 비용을 숨긴다.
- A/B 출력 순서를 무작위화하고 일부를 역순으로 재평가한다.
- 가능하면 서로 다른 model family의 judge를 사용한다.
- Korean/English/mixed별 agreement와 acceptance rate를 각각 계산한다.
- 사람이 만든 gold/audit subset으로 judge calibration을 확인한다.
- position/language disagreement가 threshold를 넘으면 해당 judge score를 primary
  endpoint에서 제외하고 결과를 보류한다.

judge prompt와 rubric도 evaluator version의 일부다.

## 7. 지표

### 7.1 Primary

```text
paired objective-quality risk difference
  = P(Claude pass, Codex fail) - P(Codex pass, Claude fail)
```

pilot과 확증 benchmark에서는 사전 정의한 stratum별 effect를 primary로 둔다.
target workload weight가 독립적으로 측정된 뒤에만 fixed resource envelope에서의
가중 objective verified success를 policy primary로 둘 수 있다. pass/fail이 아닌
bounded score면 paired score difference도 함께 보고한다.

### 7.2 Secondary

- reliability success와 interrupted/timeout rate;
- constraint/safety violation;
- wall time과 token/common resource unit. 서로 다른 tokenizer나 언어의 raw token을
  그대로 agent 간 동일 비용 단위로 보지 않음;
- 양쪽에서 관측 가능할 때만 현금 비용;
- cost/time per verified success;
- modified-file scope와 unexpected change;
- predicted quality calibration;
- exploration regret와 circuit-breaker activation;
- evaluator coverage와 missingness;
- 전체·각 stratum·worst-stratum 결과.

평균만 보고하지 않는다. 어떤 task/language group이 손해를 봤는지 함께 표시한다.

## 8. 통계 분석

### 8.1 Paired 결과

- 2×2 pass/fail 표와 win/tie/loss를 항상 제시한다.
- binary discordant pair는 exact McNemar/binomial 방식과 paired risk-difference CI를
  사용한다.
- score, latency, resource는 paired difference와 seed가 고정된 bootstrap 또는
  exact paired permutation CI를 사용한다.
- overall 95% CI와 주요 사전등록 strata CI를 보고한다.
- 다중 strata의 확증적 판정에는 Holm 보정 등 사전 등록한 방식을 사용한다.

60-task pilot에는 고정 CI 폭이나 유의성 목표를 붙이지 않는다. discordant-pair
rate의 보수적 신뢰한계 또는 사전 정의한 internal-pilot sample-size re-estimation,
목표 effect/non-inferiority margin, 원하는 power와 confidence level로 **신규** 확증
round 크기를 계산하고 다음 round 전에 고정한다. 핵심 stratum에 필요한 표본을
모을 예산이 없으면 그 stratum의 승격 판정을 하지 않는다. 넓은 CI는 “차이 없음”이
아니라 “불확실”이다.

분석 코드는 runtime core와 분리하되 재현 가능한 version/seed를 가진다. stdlib로
exact/bootstrapped 통계를 구현하면 알려진 R/SciPy fixture와 대조하는 golden test를
둔다. 검증된 외부 분석 도구를 쓸 경우 core dependency로 추가하지 않고 실험
environment manifest에 고정한다.

### 8.2 Prospective policy 결과

- 실제 선택 propensity를 사용한다.
- 평가할 target policy 또는 policy class, clipping, feature version을 사전 정의한다.
- IPS/DR point estimate와 함께 effective sample size, CI, maximum weight를 보고한다.
- support가 약하거나 ESS가 최소 기준 미만이면 policy 순위를 거부한다.
- legacy/manual/escalation/paired data를 ordinary auto propensity 표본처럼 사용하지
  않는다.
- always-Claude/always-Codex처럼 overlap 밖의 action을 요구하는 정책은 prospective
  IPS로 전체 workload 성능을 추정하지 않는다. 대표 paired cohort에서만 비교한다.
- overlap/positivity는 IPS와 DR의 식별 조건이다. prospective randomized cohort에서는
  실제 propensity를 선택 전에 기록하므로 logging policy model은 알려져 있다.
  이론적으로 DR의 일관성은 propensity 또는 outcome model 중 하나의 정확성으로
  성립할 수 있지만, 이 프로젝트는 분산 감소와 추가 robustness를 확인하기 위해
  별도의 objective-quality sample과 time-ordered 검증을 통과한 outcome model이
  있을 때만 DR를 보고한다. 이는 이론적 필요조건이 아니라 사전 등록한 운영
  admission rule이다.

### 8.3 Time과 drift

무작위 train/test split만 사용하지 않는다. model/CLI/environment epoch를 보존한
time-ordered 분석을 수행하고 update 전후 결과를 별도로 보고한다.

## 9. 미래 Prospective overlap 규칙

현재 traffic에서는 실행하지 않는다. 평가할 target policy class를 먼저 고정하고,
월별 auto task, 아래 eligibility를 만족하는 비율, 최대 exploration mass에서 그
policy class의 예상 ESS가 사전 최소값을 넘을 때 별도
protocol version으로 재개한다. paired pipeline과 Phase 0/1 telemetry 검증은
필요조건이지 시작하기에 충분한 조건이 아니다.

- auto, low-risk, isolated, objective-evaluated task만 eligibility;
- 두 후보가 minimum safety/quality floor를 통과하고 uncertainty가 겹치는 경우만;
- 초기 total exploration mass ≤ 0.05;
- high-risk, unverified, direct production mutation은 exploration 0;
- per-day/session traffic와 resource budget을 hard cap;
- timeout/permission/safety 이상이 연속 발생하면 circuit breaker;
- 정확한 candidate probability와 random draw를 selection 전에 기록.

재개 시 0.05는 영구 상수가 아니라 보수적 시작값이다. exploration regret, safety,
ESS를 검토해 유지·감소·중단하며, 증가하려면 별도 승인 기준을 통과해야 한다.

## 10. 중단·제외·결측 규칙

### 즉시 중단

- secret/production 접근 또는 예상 밖 외부 변경;
- evaluator가 서로 다른 fixture/version을 사용함;
- workspace 격리 실패;
- propensity가 선택 뒤에 기록되거나 누락됨;
- 반복되는 permission/safety 위반;
- resource hard cap 초과.

### 결과에서 제외할 수 있는 경우

task 자체 fixture가 깨졌거나 양쪽 모두 실행 전 infrastructure failure인 경우만
사전 규칙에 따라 제외한다. agent failure, timeout, one-sided interruption은 성능
결과이며 편의상 제거하지 않는다. 모든 제외 row와 사유를 공개한다.

### 결측

- evaluator 미실행: quality unobserved;
- cost 미노출: cost unknown;
- terminal event 없음: incomplete 후 reconcile;
- subjective judge disagreement: unresolved/needs audit.

결측을 success, failure, zero cost로 자동 대체하지 않는다.

## 11. Policy promotion report

새 정책마다 다음 표를 채운다.

| 항목 | Baseline | Candidate | Difference/CI | 통과 여부 |
|---|---:|---:|---:|---|
| pooled/quota objective quality (not workload value) | | | | |
| target-workload-weighted objective quality (weights available only) | | | | |
| Korean | | | | |
| English | | | | |
| mixed | | | | |
| worst task stratum | | | | |
| safety violations | | | | |
| interrupted/timeout | | | | |
| time/resource per verified success | | | | |
| propensity completeness | | | | |
| OPE ESS | | | | |

policy는 point estimate 하나로 승격하지 않는다. 사전 정의한 비열등성/개선 기준,
safety, strata, data integrity를 모두 통과해야 한다.
target workload weight가 없거나 대표성 검토를 통과하지 못하면 weighted row는
`not estimable`로 두며 pooled/quota 결과를 대신 policy value라고 부르지 않는다.

## 12. 구현 전 dry run

실제 agent를 호출하지 않고 다음을 먼저 검증한다.

- manifest와 task metadata schema validation;
- seeded order assignment 재현성;
- 두 workspace base hash 동일성;
- evaluator 역할/버전/aggregation 고정;
- lifecycle event idempotency와 interrupted reconciliation;
- propensity 합 1, selected probability 일치;
- 분석기가 synthetic 2×2 결과와 결측을 올바르게 처리;
- report가 희소 stratum의 순위를 거부.

dry run과 작은 4-task smoke pair가 성공한 뒤 60-task pilot을 시작한다.
