# Claude 독립 검토 기록

> 실행일: 2026-07-17
> 대상: adaptive routing 연구·설계·평가·진행상황 문서와 현재 source/telemetry
> 방법: 이 저장소의 CLI 오케스트레이터에서 `--agent claude-code`를 명시한
> 읽기 전용 비판 검토

## 1. 실행 기록

첫 실행은 격리 환경에서 Claude API 연결이 차단되어 실패했다.

```text
Claude session: 6f768368-c7b6-450e-9059-106524b11475
status: failed
terminal reason: api_error / ENOTIMP
cost: 0
```

외부 연결을 허용해 동일 요청을 다시 실행했다.

```text
Claude session: 776d7976-ff8b-47a2-9fb8-bbfcc198afe2
model: claude-opus-4-8
status: completed
turns: 26
cost: $2.398519
```

현재 실행 schema에는 stable `execution_id`가 없으므로 session ID를 대체 식별자로
기록한다. 두 시도는 `.orchestrator/executions.jsonl`에 최종 record로 추가됐다.
Claude는 파일을 수정하지 않았고 network research나 test 실행도 하지 않았다.

## 2. 수용한 지적

### 현재 점수식의 구조적 노출 편향

현재 점수에서 affinity 50, complexity fit 15, risk fit 10, history evidence 25가
합쳐진다. 실제 auto task 중 한 사례에서는 Claude의 관측 history가 더 좋아도
검증되지 않은 complexity/risk prior의 격차를 이기지 못했다. history의 영향에
상한이 있어 해당 context에서 Claude 선택 확률이 계속 0이 될 수 있다.

수정 방향:

- 현재 auto 정책을 unbiased baseline으로 간주하지 않는다.
- 추가 auto evidence를 모으기 전에 검증되지 않은 complexity/risk prior를
  중립화하거나 static policy를 고정한다.
- required/inferred capability를 분리하고 score component별 reachable range를
  테스트한다.

### token telemetry가 secret redaction에 의해 파괴됨

`logging.py`의 sensitive-key regex가 `token` 부분 문자열을 찾기 때문에
`input_tokens`, `output_tokens`, `cached_input_tokens` 값도 `[REDACTED]`가 된다.
Codex 현금 비용이 없는 상태에서 공통 자원 단위로 제안한 token을 실제로 쓸 수
없다.

수정 방향:

- credential token과 usage count key를 구분하는 redaction contract를 먼저 고친다.
- 실제 token literal redaction은 유지한다.
- usage count가 살아 있고 credential-like key는 가려지는 regression test를 둔다.

### escalation cohort가 두 생성 과정을 섞음

현재 escalation은 첫 실행 실패/검증 실패뿐 아니라 사전 분석의 high risk,
uncertainty, difficulty만으로도 발생한다. 전자는 outcome-conditioned이고 후자는
task-analysis-conditioned다. 둘 다 ordinary execution과 섞여 history에 들어간다.

수정 방향:

- `escalation_trigger=outcome|task_analysis`와 이유를 기록한다.
- 두 번째 실행은 첫 실행의 workspace를 볼 수 있어 독립 paired sample이라고
  부르지 않는다.
- 자동 정책 history와 조건부 recovery 분석을 분리한다.

### pilot 규모와 정밀도 목표의 불일치

60-task pilot을 3개 언어와 5개 category로 교차하면 cell당 평균 4개뿐이다. 이는
stratum 순위나 좁은 CI를 위한 표본이 아니다.

수정 방향:

- 60 task는 pipeline, discordance, variance, failure mode를 추정하는 pilot으로만
  사용한다.
- 확증 표본수와 reporting strata는 pilot의 discordant-pair rate로 다시 계산한다.
- 희소 cell을 “차이 없음”으로 해석하지 않는다.

### 현재 트래픽에서 prospective OPE가 비현실적

원래 auto 4건 수준에서 0.05 exploration은 evidence를 거의 만들지 못한다. 또한
equipoise 밖의 0/1 propensity는 always-Claude/always-Codex 같은 정책을 전체
분포에서 IPS로 평가할 support를 제공하지 않는다.

수정 방향:

- prospective overlap/OPE를 현재 active phase에서 제외한다.
- 대표성 있는 paired benchmark에 우선 투자한다.
- 향후 auto traffic·eligible overlap·예상 ESS가 사전 threshold를 넘을 때만
  overlap-region estimand로 재도입한다.

### typed evaluator만 추가하면 quality 표본이 0이 됨

기존 verification 대부분은 전체 `unittest` suite이며 역할 metadata가 없다. 이를
보수적으로 constraint로 migration하면 legacy objective-quality label은 0건이다.
따라서 Phase 0/1 뒤 자동으로 학습 가능해지는 것이 아니다.

수정 방향:

- evaluator foundation 뒤 작은 paired smoke task부터 task-specific acceptance
  evidence를 만든다.
