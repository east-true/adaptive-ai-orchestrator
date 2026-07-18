# Phase 2b Paired Pilot 사전등록 계약

> 계약 버전: `phase2b-pilot-prereg-v1`
> manifest schema: `paired-pilot-manifest-v1`
> 상태: construction/validity 계약 고정, 60-task manifest 미작성, 실행 미승인
> 목적: Phase 2a smoke의 통제 원칙을 60-task variance/discordance pilot로 일반화한다.

## 1. 현재 이 문서가 승인하는 것

이 문서와 [`paired-pilot-manifest-v1.schema.json`](../experiments/schemas/paired-pilot-manifest-v1.schema.json)은
task와 evaluator를 만드는 절차 및 최종 manifest의 형식을 고정한다. 실제 task 60개,
보호 evaluator artifact, 완성된 manifest, agent 실행은 아직 승인하거나 사전등록하지
않는다.

세 artifact를 구분한다.

1. **construction contract**: 지금 고정하는 이 문서와 JSON Schema;
2. **experiment manifest**: task/evaluator validity review가 끝난 뒤 생성하고 결과를
   보기 전에 별도 commit으로 동결할 60-task instance;
3. **run authorization**: manifest validation과 agent-free dry run 뒤 사용자가 별도로
   승인하는 120-execution 실행 기록.

현재 Phase 2a parser/runner는 `paired-pilot-manifest-v1`을 지원하지 않는다. smoke
명령에 이 schema를 넣으면 거부되는 것이 의도한 fail-closed 동작이다. Phase 2b용
validator, planner, runner는 construction contract와 독립 검토가 끝난 뒤 별도 구현한다.

## 2. Pilot 목적과 금지된 해석

계획 단위는 60 task와 Claude Code/Codex의 120 independent execution이다. 이 pilot의
목적은 다음을 추정하는 것이다.

- objective evaluator와 lifecycle pipeline의 validity/coverage;
- complete/discordant/one-sided/incomplete pair 비율;
- language와 task category별 분산 및 희소성;
- infrastructure, evaluator, quota, resource missingness;
- 신규 confirmatory round의 표본수와 보고 가능한 strata.

60-task 결과로 agent 승자, 기본 policy promotion, target-workload aggregate, 언어×범주
cell 순위를 주장하지 않는다. quota 20/20/20은 실험분포이며 실제 workload weight가
아니다. pilot task는 confirmatory round에서 재사용하지 않는다.

## 3. 역할 분리와 blind

최종 manifest는 개인 이름 대신 안정적인 role ID를 기록한다. task author,
evaluator author, validity reviewer의 세 construction 집합은 서로 겹치지 않는다는
attestation을 요구한다. frozen artifact를 다루는 run operator와 analyst는 이 세 역할과
겹치지 않는 편이 좋지만, manifest를 바꿀 수 없고 blind가 유지되면 서로 겹칠 수 있다.

| 역할 | 결과를 보기 전 책임 | 보면 안 되는 것 |
|---|---|---|
| task author | source/provenance, task 문구, acceptance criteria, 예상 수정 범위 | agent별 결과 |
| evaluator author | task 문구만으로 보호 evaluator와 assertion inventory 작성 | agent identity/output |
| validity reviewer | task–assertion 대응, evaluator 완전성, negative control, leakage 검토 | agent별 결과 |
| run operator | frozen manifest 그대로 환경 검증·실행 | evaluator golden artifact 내용 |
| analyst | frozen analysis plan으로 event/result 집계 | 동결 전 agent 결과 |

한 사람이 불가피하게 여러 역할을 맡아야 하면 작업을 진행하지 않고 protocol amendment와
conflict mitigation을 먼저 기록한다. task와 evaluator를 같은 대화에서 동시에 생성한
출력은 독립 construction으로 인정하지 않는다. evaluator author에게 agent 이름, 예상
우열, 과거 smoke 결과를 제공하지 않는다.

## 4. Task set construction

### 4.1 고정 quota와 strata

- native Korean 20;
- native English 20;
- 실제 혼합 언어 지시 20;
- category는 `implementation`, `debugging`, `testing`, `refactoring`,
  `repository-analysis-planning`을 각각 12개 포함;
