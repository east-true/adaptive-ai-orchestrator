# Adaptive Routing v2: Evidence-First Stratified Temporal Routing

> 상태: Phase -1/0/1과 Phase 2a 실제 paired smoke, post-run reporting/v2 preflight 반영
> 기준일: 2026-07-18
> 관련 문서: [연구 검토](routing-research-review.md),
> [평가 프로토콜](routing-evaluation-protocol.md),
> [Claude 독립 검토](routing-claude-review.md),
> [진행상황과 이어하기](adaptive-routing-progress.md)

## 1. 결정

현재 `AdaptiveRouter`를 곧바로 복잡한 bandit으로 교체하지 않는다. 먼저
품질 증거, 선택 확률, 실행 생명주기, 언어·작업군을 관측할 수 있게 만든 뒤
작은 후보부터 전향적으로 비교한다.

최종 목표 정책은 **ESTR(Evidence-First Stratified Temporal Routing)** 이다.
ESTR은 하나의 고정 학습기라기보다 다음을 결합하는 단계적 정책이다.

1. 필수 능력·권한·위험·자원 조건으로 후보를 거른다.
2. 작업 종류, 지시 언어, 저장소 언어, 평가 강도, 환경 버전을 분리한다.
3. 데이터가 적을 때는 정적 prior와 층화된 단순 추정기를 사용한다.
4. 충분한 전향 데이터에서 더 복잡한 contextual/temporal 모델이 실제로
   이길 때만 승격한다.
5. 낮은 위험과 강한 평가가 있는 동률(equipoise) 구간에서만 작은 확률로
   탐색한다.
6. 품질, 실행 신뢰성, 안전, 비용, 지연을 서로 다른 결과로 유지한다.

“Claude 사용 비율을 의도적으로 늘리는 것”은 목표가 아니다. 목표 작업분포에서
어느 후보가 더 좋은지 알 수 있는 **비교 가능성**을 만드는 것이 목표다. 작업
자체가 Codex에 어울리는 경우 Codex가 더 자주 선택되는 것은 정상이다. 문제는
그 결과만 보고 Claude의 실력이 낮다고 결론내리거나, Claude에 선택 확률 0을
계속 부여해 반사실을 영구히 잃는 것이다.

## 2. 현재 구현에서 확인된 문제

초기 연구 감사 시점의 코드와 12개 로컬 실행 기록 snapshot을 대조했다. 이후
검토 호출까지 포함한 현재 개수와 표본 경계는
[진행상황 문서](adaptive-routing-progress.md)에서 추적한다.

- 초기 감사 snapshot의 자동 선택은 4건뿐이고 전체는 Claude 4건, Codex 8건이다. 정책 우열을
  추정할 표본이 아니다.
- `history.py`는 실행 상태가 `completed`이면 verifier가 없어도 execution
  success로 센다. `workflow.py` 역시 verification이 `skipped`인 완료를
  성공으로 취급한다.
- completion rate와 완료/검증 표본에 조건부인 verification pass rate를 하나의
  quality-like score로 선형 합산한다. 두 값의 모집단과 의미가 다르다.
- `CommandVerifier`의 test, lint, typecheck, diff 확인은 모두 같은 의미로
  합쳐진다. “명령이 성공했다”와 “작업 목표가 달성됐다”를 구분할 수 없다.
- 실행 기록은 CLI 프로세스가 끝난 뒤 한 번에 쓰인다. 인터럽트나 프로세스
  비정상 종료 시 비용·진행·실패가 사라질 수 있다.
- 어떤 정책이 어떤 후보들을 어떤 확률로 고려했는지 기록하지 않는다.
- 작업 지시 언어, 저장소 언어, 작업 출처/cohort, 모델·CLI 환경 epoch가 없다.
- stable execution/attempt ID와 timestamp가 없어 legacy row는 파일 순서 외의
  시간 정보를 제공하지 않는다. evaluator 1:N 관계와 time-ordered 분석의 기반이
  없다.
- Claude 비용만 관측되고 Codex 비용은 관측되지 않는다. 결측을 0으로 두면
  비용 최적화가 왜곡된다. 현재 cost penalty도 관측값이 있는 Claude에만 적용될
  수 있다. `Task.cost_limit_usd`는 이제 structured plan JSON에서 도달 가능하지만
  일반 one-task CLI의 직접 입력은 없고 비용 관측 비대칭도 남아 있다.
- usage count key도 secret redaction의 `token` 부분 문자열에 걸려 현재 로그의
  `input_tokens`, `output_tokens`, `cached_input_tokens`가 파괴된다. 양쪽 agent에
  공통인 자원 단위가 duration밖에 남지 않는다.
