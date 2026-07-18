# Adaptive Routing 개선 작업 진행상황

> 마지막 갱신: 2026-07-18
> 상태: Phase -1/0/1 구현 완료, Phase 2a paired smoke tooling 대기
> 목적: 다른 세션이 결정 근거와 다음 순서를 잃지 않고 작업을 이어간다.

## 1. 목표

`--agent auto`가 과거의 편향된 선택 기록을 실력 차이로 오인하지 않게 하고,
Claude/Codex 중 목표 작업에 더 적합한 agent를 정확하고 효율적으로 선택한다.

여기서 성공은 agent 사용 비율을 맞추는 것이 아니다. 다음 네 편향을 통제하면서
목표 작업분포의 **objective verified quality**를 높이는 것이다.

1. workload composition: 애초에 한 agent에 어울리는 task만 들어옴;
2. selection/exposure: 선택된 agent 결과만 관측됨;
3. evaluator: verifier/judge가 특정 출력·언어를 선호함;
4. environment: model, CLI, permission, cache 변화가 agent 실력처럼 보임.

## 2. 현재까지 완료한 것

### 코드와 telemetry 감사

- `verification.py`, `domain.py`, `history.py`, `routing.py`, `workflow.py`,
  `kernel.py`, `process_runner.py`, CLI 경계를 확인했다.
- 로컬 `.orchestrator/executions.jsonl` 12건을 진단했다.
  - Claude 4, Codex 8;
  - auto 4, manual Claude 3, manual Codex 3, legacy 2;
  - passed verification 9, skipped 3;
  - candidate propensity 0건;
  - 비용 sample은 Claude 쪽 일부만 존재.
- 현재 표본은 policy 순위가 아니라 schema/실패 진단에만 쓸 수 있다고 결론냈다.

이 12건은 연구 감사 당시 snapshot이다. 이후 설계 검토용 Claude 호출 3건(네트워크
차단 실패 1, 1차 성공 1, 상세 근거를 준 2차 성공 1)이 수동 실행으로 추가되어
당시 로그는 15건이었다. 2026-07-18 연구 근거 중심 재검토의 실패 1건과 성공
2건이 더해져 현재 로그는 18건(Claude 10, Codex 8; completed 15, failed 3)이다.
추가 3건도 manual review attempt이며 정책 표본으로 합치지 않는다.

### 확인한 구현 결함

- verifier 없는 완료도 execution success로 집계됨;
- test/lint/typecheck/diff 등 verifier 역할이 구분되지 않음;
- 최종 실행 뒤에만 log를 써서 인터럽트 시 evidence가 사라질 수 있음;
- policy/version/candidate probability/cohort/language/environment epoch가 없음;
- escalation 표본이 ordinary execution과 통계적으로 분리되지 않음;
- 비용 결측이 agent 간 비교 가능한 형태가 아님.

### 연구 교차검토

- 고전 contextual bandit, IPS/DR/CRM, conservative exploration을 검토했다.
- 2024~2026 routing, agentic/temporal routing, unseen-model transfer, conformal
  calibration을 검토했다.
- 중국·홍콩·한국·싱가포르·인도·동남아 관련 연구와 native-language benchmark를
  추가했다.
- complex router가 simple baseline을 압도하지 못하는 결과, rare-case recall,
  router attack/threshold fragility, multilingual judge bias를 포함했다.
- 연구기관의 지리적 다양성만으로 관점 독립성을 주장하지 않기로 했다.

자세한 근거는 [연구 검토](routing-research-review.md)에 있다.

### 설계 결정

- 기존 VCR-UCB 즉시 도입 결정을 철회했다.
- typed evaluator와 durable event를 먼저 만드는 evidence-first 순서를 택했다.
- 최종 정책을 ESTR evidence ladder로 정의하되 가장 단순한 검증 승자만 승격한다.
- 강제 50:50 대신 paired benchmark를 사용하고, prospective overlap은 충분한
  traffic/support가 생긴 미래에만 최대 0.05에서 검토한다.
- Korean/English/mixed와 task category/worst-stratum을 승격 기준에 넣었다.

### Claude 오케스트레이션 검토