- language와 category는 marginal reporting strata다. 3×5 cell은 확증 단위로
  사용하지 않는다;
- low-risk, isolated-checkout-only task만 허용한다.

Korean과 English는 상대 언어 task의 단순 번역으로 채우지 않는다. mixed task는
identifier만 영어인 것을 뜻하지 않고 지시·문서·acceptance criteria에서 두 언어가
실제로 필요한 작업이어야 한다. 번역쌍은 별도 language-sensitivity 연구로 분리하고
pilot primary set에 넣지 않는다.

### 4.2 Source와 provenance

각 task는 다음을 결과 확인 전에 고정한다.

- source kind/reference/revision과 선택 이유;
- 원문 언어, native 여부, adaptation 이력, license/사용 조건;
- repository ID, exact commit/tree, fixture path/hash;
- description/objective/constraints와 명시적 acceptance criteria;
- required capability, 예상 resource bucket, exact modified-file allowlist;
- task author role ID와 construction timestamp;
- confirmatory reuse 금지 표시.

실제 이슈나 patch에서 파생한 task는 원래 정답 patch가 agent workspace나 prompt에
노출되지 않게 한다. task source 선택은 특정 agent의 알려진 강·약점을 맞추는 방식이
아니라 사전에 고정한 quota와 eligibility 규칙으로 수행한다. 후보 탈락 row와 사유도
ledger에 남겨 selection bias를 검토할 수 있게 한다.

### 4.3 Repository와 환경

repository별 exact commit/tree와 fixture hash를 기록하고 두 agent checkout이 동일한
object에서 만들어졌음을 검증한다. workspace에는 다른 branch/ref, 상대 agent 결과,
보호 evaluator/golden artifact, secret, production credential을 노출하지 않는다.
network, push, production mutation은 허용하지 않는다.

## 5. Evaluator construction

Pilot primary set은 다음 objective mode만 허용한다.

1. deterministic acceptance test;
2. golden output/patch invariant;
3. property/integration evaluator.

human rubric이나 LLM judge가 필요한 task는 pilot primary set에서 제외하거나, 결과를
보기 전 protocol amendment로 별도 exploratory endpoint를 정의한다. 하나의 global judge
또는 언어별 threshold 하나를 objective quality로 대체하지 않는다.

각 evaluator는 다음 계약을 만족한다.

- agent 이름과 output에 blind한 상태에서 task contract만 보고 작성;
- agent-writeable checkout 밖의 read-only artifact로 materialize;
- command, 보호 evaluator root 기준 상대 artifact path/mode/hash, version, timeout 고정;
- 모든 assertion에 stable ID, requirement, task field와 literal contract text 매핑;
- `assertion_inventory_complete=true` reviewer attestation;
- base fixture에서 의도한 missing behavior 때문에 실패하는 negative control;
- 알려진 유효 solution 또는 property fixture를 판별하는 positive/sanity control;
- 실행 전후 artifact hash 동일성 검증;
- lint/typecheck/process completion을 objective quality와 분리.

`testing` task는 agent가 작성한 test로 자기 자신을 증명하지 않게 held-out buggy
implementation, mutation target 또는 외부 hidden test를 사용한다. 이 경계를 만들 수
없으면 해당 task를 포함하지 않는다.

## 6. Validity review gate

validity reviewer는 agent 결과 없이 task별로 다음을 확인하고 role ID와 timestamp를
manifest에 attest한다.

- evaluator의 모든 assertion이 task 문구에 실제로 요구됐는가;
- task의 모든 acceptance criterion이 evaluator assertion으로 검사되는가;
- evaluator가 문서에 없는 top-level key, 경로, formatting을 요구하지 않는가;
- golden artifact나 답이 workspace/prompt/visible Git ref로 새지 않는가;
- negative control 실패 이유가 의도한 missing behavior인가;
- positive/sanity control이 evaluator false-negative를 탐지하는가;
- allowlist가 task에 필요한 최소 범위이며 glob이나 절대 경로가 없는가;
- 특정 agent CLI 출력 형식·언어 스타일을 품질로 보상하지 않는가;
- task source와 evaluator source가 confirmatory holdout을 소모하지 않는가.