- 현재 static profile을 그대로 L0 prior로 재사용하지 않는다.

### 추가로 수용

- duration 결측용 sample count가 없고 평균 분모가 전체 execution인 문제;
- completion probability와 conditional verification rate의 의미 없는 선형 합;
- 비용 penalty가 관측 가능한 Claude에만 걸릴 수 있고 CLI에서는 cost limit 입력
  경로가 없는 비대칭;
- event volume을 늘리기 전에 incremental projector/read path가 필요함;
- exact tier ID가 바뀌면 history가 끊기므로 base/tier/environment evidence를
  의도적으로 분리해야 함;
- Git snapshot은 pre-existing dirty state를 agent change로 귀속할 수 없음.

## 3. 한정 수용 또는 표현 수정

### “Claude는 어떤 history로도 이길 수 없다”

검토 보고의 이 표현은 너무 넓다. capability 조합, difficulty/risk, 상대 agent의
history가 달라지면 Claude가 이길 수 있다. 정확한 결론은 다음이다.

> 현재 관측된 일부 low-risk/moderate-difficulty context에서는 Claude의 더 좋은
> history가 검증되지 않은 static component 격차를 상쇄하지 못하며, deterministic
> 선택 때문에 그 context의 Claude propensity가 0으로 고정될 수 있다.

핵심 결함은 수용하되 전역 불가능성 주장은 수용하지 않았다.

### “표본수와 CI/유의성이 수학적으로 상호 배타”

프로토콜은 p-value 유의성을 명시적 promotion 조건으로 두지 않았으므로 exact
McNemar 유의성과 CI 폭을 동시에 반드시 만족해야 한다는 해석은 과하다. 하지만
n=20/언어와 cell당 4로 정밀한 strata 결론을 내릴 수 없다는 지적은 타당하다.
고정 CI 폭 목표를 pilot에서 제거했다.

### “prospective/OPE 삭제”

방법론 자체를 영구 삭제하지 않는다. 현재 active roadmap에서는 보류하고, 충분한
traffic/support 예상치를 만족할 때 **overlap region에 한해** 다시 검토한다.

### 최신 multilingual preprint 의존

하루 된 preprint 하나를 확정 근거로 사용하지 않는다. 언어별 calibration 원칙은
2024~2025 judge bias와 native-language benchmark 연구가 함께 지지하는 보수적
평가 설계다. 2026-07 수치는 잠정적 corroboration으로만 표시한다.

## 4. 검토로 바뀐 구현 순서

```text
Phase -1  추가 오염 차단
  - current auto prior 중립화/freeze
  - usage-token redaction 수정
  - escalation trigger/cohort 표식
  - duration sample semantics 수정
  - exact tier/base/environment history 경계 명시

Phase 0   evaluator 의미 + incremental projection
Phase 1   durable event + replay + simple baseline
Phase 2a  4-task paired smoke
Phase 2b  60-task variance/discordance pilot
Phase 3   pilot 기반 확증 paired benchmark
Phase 4   가장 단순한 estimator promotion
Future    traffic/support threshold를 충족할 때만 prospective/OPE
```

## 5. 독립 검토의 한계

- Claude는 외부 논문 링크를 확인하지 않았다.
- Claude는 current test suite를 실행하지 않았다.
- Claude의 보고는 같은 vendor 계열 model이 만든 subjective review이며 ground
  truth가 아니다.
- 핵심 항목은 이 문서 작성자가 현재 source와 telemetry로 다시 확인했다.
- 연구 인용은 별도의 primary-source 검토에 의존한다.

## 6. 수정 후 2차 상세 검토

사용자 요청에 따라 첫 검토 결과를 반영한 문서를 다시 Claude에게 보냈다. 이번에는
단순 비판 요청이 아니라 목표 estimand, 네 편향의 정의, 로컬에서 확인한 사실,
첫 검토의 수용·한정 수용 이유, 변경한 phase와 아직 모르는 값을 상세히 제공했다.

```text
Claude session: 1649564f-19d3-4bba-88f4-16e915823304
model: claude-opus-4-8
status: completed
duration: 851.4s
turns: 36
cost: $3.716420
```

Claude는 파일을 수정하지 않았다. source는 읽었지만 test와 전체 telemetry 집계,
외부 web 확인 권한은 얻지 못했다. 외부 인용은 이 검토와 별개로 primary source를
확인했다.

### 6.1 새로 수용한 blocking findings

#### Static prior 원인을 너무 좁게 지목함

첫 반영은 complexity/risk prior만 중립화 대상으로 적었다. 실제 static gap에는
capability affinity가 더 크게 작용할 수 있고, affinity는 required와 inferred
capability를 같은 무게로 사용한다. 또한 history evidence의 명목 가중치는 25지만
`0.4 + 0.3` 구조로 실제 상한은 17.5다.