- duration 결측 여부를 세지 않고 전체 execution을 평균 분모로 쓰므로 불완전한
  row의 missing duration이 0처럼 반영될 수 있다.
- escalation은 실패/검증 결과에 조건부인 경우와 사전 risk/difficulty 분석에
  조건부인 경우가 모두 있다. 현재는 trigger 종류 없이 보통 실행과 합쳐진다.
- Git snapshot은 실행 뒤 작업공간 전체 상태이며 에이전트의 변경만을
  귀속하지 못한다.

현재 점수식 자체에도 exposure 편향이 있다. 검증되지 않은 capability affinity,
complexity fit, risk fit이 static 격차를 만들고, `required ∪ inferred` capability를
affinity의 50점 항에서 같은 무게로 쓴다. 그 뒤 선택 횟수에 비례한 confidence가
좋지만 적게 선택된 후보를 고정 neutral evidence 쪽으로 낮추고, deterministic
argmax가 다시 그 후보를 선택하지 않는 feedback loop를 만든다. 실제 일부
low-risk/moderate-difficulty context에서는 더 좋은 Claude history가 이 격차를
상쇄하지 못해 propensity 0이 지속될 수 있었다. 이는 표본 부족만의 문제가 아니라
**관측을 만들 수 없게 하는 정책 구조**다. 상세 재검토는
[Claude 독립 검토](routing-claude-review.md)에 남겼다.

따라서 현재 로그는 재현·진단·schema migration에는 쓸 수 있지만, IPS/DR
off-policy 평가나 Claude/Codex 정확도 순위에는 쓸 수 없다.

## 3. 설계 원칙

### 3.1 관측하지 않은 것은 성공도 실패도 아니다

결과는 다음 축으로 나눈다.

```text
quality       작업 목표의 객관적 달성
reliability   CLI가 정상적으로 실행·종료됐는가
constraint    lint/typecheck/형식/변경범위 조건을 지켰는가
safety        권한, 비밀, 위험 변경, 정책 위반이 없었는가
resource      시간, token, 현금 비용, cache 사용
```

`completed + skipped verification`은 reliability 관측일 뿐 quality 성공이
아니다. 결측 비용도 0이 아니다. 평가가 실행되지 않았으면 censored/unobserved로
남긴다.

### 3.2 지리적 다양성과 평가 다양성은 다르다

아시아 소재 연구기관의 논문을 추가하는 것만으로 관점 편향이 사라지지 않는다.
영어 번역 benchmark, 같은 judge 계열, 같은 API 모델군을 쓰면 평가 관점은
여전히 비슷하다. 따라서 다음을 함께 층화한다.

- 연구기관/산업·학계/peer-review 상태;
- native Korean, native English, mixed-language 작업;
- 저장소의 코드·문서 주언어;
- 객관적 evaluator와 주관적 judge;
- 공개 artifact와 로컬 재현 여부;
- 평균 성능과 희소·최악 strata 성능.

사용자 국적·문화권을 추론하거나 저장하지 않는다. 작업에 드러난 언어와
저장소 특성만 사용한다.

### 3.3 단순 모델을 반드시 이겨야 복잡도를 늘린다

Contextual Bandit Bake-off와 LLMRouterBench 모두 복잡한 라우터가 항상 단순
baseline을 크게 이기지 않음을 보여준다. 새 정책은 always-Claude,
always-Codex, best-single, 정적 capability, 층화 Beta/greedy와 비교한다.
복잡한 모델은 time-ordered 검증에서 통계적·운영적으로 이길 때만 채택한다.

### 3.4 안전과 품질을 평균 하나로 숨기지 않는다

고위험 작업에서 낮은 평균 regret를 얻었다고 안전한 정책이 되는 것은 아니다.
고위험 작업에는 탐색 확률을 0으로 두고 안전·권한 위반은 별도 hard gate와
지표로 관리한다.

## 4. 평가 계약

현재 `--verify-command`를 다음 명시적 계약으로 확장한다.

```text
EvaluatorSpec
  evaluator_id         안정적인 식별자
  version              명령·rubric 변경 버전
  role                 quality | constraint | safety | health
  subject              무엇을 평가하는가
  command              shell=False 인자 벡터
  required             필수 여부
  timeout_seconds
  language             rubric/출력 언어, 선택 사항

EvaluatorResult
  evaluator_id / version / role
  status               passed | failed | timed_out | error | skipped
  observed             실제 관측 여부
  score                 객관적으로 정의된 경우에만 [0, 1]
  exit_code / duration / stdout / stderr
  evidence_scope       이 결과가 증명하는 범위
```

집계 규칙은 다음과 같다.