- 이 프로젝트 CLI에서 `--agent claude-code`를 명시해 읽기 전용 검토를 실행했다.
- 첫 호출은 격리 환경 네트워크 차단으로 실패했고, 연결 허용 후 Claude Opus 4.8이
  source/telemetry/doc을 검토했다.
- 구조적 score 편향, usage-token redaction, escalation 생성과정 혼합, pilot 정밀도,
  현재 traffic의 OPE 부적합, legacy objective-quality 0건 문제를 수용했다.
- “모든 history에서 Claude가 절대 이길 수 없음”, “CI와 유의성이 반드시 상호
  배타”, “OPE 영구 삭제”는 범위가 과해 한정 수용했다.
- 수정 문서를 다시 상세 검토시킨 결과, affinity와 confidence blend를 누락한 첫
  원인 분석, agent-writeable evaluator, projector 순서, target workload estimand
  간극을 추가로 확인했다.
- 2차 검토에 따라 Phase -1의 임의 policy 중립화를 철회하고 additive identity와
  오염 라벨링을 먼저 하며 corrected L0는 Phase 1에서 한 번에 정의하기로 했다.
- 2026-07-18에는 연구 원문을 먼저 대조한 주 검토와 Claude의 source-aware 재검토를
  교차시켰다. Claude는 큰 설계와 Phase -1 readiness에 동의했고, DR의 이론/운영
  조건, overall metric, target workload intake와 비용 비대칭 문구만 정밀화했다.

실행 환경과 항목별 판단은 [Claude 독립 검토](routing-claude-review.md)에 있다.

자세한 설계는 [Adaptive Routing v2](adaptive-routing-v2.md), 실험 절차는
[평가 프로토콜](routing-evaluation-protocol.md)에 있다.

## 3. 왜 이 순서인가

```text
additive identity + policy/cohort labels
  -> typed/protected evaluator
  -> durable lifecycle log
  -> deterministic replay + simple baselines
  -> paired benchmark
  -> estimator promotion
  -> optional temporal/budget sophistication
  -> optional prospective overlap/OPE when traffic supports it
```

- label 의미가 틀리면 더 정교한 학습기가 오류를 더 빠르게 학습한다.
- started/terminal evidence가 없으면 timeout·중단 비용이 사라진다.
- propensity가 없으면 unselected agent의 policy effect를 평가할 수 없다.
- simple baseline 없이 complex model gain을 구분할 수 없다.
- native-language strata 없이 평균 정확도는 언어별 회귀를 숨긴다.
- paired data 없이 workload composition과 agent 능력을 분리하기 어렵다.
- production 탐색은 안전한 비교 기반을 만든 뒤에만 허용해야 한다.

## 4. 지금 작업 중

- [x] 기존 코드·로그 감사
- [x] 연구 범위 확대와 반례 검토
- [x] 개선 설계 초안 재작성
- [x] paired/언어층화 평가 프로토콜 초안
- [x] 오케스트레이터를 통한 Claude 비판 검토
- [x] Claude 지적을 코드/연구 근거와 대조해 채택·기각 기록
- [x] 수정 문서에 상세 의도·근거를 제공한 Claude 2차 검토와 재반영
- [x] 문서 내부 링크·용어·현재 코드 사실 검증
- [x] 설계 handoff 당시 전체 unit test 실행(136 tests)
- [x] 연구 1차 자료를 대조한 설계 재검토와 Claude source-aware 비판 검토
- [x] 주 검토자의 교차판단을 Claude에 재전달해 합의/불일치 항목 확정
- [x] DR·overall estimand·target workload intake·비용 문구 정밀화
- [x] Phase -1 usage redaction·identity/policy/cohort·duration semantics 구현
- [x] 새 `legacy-biased` row의 routing evidence 편입 동결
- [x] Korean/English `TaskAnalyzer` 번역쌍 zero-cost 회귀 테스트
- [x] Phase -1 완료 후 전체 unit test 실행(152 tests)
- [x] Phase 0A evaluator role/API 의미 분리
- [x] Phase 0B legacy evaluator migration smoke
- [x] Phase 0 완료 후 전체 unit test 실행(161 tests)
- [x] Phase 1 durable lifecycle event와 replay/reconciliation
- [x] versioned routing context와 corrected static L0
- [x] protected event-derived state 기반 simple shadow baseline
- [x] Phase 1 완료 후 전체 unit test 실행(191 tests)

