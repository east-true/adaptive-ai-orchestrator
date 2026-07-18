# Phase 2b source candidate ledger

> Schema: `paired-pilot-candidate-ledger-v1`
> Protocol: `phase2b-pilot-prereg-v1`
> 상태: source screening 진행 중, task/evaluator/agent 실행 미승인

## 1. 이 artifact가 하는 일

[`phase2b-candidate-ledger-v1.json`](../experiments/phase2b-candidate-ledger-v1.json)은
60-task manifest보다 앞선 result-blind 후보 모집단이다. 후보를 먼저 전부 보존하고,
포함·제외 판정과 이유를 남겨 특정 agent의 알려진 강·약점이나 실행 결과에 맞춘 선택을
막는다. `screening` row는 task로 선정된 row가 아니며 quota에도 세지 않는다.

이 ledger는 task-source construction 역할의 산출물이다. evaluator assertion, golden
output, agent 실행, agent 비교는 이 단계의 범위가 아니다. task author, evaluator author,
validity reviewer 분리는 [사전등록 계약](paired-pilot-preregistration.md#3-역할-분리와-blind)을
그대로 따른다.

## 2. 포함 규칙

`selected-for-task-authoring`으로 바꾸려면 아래 11개가 모두 `pass`여야 한다. 하나라도
`unknown`이면 `screening`에 남고, 하나라도 명시적 제외 사유에 해당하면 `excluded`다.

| rule ID | 판정 기준 |
|---|---|
| `license-or-use-basis` | task, fixture, patch lineage를 이 실험에 사용할 근거가 기록돼 있다. |
| `exact-base-resolvable` | solution 전 exact commit과 tree를 동일하게 materialize할 수 있다. |
| `single-bounded-task` | 한 checkout과 명시적 allowlist 안에서 끝나는 단일 작업이다. |
| `native-language-source` | 지시가 해당 언어로 직접 작성됐으며 상대 언어 task의 번역물이 아니다. mixed는 두 언어가 실제 요구사항에 필요하다. |
| `low-risk-isolated-execution` | 격리 checkout에서 비파괴적으로 수행할 수 있다. |
| `no-network-secret-push-production` | network, secret, push, production mutation이 필요 없다. |
| `objective-evaluator-feasible` | deterministic test, invariant, property/integration check 중 하나로 핵심 요구사항을 판정할 수 있다. |
| `gold-and-evaluator-hideable` | solution과 보호 evaluator를 agent-visible prompt, workspace, Git ref 밖에 둘 수 있다. |
| `reproducible-within-budget` | fixture와 의존성을 고정하고 사전등록 resource/time budget 안에서 반복할 수 있다. |
| `selection-independent-of-agent-results` | 후보 모집과 선택 전에 agent별 output·quality를 보지 않았다. |
| `not-used-for-confirmatory-round` | 이 pilot 뒤 confirmatory task로 재사용하지 않는다고 표시했다. |

`native-language-source`는 commit 제목이나 identifier의 언어로 추정하지 않는다. 원래
issue/task 문구가 없고 solution delta만 있는 후보는 task author가 번역이 아닌 해당
언어의 지시를 직접 구성하고 adaptation 이력을 남기기 전까지 `unknown`이다.

## 3. 제외 규칙

| rule ID | 제외 사유 |
|---|---|
| `no-parent-or-exact-base` | pre-solution base가 없거나 exact tree를 재현할 수 없다. |
| `task-source-unavailable-or-underspecified` | bounded task를 복원할 근거가 부족하다. |
| `translation-only` | Korean/English quota를 상대 언어 task의 번역으로 채운다. |
| `multiple-coupled-issues` | 독립 평가할 수 없는 여러 작업이 결합돼 있다. |
| `unsafe-or-external-side-effect` | network, credential, push, production/외부 상태 변경이 필요하다. |
| `subjective-only-evaluation` | 핵심 품질을 objective evaluator로 판정할 수 없다. |
| `broken-or-flaky-fixture` | agent 실행 전부터 fixture가 깨졌거나 반복 결과가 불안정하다. |
| `gold-or-evaluator-leakage` | 정답 patch, golden artifact, 보호 evaluator를 숨길 수 없다. |
| `resource-budget-exceeded` | 고정된 time/resource budget에서 재현할 수 없다. |
| `selected-after-agent-result` | agent별 결과를 본 뒤 후보를 넣거나 뺐다. |
| `previous-paired-task-reuse` | Phase 2a smoke 등 이전 paired 실행에서 이미 사용했다. |

제외 row는 삭제하지 않는다. 여러 제외 사유가 확인되면 모두 기록한다. fixture 문제를
고쳐 task identity가 달라지면 기존 row를 수정하지 않고 새 candidate ID와 lineage를
추가한다.

## 4. 현재 source pool snapshot

현재 snapshot은 두 source pool을 어느 agent의 결과나 leaderboard 성능으로도 거르지
않고 전부 열거했다.

| source pool | rows | 현재 판정 | 한계 |
|---|---:|---|---|
| `adaptive-ai-orchestrator` root–`0e32241` | 36 | screening 34, excluded 2 | 원래 task statement가 없는 단일 Python repo history |
| SWE-bench Multilingual `2b7aced…` default/test 전체 | 300 | screening 300 | English-only instruction, 공개 benchmark 노출, upstream 재현 미검증 |

각 pool에는 열거한 원자료 identity의 SHA-256을 기록했다. 외부 pool은 원문,
solution patch, source test patch를 ledger에 복제하지 않고 instance별 SHA-256만 남겼다.
dataset의 300 rows와 41 repository를 편의 표본으로 줄이지 않았으며 instance-level
screening 전에는 어느 row도 quota에 세지 않는다.

| 상태 | 개수 | 의미 |
|---|---:|---|
| `screening` | 334 | native 언어, evaluator 가능성, license, 격리·예산 중 하나 이상을 아직 독립 판정하지 않음 |
| `excluded` | 2 | root commit 1개는 parent base가 없고, `4c4f73c` 1개는 Phase 2a task 재사용 |
| `selected-for-task-authoring` | 0 | 현재 quota에 셀 수 있는 후보 없음 |

local commit diff는 solution lineage이지 원래 task statement가 아니다. 그래서 local
36개는 instruction language를 배정하지 않았다. 외부 300개는 공식 dataset metadata에
따라 English로만 provisional 분류했지만 원래 issue와의 native-source fidelity는 아직
instance별 `unknown`이다. 336개 모두 category 미배정이며 Korean/mixed 후보는 0개다.

[SWE-bench Multilingual](https://www.swebench.com/multilingual.html)과 그
[공식 dataset](https://huggingface.co/datasets/SWE-bench/SWE-bench_Multilingual)의
전체 English pool은 revision과 instance provenance를 pin해 inventory했다. 다만 dataset
이름이나 기존 test 존재만으로 통과시키지 않고 각 instance의 upstream license, exact
base/tree, task 원문, fixture 재현성, assertion coverage를 같은 규칙으로 검사한다.
English task pool이므로 Korean/mixed quota의 대체물도 아니다.

## 5. 보호와 검증

ledger의 `solution_revision`, solution artifact hash, source evaluator artifact hash는
construction-only 보호 metadata다.
task package를 만들 때 agent checkout은 `base_revision`만 materialize하고 다른 ref,
ledger, solution diff를 노출하지 않는다. evaluator author에게도 solution을 전달하지
않는다.

JSON Schema는 selected row의 모든 inclusion 결과가 `pass`이고 exact base와 task 원문이
있으며 exclusion ID가 비어 있음을 강제한다. 별도 semantic validation은 다음을 추가로
검사해야 한다.

- candidate/source-pool ID uniqueness와 reference integrity;
- summary count 재계산 일치;
- revision과 tree hash의 실제 Git object 일치;
- source cluster 중복과 같은 solution/task의 중복 포함;
- 최종 60개 language/category marginal quota;
- ledger freeze 뒤 selection이나 provenance 변경 여부.

다음 작업은 외부/native source pool을 instance 단위로 수집하고 34개 local-history row를
같은 규칙으로 screen하는 것이다. quota가 부족하면 번역이나 임의 분류로 채우지 않고
부족분을 그대로 보고한다.