- `quality`는 task-specific test, golden patch check, 명시적 acceptance
  evaluator처럼 목표를 직접 평가하는 경우에만 관측한다.
- lint/typecheck/format/diff-scope는 기본적으로 `constraint`다. 통과를 quality
  1로 승격하지 않는다.
- process health는 `reliability`를 갱신한다.
- safety evaluator는 별도로 유지하며 실패 시 정책 승격을 막는다.
- 여러 quality evaluator가 있으면 사전에 버전된 aggregation rule을 정한다.
  실행 뒤 결과에 맞춰 가중치를 바꾸지 않는다.
- legacy `verification.command`와 현재 `verification.commands`는 읽되, 역할이
  없으므로 자동 quality label로 변환하지 않는다.

LLM judge가 불가피하면 후보 이름을 가리고, 출력 순서를 무작위화하고, 역순
재평가와 사람 gold audit를 수행한다. 언어별 calibration을 따로 보고하며 하나의
global threshold를 모든 언어에 적용하지 않는다. judge 결과는 objective quality와
섞지 않고 `subjective_quality`로 분리한다.

evaluator artifact와 golden fixture는 agent가 쓸 수 있는 workspace 밖의 read-only
경로에 둔다. 실행 전후 evaluator ID/version/content hash를 확인한다. agent diff는
깨끗한 평가 checkout에 적용해 검사하며 evaluator 자체의 변경은 적용하지 않는다.
`testing` task는 agent가 작성한 test가 자기 자신을 증명하는 순환을 피하기 위해
보류된 buggy implementation, mutation score, 또는 외부 hidden test로 평가한다.
`agent-blind`는 이름 편향만 막을 뿐 evaluator 오염 방지가 아님을 구분한다.

## 5. 내구성 있는 telemetry

최종 `ExecutionRecord` 하나만 쓰는 대신 append-only event를 사용한다.

```text
selection_made
execution_started
progress_checkpoint       선택적, 비용/usage/단계 변화가 있을 때
execution_terminal
evaluation_completed      evaluator별 한 건
outcome_finalized
```

모든 event에는 다음이 필요하다.

```text
schema_version, event_id, execution_id, sequence
occurred_at, recorded_at
task_id, attempt_id, parent_attempt_id
```

동일 `event_id` 재처리는 idempotent해야 한다. `execution_started` 뒤 terminal이
없는 실행은 다음 시작 때 `incomplete/abandoned`로 reconcile한다. `KeyboardInterrupt`
같은 중단도 가능한 범위에서 terminal event를 남기되, 원래 예외 흐름은 보존한다.

선택 event에는 반드시 다음을 남긴다.

```text
policy_name / policy_version / config_hash
selection_mode            manual | exploit | explore | escalation | paired_eval
cohort                    legacy | shadow | paired | prospective | manual
context_schema / context_features
eligible_candidates / ineligible_reasons
candidate_probabilities / selected_probability
baseline_candidate / random_draw_id
```

환경 event에는 base agent, 정확한 model/tier, CLI version, permission mode,
cache/continuation 여부, workspace base revision, 비용 관측 신뢰도를 둔다. raw prompt
embedding, 추론된 사용자 문화권, 비밀 가능성이 있는 원문은 feature로 저장하지
않는다.

파생 routing state는 `.orchestrator/routing-state.json` 같은 별도 파일에 두되
event log에서 완전히 재구축할 수 있어야 한다.

## 6. Routing context와 probe

초기 context schema는 작고 해석 가능하게 유지한다.

```text
required capabilities / inferred capabilities (분리)
task category
difficulty / risk / uncertainty
instruction_language      ko | en | mixed | other | unknown
repository_code_language
repository_doc_language
task_source / cohort
objective_evaluator_available
constraint_evaluator_count
read_only / allowed_mutation_scope
time and resource constraints
environment_epoch
```

description 길이는 feature로 쓰지 않는다. 상세한 명세가 어려운 작업으로 잘못
해석된 기존 사례가 있기 때문이다.

현재 Korean/English keyword set은 번역 동등하지 않아 같은 뜻의 task가 서로 다른
capability, difficulty, uncertainty와 escalation을 만들 수 있다. paired agent
실행 전에 번역쌍을 `TaskAnalyzer`에만 통과시키는 zero-cost symmetry test를 둔다.
층화 변수 자체가 언어 keyword artifact이면 그 변수로 언어 편향을 통제했다고
주장하지 않는다.

초기 probe는 모델 호출이 아니라 읽기 전용 deterministic repository inventory다.
예: 언어, 테스트 도구, 변경 파일 수, 관련 test 존재 여부, 깨끗한 base revision.
SWE-Router처럼 partial trajectory 뒤 라우팅하는 방식은 유망하지만 다음이 확인될
때까지 보류한다.