Phase -1은 routing score의 corrected L0를 임의로 만들지 않고 기존 legacy evidence는
그대로 유지했다. 대신 모든 새 workflow row를 `routing_evidence_eligible=false`로
기록해 현재 biased policy가 새 실력 evidence를 더 쌓지 않게 했다.

## 5. 다음 구현 작업

### Phase -1 — 추가 오염 차단 (완료)

예상 수정 위치:

```text
src/adaptive_orchestrator/domain.py
src/adaptive_orchestrator/logging.py
src/adaptive_orchestrator/history.py
src/adaptive_orchestrator/workflow.py
src/adaptive_orchestrator/routing.py
```

구현한 일:

- usage count(`input_tokens` 등)는 보존하고 credential token은 가리는 redaction;
- stable execution/attempt ID, timestamp, policy version/config hash 추가;
- escalation 전체 reasons를 보존하고 outcome/task-analysis trigger class를 집합으로
  파생하며 legacy cohort를 가능한 범위에서 소급 라벨링;
- duration sample count와 missing semantics 수정;
- Korean/English 번역쌍의 `TaskAnalyzer` 대칭성 zero-cost test.

추가로 legacy reader는 `routing_decision.selected_agent`와 중첩
`escalation.reasons`가 있는 범위에서 selection mode/cohort/trigger class를 파생한다.
번역쌍 진단에서 한국어 일반 단어 `작성`이 code generation을 과잉 추론하고
`overwrite`의 대응어 `덮어쓰기`가 risk에서 빠진 비대칭을 발견해 수정했다.

corrected L0를 정의하기 전까지 새 실력 evidence를 모을 목적으로 `--agent auto`를
사용하지 않는다. Phase -1에서 근거 없는 중립값으로 선택 정책을 바꾸지 않는다.
명시적 agent 선택은 manual cohort로 기록한다.

### Phase 0A — evaluator 의미 분리 (완료)

예상 수정 위치:

```text
src/adaptive_orchestrator/domain.py
src/adaptive_orchestrator/verification.py 또는 새 evaluation.py
src/adaptive_orchestrator/workflow.py
src/adaptive_orchestrator/history.py
src/adaptive_orchestrator/cli.py
tests/test_verification.py
tests/test_workflow.py
tests/test_history.py
```

구현한 일:

- `EvaluatorSpec`, `EvaluatorResult`, role, version, observed와 evaluator별 출력을 추가;
- 기존 `VerificationResult`는 workflow 제어용 aggregate로 유지;
- 기존·신규 `--verify-command`는 보수적으로 `constraint`로만 projection;
- process terminal은 `reliability`로 기록하고 quality/constraint/safety/resource와
  서로 대체하지 않음;
- repeatable `--quality-evaluator-command`와 artifact/time-limit 입력 추가;
- 품질 evaluator는 agent workspace 밖의 직접 참조한 read-only artifact를 요구하고,
  agent 실행 전 baseline과 evaluator 실행 전후 content hash를 검증;
- task-specific quality command의 객관적 pass/fail에만 1/0 score를 부여하며,
  skipped/error/untyped verifier에는 quality score를 만들지 않음.

확정한 작은 API 결정:

- `--verify-command`의 기본 role은 `constraint`다.
- task-specific evaluator는 별도 `--quality-evaluator-command`로 받는다.
- 여러 quality result는 현재 합치지 않는다. 사전 버전된 aggregation rule을 담을
  실험 manifest가 생길 때까지 evaluator별 score를 그대로 보존한다.

### Phase 0B — evaluator migration smoke (완료)

예상 수정 위치:

```text
src/adaptive_orchestrator/workflow.py
tests/test_verification.py
tests/test_workflow.py
```

구현하고 검증한 일:

- single/multi legacy command가 동일 aggregate 동작을 유지하면서 constraint result로
  변환되는 fixture;
- workspace-local artifact와 실행 중 artifact mutation 탐지;
- evaluator별 observed/role/version/score와 5개 role projection;
- legacy 전체 regression suite 통과가 quality observation을 만들지 않는 history test.