더 중요한 동역학은 선택 횟수 기반 confidence blend다. 좋은 저표본 후보를 고정
neutral 값으로 낮춘 뒤 deterministic argmax가 다시 노출을 막을 수 있다. 이는
Bayesian shrinkage 자체가 잘못이라는 뜻이 아니라, uncertainty-driven exploration
없는 현재 argmax에서 자기강화 feedback을 만든다는 뜻이다.

결정:

- affinity, complexity/risk, confidence blend를 corrected L0에서 함께 재설계한다.
- Phase -1에서 임의의 중립값으로 정책을 부분 수정하지 않는다.
- corrected L0 전에는 `auto`를 실력 evidence 수집에 사용하지 않는다.

#### Phase -1은 policy 변경보다 additive identity가 먼저

정확한 중립 정책을 정의하지 않은 상태에서 policy를 바꾸면 다른 편향을 가진 새
epoch가 생긴다. 현재 결정 component는 이미 record에 남으므로 다음 additive 작업이
더 작고 되돌리기 쉽다.

- execution/attempt ID와 timestamp;
- policy version/config hash와 `legacy-biased` epoch;
- usage-count redaction과 duration sample semantics;
- escalation reason-set 기반 retrospective cohort label;
- agent 실행 없는 Korean/English analyzer symmetry test.

#### Evaluator가 agent-writeable workspace에 있음

현재 verifier는 agent가 방금 수정한 workspace에서 실행된다. hidden test나 golden
fixture가 그 안에 있으면 agent가 평가 기준을 바꿀 수 있고, testing task는 agent가
작성한 test가 자기 자신을 증명하는 순환이 생긴다.

결정:

- evaluator artifact를 agent-write 영역 밖의 read-only 경로에 둔다.
- clean evaluation checkout에 agent diff만 적용한다.
- 실행 전후 evaluator hash를 확인한다.
- testing task는 held-out buggy implementation, mutation, hidden test로 평가한다.

#### Pilot sizing 문구와 reuse

margin과 확증 표본수의 고정 시점이 문서에서 충돌했다. pilot discordance의
점추정치만으로 sizing하면 under-power 위험이 있고, pilot task를 확증에 재사용하면
확증성을 훼손한다.

결정:

- margin은 pilot 전에 고정한다.
- 보수적 discordance 한계 또는 사전 정의한 internal-pilot rule로 sizing한다.
- 표본수와 reporting strata는 신규 확증 round 시작 전에 고정한다.
- 확증 round는 신규 task를 사용한다.

#### Projector 순서

per-evaluator 1:N 관계와 idempotency에는 execution/event identity가 먼저 필요하다.
terminal-only row를 전제로 projector를 먼저 만들면 event 도입 때 다시 써야 한다.

결정: additive identity → typed evaluator → durable event schema → projector 순서로
바꿨다.

### 6.2 새로 수용한 nonblocking findings

- Korean/English keyword가 번역 동등하지 않아 analyzer feature와 미래 auto route가
  언어 자체에 따라 달라질 수 있다.
- raw token은 tokenizer와 언어에 의존하므로 agent 간 절대 공통 비용 단위로 바로
  사용할 수 없다.
- balanced paired quota는 workload composition을 대비에서 제거하지만 실제 target
  workload 빈도가 없으면 aggregate policy value를 추정하지 못한다. 우선 stratum별
  paired effect를 primary로 둔다.
- future ESS는 traffic뿐 아니라 평가할 target policy의 weight에 의존한다. target
  policy class를 먼저 고정해야 한다.
- DR는 propensity 외에 충분한 quality label과 검증된 outcome model이 추가로
  필요하다.
- base ID가 log에 있어도 현재 router는 exact tier metrics만 읽으므로 model 변경
  간 history continuity가 실제 routing에는 구현되지 않았다.
- escalation trigger는 outcome/task-analysis 중 하나를 고르는 enum이 아니라 둘 다
  포함할 수 있는 reason/class set이다.
- future exploration flag와 progress checkpoint, 초기 7-module 분리는 구현을
  서두르지 않는다.

### 6.3 유지한 첫 판단

- Claude가 모든 history/context에서 절대 이길 수 없다는 전역 주장은 계속 기각한다.
- p-value가 필수 조건이 아니므로 CI 폭과 유의성이 반드시 상호 배타라는 주장도
  기각한다.
- prospective OPE는 영구 삭제하지 않고 target-policy/support/ESS gate 뒤에 둔다.
- 2026-07 multilingual preprint는 단독 확정 근거가 아닌 보조 근거로만 쓴다.

### 6.4 2차 검토의 결과

첫 설계의 큰 방향인 evidence-first, paired-first, simple-baseline promotion은
유지됐다. 바뀐 것은 가장 이른 구현 순서와 평가 경계다. 현재 선택 정책을 어설프게
고치기보다 먼저 새 evidence의 identity와 의미를 보존하고, evaluator를 보호한 뒤,
corrected L0를 한 policy epoch에서 일관되게 정의한다.