- 약한 에이전트의 추론이 강한 에이전트에 미치는 오염 효과;
- 세션 전환 시 cache 손실과 재시작 비용;
- probe 자체의 권한·안전 정책;
- continuation과 restart 중 어느 쪽이 나은지에 대한 paired evidence.

## 7. ESTR 정책

### 7.1 Stage A — eligibility

다음 후보는 점수를 계산하기 전에 제거한다.

- required capability가 없음;
- 모델/CLI가 사용할 수 없음;
- permission mode나 안전 정책이 작업과 맞지 않음;
- 알려진 hard time/resource constraint를 위반함;
- 명시적 `--agent` 요청과 다름.

명시적 요청은 `manual`, 확률 1이다. 자동 정책 학습 평가에는 넣지 않는다.

### 7.2 Stage B — evidence ladder

현재 데이터 규모에서는 하나의 고차원 모델을 강제하지 않는다.

```text
L0  corrected static capability profile
L1  task category × instruction language의 층화 Beta/greedy 추정
L2  vendor/tier/environment를 shrinkage한 계층 추정
L3  full-covariance contextual model
L4  optional temporal/trajectory router
```

각 단계는 이전 단계와 shadow 비교해 promotion criterion을 통과해야 한다.
표본 수만으로 승격하지 않고 calibration, worst-stratum, 비용, 안전을 함께 본다.
프로필은 낮은 유효 표본수의 prior일 뿐 실제 관측으로 세지 않는다. corrected L0는
현재 capability affinity, `complexity_preference`, `risk_preference`, confidence
blend를 **함께** 재검토해야 한다. 일부만 중립화하면 나머지 static gap과
mean-reversion feedback이 zero exposure를 유지한다.

paired evidence 전의 multi-candidate `auto` fallback은 “중립”이라는 이름으로
임의 tie-break를 숨기지 않는다. Phase 1에서는 첫 선택지를 구현했다.

- 사용자가 configured baseline agent를 지정하고 policy 선택임을 표시;
- evidence 부족을 보고하고 explicit agent 선택을 요구;
- 오직 paired-evaluation cohort에서만 무작위 배정.

즉 `--routing-policy static`은 `--routing-baseline-agent`가 없으면 실패한다. 호환용
`legacy`는 별도 policy epoch로 남고, random-safe는 shadow에서만 계산한다.

현재 history는 objective quality가 아니므로 corrected L0의 quality evidence로
재사용하지 않는다.

L1의 binary objective-quality 추정 예시는 다음과 같다.

```text
posterior(a, stratum) = Beta(alpha_prior + weighted_pass,
                             beta_prior + weighted_fail)
```

exact stratum이 희소하면 `agent × task × language` → `agent × task` → `agent`
순으로 back off한다. time decay가 있는 weighted count의 구간은 엄밀한 Bayesian
보장으로 부르지 않고 calibration 대상인 uncertainty estimate로 표시한다.

L3의 선형 contextual 모델을 구현한다면 상관된 feature를 가진 상태에서 diagonal
ridge를 LinUCB 신뢰구간으로 부르지 않는다. full covariance를 사용하거나 불확실성
주장을 낮춘다.

### 7.3 Stage C — utility와 결측

후보별 예측은 분리한다.

```text
utility(a, x)
  = predicted_quality(a, x)
  - lambda_time * predicted_time(a, x)
  - lambda_resource * predicted_resource(a, x)
```

reliability와 safety는 utility에만 묻지 않고 eligibility/circuit breaker에도 쓴다.
Codex의 현금 비용이 관측되지 않는 동안 dollar budget controller는 켜지 않는다.
먼저 usage count가 secret redaction에 파괴되지 않게 고친 뒤, 양쪽에 공통인
duration/token/configured resource unit을 보고한다. 비용과 duration 결측은
unknown이다. 현재 `cost_limit_usd` penalty는 관측 가능한 agent에만 불리하고 정상
CLI/plan 입력으로 설정할 수도 없으므로, 비교 가능한 비용 관측과 명시적 입력 계약을
함께 갖추기 전에는 routing utility에 사용하지 않는다.

### 7.4 Stage D — safe equipoise exploration

탐색은 아래 조건을 모두 만족할 때만 가능하다.

- `--agent auto`;
- low-risk이고 격리된 작업공간;
- task-specific objective evaluator가 있음;
- 두 후보 모두 minimum quality/safety floor를 만족함;
- 후보의 uncertainty interval이 겹치거나 비교 evidence가 부족함;
- 최근 timeout/permission failure circuit breaker가 닫혀 있음;
- 명시적 실행·비용 budget 안임.