### Phase 1 — replay와 baseline (완료)

예상 새 모듈:

```text
routing_context.py
routing_policy.py  # 초기에는 context/model 책임도 함께 둘 수 있음
routing_state.py
replay.py
events.py
```

구현한 일:

- required/inferred capability를 분리한 `routing-context-v1` pure projection;
- 명시적 configured baseline만 쓰고 vendor skill prior를 제거한
  `corrected-static-l0-v1`;
- deterministic active candidate/selected propensity와 모든 shadow decision을 agent
  실행 전에 selection event로 기록;
- fsync append-only selection/start/terminal-or-reconciled/evaluation/finalize event;
- event ID idempotency/collision, sequence gap, transition 검증과 atomic derived state;
- KeyboardInterrupt 시 child kill/reap 후 terminal/finalized를 기록하고 예외 재전파;
- live PID/host와 충돌하지 않는 abandoned reconciliation;
- CLI event/state를 agent workspace 밖의 private control directory로 분리;
- exact agent → base agent와 environment/task/language의 deterministic backoff;
- always-agent, corrected static, legacy adaptive/history-free profile, best-single,
  stratified Beta/greedy, seeded random-safe shadow baseline;
- 동일 event/state/config/seed replay digest와 decision 재현;
- legacy execution replay는 schema/record reproduction 전용이며 counterfactual support를
  항상 false로 보고.

### Phase 2a — paired smoke tooling (다음)

먼저 실제 agent 8회를 호출하지 않고 다음 dry run을 구현한다.

- versioned paired manifest와 task/evaluator/base revision schema validation;
- 동일 clean base에서 격리 workspace A/B 생성과 base hash 비교;
- seed 기반 agent 실행 순서 배정과 pair/task/attempt ID 고정;
- 양쪽에 동일한 외부 evaluator artifact/version/hash 적용;
- `paired` cohort, one-sided failure, incomplete pair projection;
- 실행 없는 synthetic 2×2 결과가 수동 집계와 같은지 검증.

dry run이 통과하고 4개 low-risk task와 보호된 objective evaluator가 준비된 뒤에만
4-task/8-execution smoke를 별도 승인 범위에서 실행한다.

### Phase 2b 이후

- 4-task/8-execution smoke pair 후 60-task/120-execution paired pilot;
- Korean/English/mixed native task와 agent-blind objective evaluator;
- pilot discordance의 보수적 한계로 신규 확증 round의 표본수와 strata를 계산;
- 충분한 paired evidence가 생긴 뒤 L2/L3/temporal 단계 비교;
- prospective overlap은 월별 traffic/support/예상 ESS threshold를 넘을 때만 재검토.

### 병렬 측정 — target workload composition

- Phase 0부터 agent 선택과 독립적인 task intake metadata를 versioned schema로 집계;
- 관측 기간, unknown/missing, drift와 weighting rule을 확증 전에 고정;
- 대표성 있는 weight가 없으면 workload-weighted policy value와 aggregate
  best-single/overall 순위를 보고하지 않음;
- 이 측정은 Phase -1과 stratum별 paired 평가를 막지 않음.

## 6. 구현별 필수 테스트

### Evaluator

- unverified completion은 quality update를 만들지 않음;
- constraint pass가 quality pass가 되지 않음;
- evaluator error/timeout/skipped의 observed semantics;
- 여러 evaluator aggregate가 사전 rule을 따름;
- legacy `command`와 `commands` row가 읽힘.
- evaluator/golden hash 변경과 agent-written test 오염을 탐지함.

### Event durability

- 시작 event가 subprocess 전에 기록됨;
- success/failure/timeout/interrupt 모두 terminal 또는 reconciled;
- duplicate event가 state를 두 번 갱신하지 않음;
- sequence gap/invalid transition 탐지;
- event만으로 state 재구축.

### Routing