불일치가 하나라도 있으면 task/evaluator version을 올리고 모든 control과 review를 다시
수행한다. review 뒤 artifact를 수정하면 기존 attestation은 무효다.

## 7. Manifest와 분석 계약

machine-readable schema는 다음을 강제하거나 명시적으로 attest하게 한다.

- 정확히 두 agent와 60 task/120 maximum execution;
- Korean/English/mixed 각각 정확히 20 task;
- 다섯 category의 포함과 task별 provenance;
- exact environment/repository/agent/evaluator identity;
- role separation, result blindness, evaluator validity review;
- deterministic balanced order와 stable pair/execution/attempt identity rule;
- primary paired objective-quality risk difference;
- reliability, safety/constraint, resource, scope, evaluator coverage의 분리;
- quality/cost/resource missing을 0이나 pass로 대체하지 않는 규칙;
- stopping/pause/exclusion/resume과 untouched suffix 보존;
- pilot task의 confirmatory reuse 금지와 별도 target-workload weight gate;
- manifest 밖의 별도 run authorization.

JSON Schema만으로 task ID/repository ID의 key-level uniqueness, task의
`task_set_version` 일치, 참조 무결성, 역할 ID 집합의 disjointness, artifact hash 계산,
task별 최대 실행 수와 전체 budget 관계는 완전히 증명할 수 없다. Phase 2b semantic
validator가 이 항목을 추가로 검사해야 한다.

## 8. 실행 전 agent-free gate

완성된 manifest를 version control에 동결한 뒤에도 실행은 자동 승인되지 않는다.
별도 validator/dry run이 다음을 모두 통과해야 한다.

1. JSON Schema와 semantic invariant validation;
2. source repository clean 상태와 exact commit/tree/fixture hash;
3. protected evaluator path/mode/version/hash와 negative-control evidence;
4. 120개 unique workspace/attempt identity와 balanced order projection;
5. agent 호출 없는 120-checkout materialization 및 격리 검증;
6. synthetic complete/discordant/one-sided/incomplete projection golden test;
7. missing quality/cost/resource와 unexpected-file aggregation golden test;
8. partial finalized prefix와 untouched suffix resume rehearsal;
9. installed model/CLI/permission/environment epoch 및 resource budget check;
10. manifest commit 이후 task/evaluator/analysis artifact가 바뀌지 않았다는 audit.

그 뒤 사용자에게 exact manifest commit, 예상 최대 시간·실행 수, CLI quota 상태,
protected workspace/control path, 중단 규칙을 제시하고 120 execution을 별도로 승인받는다.

## 9. 실행·중단·재개 원칙

- secret/production/network/push, base/evaluator hash mismatch, 격리 실패는 즉시 중단;
- permission/sandbox/quota/infrastructure one-sided failure는 row를 finalized하고 pause;
- agent failure/timeout/interruption은 편의상 제외하지 않음;
- fixture 자체가 양쪽 실행 전 깨진 경우만 사전 exclusion rule로 제외;
- finalized prefix를 수정·삭제하지 않고 materialize되지 않은 untouched suffix만 재개;
- quality 미관측은 `missing`, cost 미노출은 `unknown`, terminal 없음은 `incomplete`;
- missing을 quality 0/pass나 cost 0으로 impute하지 않음;
- 모든 exclusion, pause, resume, protocol deviation을 공개.

## 10. 완료 정의와 다음 작업

construction 단계 완료 조건은 다음과 같다.

- [x] construction/validity workflow와 machine-readable schema 동결;
- [x] source candidate ledger schema와 inclusion/exclusion rule 작성;
- [ ] source pool screening 완료 및 candidate ledger 동결;
- [ ] 역할을 분리해 native task 60개 작성;
- [ ] 보호 evaluator 60개, assertion inventory, negative/positive control 작성;
- [ ] 독립 validity review 완료;
- [ ] 완성된 manifest instance와 semantic validator 작성;
- [ ] agent-free validation/dry run 결과 검토;
- [ ] 별도 120-execution 승인.

따라서 이 문서 다음의 실제 작업은 runner 실행이 아니라
[source candidate ledger](paired-pilot-candidate-ledger.md)의 pool을 완성·동결하고
**역할 분리된 task construction package**를 만드는 것이다.