초기 최대 exploration mass는 `0.05`다. 50:50 강제 분배는 하지 않는다.
고위험, verifier 없는 작업, production 직접 변경에는 baseline 확률 1을 둔다.
이 gate는 per-action 안전 장치이며, 누적 성능 제약을 실제 구현하기 전에는
CLUCB라고 부르지 않는다.

탐색 gate 안의 overlap region에서는 두 후보 확률을 0이 아니게 하고 propensity를
그대로 기록한다. gate 밖의 0/1 결정을 포함한 전체 workload 정책을 이 표본으로
IPS 평가할 수 있다고 주장하지 않는다.

현재 auto traffic 규모에서는 0.05 탐색으로 유효 표본이 생기지 않는다. 이 단계는
active roadmap에서 보류한다. 월별 eligible auto traffic, overlap 비율, 예상 ESS가
사전 threshold를 넘을 때만 overlap-region estimand로 재도입한다.

### 7.5 Stage E — drift와 환경 경계

decay age는 후보별 선택 횟수가 아니라 **global decision index 또는 wall-clock**을
사용한다. 선택되지 않은 후보의 오래된 evidence도 낡아야 한다. model/CLI/permission
mode가 바뀌면 새 `environment_epoch`를 만들고 prior를 shrink한다. 임의의 half-life
50을 기본 진리로 두지 않고 replay와 time-ordered paired calibration으로 정한다.

## 8. 비교 실험과 off-policy 평가

초기 감사 시점의 legacy 12건은 선택 확률과 반사실이 없어 정책 우열에 쓰지 않는다.
이후 설계 검토를 위한 Claude 호출은 성공·실패와 관계없이 별도 manual review
attempt이며 이 숫자에 포함하지 않는다. 현재 호출 수와 경계는
[진행상황 문서](adaptive-routing-progress.md)에서 추적한다. 다음 cohort를 분리한다.

| Cohort | 목적 | 정책 학습/평가 사용 |
|---|---|---|
| legacy | schema migration, 진단 | 순위 산정 금지 |
| paired | 같은 작업의 격리된 양쪽 실행 | head-to-head 평가 |
| shadow | 실행 없이 정책 결정 비교 | coverage/결정 재현 |
| prospective | 미래의 safe randomized auto traffic | support가 있는 overlap region에서만 IPS/DR |
| manual | 사용자 지정 사용성 | 자동 정책 OPE 제외 |
| escalation | outcome 또는 task-analysis 조건부 복구 | trigger별 별도 모델 |

paired 실험과 언어 층화, 통계·중단 규칙은
[평가 프로토콜](routing-evaluation-protocol.md)을 따른다.

현재 목표 workload의 stratum 빈도는 관측되지 않았다. 따라서 paired pilot의
primary estimand는 **사전 정의한 stratum별 paired effect**이며 20/20/20 quota의
비가중 평균을 실제 workload policy value로 부르지 않는다. 전체 policy value는
agent 선택과 독립적으로 수집된 target workload 빈도와 사전 정의한 weighting이
생긴 뒤에만 계산한다.

target workload 구성 측정은 Phase 0부터 구현과 병렬인 intake track으로 시작한다.
선택된 agent나 결과를 조건으로 삼지 않고 task category, instruction language,
repository language, risk/evaluator availability 같은 사전 정의 metadata만 집계한다.
이 track은 Phase -1과 stratum별 paired 평가를 막지 않지만, target-distribution으로
가중한 policy value와 aggregate best-single/overall 주장의 선행조건이다.

필수 baseline:

1. always Claude;
2. always Codex;
3. best single agent;
4. 현재 history 없는 static capability profile;
5. 현재 legacy adaptive score;
6. 층화 Beta/greedy;
7. 승격 후보 ESTR 단계;
8. random safe policy(평가 기준점이며 production 기본값 아님).

시간순 split을 사용한다. aggregate 평균뿐 아니라 Korean/English/mixed, task type,
risk, evaluator strength별 값과 worst-stratum을 보고한다. 희소한 셀은 순위를
거부하고 불확실성을 표시한다.

## 9. 구현 경계

```text
TaskAnalyzer
  -> RoutingContextBuilder
  -> EligibilityPolicy
  -> OptionalReadOnlyProbe
  -> RoutingEstimator
  -> ExplorationPolicy
  -> SelectionEvent
  -> Kernel / Agent / ProcessRunner
  -> EvaluatorRunner
  -> OutcomeFinalizer
  -> RoutingStateProjector
```

장기 권장 책임(초기에는 `routing_context`/`policy`/`model`을 한 모듈로 시작해도 됨):