- explicit agent는 확률 1;
- ineligible agent는 확률 0, 합은 1;
- high-risk/unverified는 explore하지 않음;
- unknown cost를 0으로 쓰지 않음;
- cohort를 섞지 않음;
- global time이 흐르면 unselected arm evidence도 낡음;
- language/task strata fallback이 deterministic;
- static prior가 measured sample로 노출되지 않음.
- ko/en 번역쌍의 analyzer 차이를 측정하고 의도하지 않은 escalation을 탐지;
- 저표본의 더 좋은 arm이 confidence shrinkage만으로 순위 역전되지 않음;
- affinity/complexity/risk 각 component의 reachable score range가 기록됨.

### Experiment tooling

- 두 workspace base hash 일치;
- evaluator는 agent-writeable workspace 밖에 있고 전후 hash가 일치;
- order randomization 재현;
- one-sided failure를 편의상 제외하지 않음;
- propensity/ESS/CI 누락 시 promotion 거부;
- 희소 stratum에서 “동률” 대신 “불확실” 보고.

## 7. 완료 정의

이번 **문서 검토 작업**의 완료 조건:

- 연구·설계·프로토콜·진행상황 문서가 서로 링크됨;
- Claude 비판 검토와 반영 판단이 이 문서에 남음;
- 문서가 현재 코드를 구현 완료라고 잘못 표현하지 않음;
- Markdown/링크 기본 검증과 기존 test suite가 통과함;
- 변경사항과 아직 구현하지 않은 범위가 최종 보고됨.

전체 **routing 개선**의 완료 조건은 설계 문서의 promotion criterion을 만족한
정책이 기본값으로 승격되고 rollback과 실제 cohort monitoring이 동작하는 것이다.
prospective/OPE는 future gate가 열릴 때만 완료 범위에 추가한다.

## 8. 재개 절차

다음 세션은 먼저 아래를 실행한다.

```bash
git status --short --branch
sed -n '1,260p' docs/adaptive-routing-progress.md
sed -n '1,260p' docs/adaptive-routing-v2.md
sed -n '1,240p' docs/routing-evaluation-protocol.md
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

그 다음 이 문서의 “지금 작업 중”에서 첫 미완료 항목을 선택한다. Phase -1/0/1은
완료됐으므로 Phase 2a의 paired smoke tooling dry run부터 진행한다.
사용자 요청 없이
production traffic 탐색, 실제 120회 agent 실행, 외부 push를 시작하지 않는다.

## 9. 작업상 주의사항

- 현재 `docs/adaptive-routing-v2.md`는 설계 작업에서 전면 재작성된 변경 상태다.
  다른 사용자 변경을 덮어쓰지 않았는지 commit 전에 확인한다.
- 현재 branch는 `main`; 이 문서 작성 시작 시 `origin/main`과 같은 위치였다.
- 설계 문서 작성 당시 별도 shell 변경을 포함한 136 tests가 통과했다. Phase -1
  기준선은 152 tests, Phase 0은 161 tests, Phase 1은 191 tests이며 모두 통과했다.
- 연구 링크는 외부 자료이며 최신 preprint 상태가 바뀔 수 있다.
- KB/Wiki prior는 설계 힌트이지 ground truth가 아니다. 현재 코드로 확인한 사실만
  구현 진단으로 기록했다.
- commit/push는 별도 사용자 요청이 있을 때 한다.

## 10. 결정 로그

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-07-17 | Claude 사용률 강제 대신 비교 가능성 확보 | 목표분포가 한 agent에 유리할 수 있음 |
| 2026-07-17 | VCR-UCB 즉시 구현 철회 | label/propensity/durability와 표본이 부족 |
| 2026-07-17 | ESTR evidence ladder 채택 | 데이터 규모에 맞는 가장 단순한 승자를 사용 |
| 2026-07-17 | verifier role typed schema 우선 | command success와 task quality가 다름 |
| 2026-07-17 | paired + native-language strata | workload/evaluator/언어 편향을 분리 |
| 2026-07-17 | prospective를 재개한다면 ≤ 0.05에서 시작 | coding agent는 비싸고 workspace를 변경함 |
| 2026-07-17 | temporal probe는 후속 단계 | trajectory contamination/cache/safety evidence 부족 |
| 2026-07-17 | Phase -1 오염 차단 추가 | current score/redaction/cohort 문제가 새 evidence를 훼손 |
| 2026-07-17 | 60-task를 variance pilot으로 한정 | language×category 확증에는 지나치게 작음 |
| 2026-07-17 | prospective/OPE를 future gate로 이동 | 현재 auto traffic과 support로 ESS 확보 불가 |
| 2026-07-17 | Phase -1에서 policy 중립화 철회 | 정확한 L0 없이 새 편향 epoch를 만들 수 있음 |
| 2026-07-17 | affinity와 confidence blend를 L0 재설계에 포함 | static gap과 저노출 자기강화의 핵심 누락 |
| 2026-07-17 | evaluator를 agent-write 영역 밖에 둠 | agent가 acceptance test를 약화할 수 있음 |
| 2026-07-17 | identity/event 뒤에 projector 구현 | 1:N evaluator와 idempotency를 먼저 정의해야 함 |
| 2026-07-17 | pilot primary를 stratum별 effect로 한정 | target workload 빈도가 아직 관측되지 않음 |
| 2026-07-18 | prospective DR 조건을 운영 admission rule로 명시 | 알려진 propensity와 outcome model의 이론적 역할을 구분 |
| 2026-07-18 | target workload intake를 병렬 track으로 지정 | per-stratum effect와 aggregate policy value의 모집단이 다름 |
| 2026-07-18 | pooled/quota overall과 workload-weighted overall 분리 | weight 없는 quota 평균을 policy value로 오인하지 않음 |
| 2026-07-18 | Phase -1 readiness 재확인 | 연구 원문·코드·Claude 교차검토에서 substantive blocker 없음 |

## 11. 외부 검토 기록

```text
review execution id: current schema에 없음
failed session: 6f768368-c7b6-450e-9059-106524b11475
successful session: 776d7976-ff8b-47a2-9fb8-bbfcc198afe2
model: claude-opus-4-8
reviewed files: routing 문서 4개, architecture.md, 관련 source와 telemetry 일부
accepted findings: score range, token redaction, escalation cohorts, pilot size,
                   OPE feasibility, zero legacy objective-quality, duration/tier gaps