```text
routing_context.py    versioned feature와 strata
routing_policy.py     eligibility, gate, probability
routing_model.py      L0-L3 estimator와 uncertainty
evaluation.py         typed evaluator 계약/집계
events.py             append-only lifecycle event
routing_state.py      event에서 재구축되는 파생 state
replay.py             실행 없는 deterministic replay/OPE
```

기존 JSONL reader와 `VerificationResult`는 migration 기간에 유지한다. 새 schema를
쓰기 시작해도 오래된 row가 읽혀야 한다.

## 10. 단계별 구현 계획

### Phase -1 — 추가 오염 차단

구현 상태(2026-07-18): 아래 additive identity/policy/cohort와 redaction/duration
수정, legacy evidence freeze, 번역쌍 진단까지 완료했다. 이후 Phase 1에서 corrected
L0와 durable lifecycle event도 구현했다.

- secret redaction이 usage-count token key를 파괴하지 않게 수정한다.
- stable `execution_id`, `attempt_id`, `occurred_at`, `policy_version`, `config_hash`를
  additive field로 기록하고 현재 policy epoch를 `legacy-biased`로 표시한다.
- escalation의 전체 reasons를 보존하고 `trigger_classes`를
  `{outcome, task_analysis}`의 **집합**으로 파생한다. 기존 row도
  `agent_id != routing_decision.selected_agent`와 부모 `escalation.reasons`로
  가능한 범위에서 소급 라벨링한다.
- duration sample count와 결측 semantics를 바로잡는다.
- Korean/English 번역쌍을 agent 실행 없이 `TaskAnalyzer`에 통과시켜 capability,
  difficulty, risk, uncertainty의 언어 대칭성을 진단한다.
- 이 단계에서는 임의의 “중립값”으로 선택 정책을 바꾸지 않는다. corrected L0가
  정의될 때까지 `--agent auto`를 실력 evidence 수집 목적으로 쓰지 않는다.

완료 조건: 새 row의 identity/policy/resource/cohort를 복구할 수 있고, 운영 규칙상
현재 biased auto feedback을 새 실력 evidence로 축적하지 않는다.

### Phase 0 — evaluator truth

구현 상태(2026-07-18): typed evaluator, legacy constraint migration, 역할별 관측
projection, 외부 read-only artifact의 baseline/실행 전후 hash 검증과 CLI 품질
evaluator를 구현했다. 여러 quality evaluator의 정책용 단일 점수 aggregation은
실험 manifest에서 사전 정의할 때까지 수행하지 않는다.

- typed evaluator와 per-evaluator result를 추가한다.
- reliability/quality/constraint/safety/resource를 분리한다.
- verifier 없는 완료가 quality를 갱신하지 않게 한다.
- policy/context/environment/cohort 필드를 기록한다.
- evaluator와 golden fixture를 agent-writeable workspace 밖에 두고 실행 전후 hash를
  검증한다. `testing` task용 외부 평가 방식을 별도 정의한다.

완료 조건: 모든 새 실행에서 무엇을 관측했고 무엇을 관측하지 않았는지 알 수
있고, legacy 전체 test pass나 agent가 수정한 test가 task-specific quality로 자동
승격되지 않는다.

### Phase 1 — durable event, replayable boundary와 baseline

구현 상태(2026-07-18): selection/start/terminal-or-reconciled/evaluation/finalized
event, idempotent projector, PID-aware interrupted reconciliation, protected control-state
경계와 replay CLI를 구현했다. `routing-context-v1`, `corrected-static-l0-v1`,
exact/base/environment/task/language backoff와 simple shadow baseline도 추가했다.
호환 기본값은 여전히 `legacy`이며 corrected static은 명시적 baseline이 필요하다.
prospective exploration과 정책 승격은 활성화하지 않았다.

- lifecycle event와 interrupted execution reconciliation을 추가한다.
- context, eligibility, scoring, random draw를 pure component로 분리한다.
- seed/config/history가 같으면 결정이 byte-for-byte 재현되게 한다.
- exploration은 끈 상태로 모든 후보 확률과 shadow 결정을 기록한다.
- event schema가 확정된 뒤 incremental projector와 migration path를 만든다.
- corrected L0를 정의한 뒤 capability affinity, complexity/risk prior, confidence
  blend를 한 policy epoch에서 함께 수정한다. required capability는 eligibility,
  inferred capability는 감쇠된 context로 다루고 vendor별 차이는 paired evidence
  전에는 실력으로 주장하지 않는다.
- exact tier와 base/vendor/environment evidence의 명시적 backoff를 구현한다.
- corrected static, best-single, 층화 Beta/greedy baseline을 구현한다.

완료 조건: legacy replay는 기록 재현·schema 검증에만 성공해야 한다. 반사실 성능을
증명했다고 표현하지 않으며, 강제 중단 테스트에서도 started execution이 사라지지
않는다.

### Parallel measurement — target workload composition

- Phase 0부터 agent 선택과 독립적인 task intake metadata를 누적한다.
- privacy 경계를 지키며 사전 정의한 strata 빈도와 unknown 비율을 보고한다.
- 표본 기간, drift 처리, weighting rule을 확증 round 전에 고정한다.
- 충분한 대표성이 없으면 workload-weighted policy value와 aggregate best-single
  순위를 보류하고 stratum별 결과만 보고한다.

완료 조건: target workload weighting의 모집단, 관측 기간, 결측/unknown 처리와
버전이 재현 가능하며 routing 결과나 agent 선택이 빈도 추정을 오염시키지 않는다.

### Phase 2a — paired smoke

구현 상태(2026-07-18): `paired-smoke-manifest-v1`과 첫 4-task/evaluator set을 사전
등록했다. shared Git refs가 없는 clean equal-base independent checkout 8개 준비,
balanced seeded order와 stable pair/execution/attempt ID, pinned evaluator integrity,
lifecycle-derived complete/one-sided/incomplete projection과 synthetic 2×2 aggregation,
explicit execution gate와 CLI version/resource/control-state guard가 있는 runner까지
구현했다. 실제 4-task/8-execution smoke는 2026-07-18 완료됐고 8개 reliability와
objective evaluation이 모두 관측됐다. 2×2는 pass/pass 3, Claude fail/Codex pass 1이지만
불일치 row의 evaluator가 task에 없는 JSON key를 요구한 validity 문제가 있으므로 agent
비교로 해석하지 않는다. tooling report는 정책 순위와 promotion을 계속 거부한다.
smoke task의 네 변경은 현재 코드에 독립 통합했고, 분석기는 overall/stratum evaluator
coverage와 reliability·wall-time·resource missingness·수정 파일 관측을 보고한다. 새 paired
run은 이 자원/수정 파일 정보를 protected finalized event에 기록하지만, 첫 smoke의 기존
log에 없던 값은 사후 추정하지 않는다.
차기 `paired-smoke-manifest-v2`는 각 evaluator assertion의 requirement를 실제
description/objective/constraints 문구에 매핑하고 assertion inventory가 완전하다는
reviewer attestation을 요구한다. validator는 문구 포함과 ID/경로 형식을 검증하지만
evaluator code에서 assertion을 추론하지 않는다. task별 exact modified-file allowlist와
모든 attempt의 수정 파일 관측이 있을 때만 전체 unexpected-file count를 확정한다.

- 독립 task-specific evaluator가 있는 4개 low-risk task를 같은 base revision의
  격리 workspace에서 양쪽 agent로 실행한다.
- evaluator/event/pairing pipeline과 one-sided failure 처리를 검증한다.

완료 조건: 8개 실행을 수동 해석과 같은 방식으로 집계하고, legacy quality가 0건인
상태에서도 새 objective evidence가 생성된다.

### Phase 2b — paired pilot와 확증 benchmark

- 60-task pilot은 native Korean/English/mixed pipeline, discordance, variance,
  failure mode를 추정하는 용도로만 사용한다.
- 실행 순서와 subjective judge 출력 순서를 무작위화한다.
- objective evaluator를 agent-blind하게 동일 적용한다.
- pilot discordant-pair rate의 보수적 신뢰한계나 사전 정의한 internal-pilot
  re-estimation으로 확증 표본수와 보고 가능한 strata를 계산한다.
- 확증 round는 pilot에 쓰지 않은 **신규 task**를 사용한다.

완료 조건: pilot을 우열 증명으로 과장하지 않고, 확증 round에서 주요 strata의
paired effect와 uncertainty를 계산할 수 있다.

### Future gate — safe prospective overlap

- 현재 active roadmap에는 넣지 않는다.
- 평가할 target policy class를 먼저 고정한다. 월별 auto traffic, eligible overlap
  비율, 그 policy class의 예상 ESS, resource budget이 사전 threshold를 넘을 때만
  별도 설계 검토를 연다.
- 재도입하더라도 overlap region 밖의 정책을 IPS/DR로 평가하지 않는다.
- overlap/positivity는 IPS와 DR의 식별 조건이다. prospective randomized cohort의
  propensity는 추정하는 nuisance model이 아니라 선택 전에 정확히 기록하는 설계값이다.
  이론적으로 DR는 propensity 또는 outcome model 중 하나가 정확하면 일관성을 얻지만,
  이 프로젝트에서는 분산 감소와 추가 robustness를 실제로 검증하기 위해 충분한
  objective-quality label과 time-ordered 검증을 통과한 outcome model이 있을 때만
  DR 결과를 보고한다. 이는 DR의 이론적 필수조건이 아니라 보수적인 운영 허용 조건이다.