qualified findings: global impossibility claim, CI/significance incompatibility,
                    permanent OPE deletion, newest preprint dependence
resulting changes: Phase -1, paired smoke, pilot repurposing, OPE future gate,
                   별도 review record 추가
unresolved: corrected static policy의 정확한 중립값, confirmatory sample size,
            future traffic/ESS threshold
```

전체 판단은 [Claude 독립 검토](routing-claude-review.md)를 본다.

2차 상세 재검토:

```text
session: 1649564f-19d3-4bba-88f4-16e915823304
model: claude-opus-4-8
duration: 851.4s
turns: 36
cost: $3.716420
accepted: affinity/confidence exposure loop, additive Phase -1, evaluator isolation,
          sample-size timing, event-before-projector, language analyzer confounder,
          stratum estimand, target-policy-dependent ESS
qualified: confidence blend는 현재 review 호출로 Claude 표본이 5를 넘었지만
           초기 snapshot과 신규 tier/arm에서 구조적 위험은 유지
external research: Claude의 web 권한은 거부됨; 1차 자료는 별도 검토에서 확인
file changes by Claude: none
```

2026-07-18 연구 근거 중심 재검토와 교차합의:

```text
failed session: 36059e9d-aee8-4158-bbbe-55dbbd15b91a (ENOTIMP, $0)
source-aware session: a5c96e8d-9dcd-4da6-91b3-106a70cd1c41
model: claude-opus-4-8
duration: 521.1s
turns: 34
cost: $2.5698165
result: Phase -1 ready, no substantive redesign; doc precision edits only
limitations: Claude web/Bash denied; 최신 원문과 telemetry exact count는 주 검토가 별도 확인

reconciliation session: 81254e6b-fa71-4c3d-a5e3-0160b491752f
model: claude-opus-4-8
duration: 244.6s
turns: 22
cost: $1.727474
verdicts: agree 7, partially agree 2, disagree 0
agreement: DR operational rule, overall label/gate, target-workload parallel intake,
           optional cost-path note, stable identity/linkage data contract
unchanged: ESTR/phase/invariants/paired/OPE gate, LLMRouterBench peer-reviewed status,
           multilingual preprint caveat, Phase -1 readiness
file changes by Claude: none
```