완료 조건: 시작 전 power/support 계산으로 최소 ESS에 도달 가능함을 보이고,
exploration eligibility 위반이 0이다.

### Phase 3 — estimator promotion

- L0/L1/L2/L3를 shadow/time-ordered 평가한다.
- 전체·언어별·worst-stratum 비열등성과 비용/지연을 비교한다.
- 단순 모델을 이기지 못한 복잡한 모델은 채택하지 않는다.

완료 조건: 아래 promotion criterion을 만족한 가장 단순한 단계만 기본값이 된다.

### Phase 4 — temporal/trajectory와 budget controller

- read-only probe의 정보가치를 ablation한다.
- partial trajectory continue/restart와 cache 비용을 paired 비교한다.
- 양쪽 비용이 비교 가능해진 뒤에만 rolling budget controller를 켠다.

## 11. Promotion criterion

정책 승격에는 모두 필요하다.

- objective verified quality가 baseline 대비 사전 정의한 비열등성 한계를
  만족하고, 목표가 개선이면 CI가 그 개선 기준도 지지함;
- Korean/English/mixed 및 주요 task strata에서 치명적 회귀가 없음;
- safety/permission 위반 증가가 없음;
- high-risk 또는 unverified task의 exploration이 0건;
- paired task의 fixture/order/evaluator integrity가 완전함;
- prospective/OPE를 사용하는 미래 정책이면 propensity 누락이 0건이고 support가
  있는 estimand의 effective sample size가 최소 기준 이상;
- 시작된 실행의 terminal/reconciled 기록률이 100%;
- cost/latency 결측을 0으로 계산한 행이 0건;
- 같은 state/config/seed의 replay 결과가 동일함.

정확한 비열등성 margin은 pilot 전에 evaluator별로 고정한다. 확증 표본수와
보고할 strata는 pilot 직후, **신규 확증 round 시작 전**에 사전 정의한 방식으로
고정한다. 결과를 본 뒤 다른 항목을 바꾸면 그 분석은 탐색적으로 다시 표시한다.

## 12. 불변식과 rollback

- 명시적 agent 요청은 덮어쓰지 않는다.
- 부적격 후보 확률은 0이고 적격 확률 합은 1이다.
- 미관측 quality는 reward update를 만들지 않는다.
- manual/escalation/paired 표본을 ordinary auto OPE에 섞지 않는다.
- unknown cost는 0이 아니다.
- static prior는 measured evidence로 표시되지 않는다.
- 오래된 event는 수정하지 않고 파생 state만 재구축한다.
- 환경 변경 전 evidence를 현재 evidence와 무조건 합치지 않는다.
- subjective judge 하나가 최종 quality ground truth가 되지 않는다.

현재 구현된 운영 flag는 다음과 같다.

```text
--routing-policy static|legacy
--routing-baseline-agent AGENT_ID
--routing-shadow
--routing-seed
--environment-epoch
--control-state-dir
```

`estr`와 exploration flag는 future gate가 실제로 열릴 때 추가한다.

파생 state만 읽지 못하면 event source에서 먼저 재구축한 뒤 사전에 지정한 configured
baseline을 사용한다. source event 자체가 손상돼 selection을 기록할 수 없으면
unlogged 실행으로 fallback하지 않고 fail closed한다. 현재의 검증되지 않은 profile이나
등록 순서상 첫 agent로 조용히 fallback하지 않는다.

## 13. 당장 구현할 범위

**Phase -1/0/1의 최소 관측 기반은 완료됐다. 다음은 tooling dry run 뒤
4-task paired smoke를 실행한다.** 현재 표본으로 VCR-UCB, neural router, prompt
embedding, correlated surrogate, full contextual model을 바로 켜면 모델은
복잡해져도 정확도를 검증할 수 없다. 기존 전체 test verification은 objective
quality로 재사용하지 않으므로 새 task-specific evidence가 반드시 필요하다.

그 다음 paired pilot과 pilot 기반 확증 benchmark로 비교 가능성을 만든다. 현재
트래픽에서는 0.05 prospective overlap도 실효 표본을 만들지 못하므로 보류한다.
최종 기본 알고리즘은 미리 이름으로 결정하지 않고, ESTR evidence ladder에서 승격
기준을 통과한 가장 단순한 모델로 정한다.
