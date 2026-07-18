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
| `license-or-use-basis-unavailable` | 후보의 pinned revision에 license 파일이나 명시적 license 선언이 없어 `license-or-use-basis`를 `pass`로 만들 근거가 없다. |
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

`license-or-use-basis-unavailable`은 **공개 저장소에 새로운 use basis를 부여하지 않는다.**
`license-or-use-basis`는 필수 inclusion criterion인데 대응하는 terminal 사유가 없어
충족 불가능한 후보가 무기한 `screening`에 남던 schema 누락을 메우는 표현일 뿐이다.
판정은 GitHub classifier가 아니라 **exact candidate revision에 실제로 존재하는
artifact**를 근거로 한다. 현재 default branch의 license를 과거 pinned revision에 소급
적용하지 않으며, "public repository"라는 사실 자체를 use basis로 보지 않고, 불명확한
custom license를 임의 SPDX로 분류하지 않는다. base와 solution revision의 license가
다르면 양쪽을 구분해 보고하고 `pass` 처리하지 않는다. 이후 저작권자가 license를
명시하면 기존 row를 수정하지 않고 새 candidate ID와 lineage로 추가한다.

## 4. 현재 source pool snapshot

현재 snapshot은 두 source pool을 어느 agent의 결과나 leaderboard 성능으로도 거르지
않고 전부 열거했다.

| source pool | rows | 현재 판정 | 한계 |
|---|---:|---|---|
| `adaptive-ai-orchestrator` root–`0e32241` | 36 | screening 34, excluded 2 | 원래 task statement가 없는 단일 Python repo history |
| SWE-bench Multilingual `2b7aced…` default/test 전체 | 300 | screening 300 | English-only instruction, 공개 benchmark 노출, upstream 재현 미검증 |
| GitHub Korean-bearing fixed-query snapshot | 411 | screening 384, excluded 27 | query별 최신 100개 cap, 29개만 초기 수동 review/linkage probe 완료 |
| GitHub explicit multilingual fixed-query snapshot | 383 | screening 361, excluded 22 | 전체 query unique 387개 중 기존 pool과 겹친 4개를 중복 제거, 50개 수동 review |

각 pool에는 열거한 원자료 identity의 SHA-256을 기록했다. 외부 pool은 원문,
solution patch, source test patch를 ledger에 복제하지 않고 instance별 SHA-256만 남겼다.
dataset의 300 rows와 41 repository를 편의 표본으로 줄이지 않았다. GitHub pool도 고정된
첫 다섯 query가 반환한 500 rows를 URL로 중복 제거한 411개 전부를 보존했다. 명시적
multilingual query 다섯 개도 500 rows/387 unique를 보존하고, 기존 pool과 겹친 4개를
candidate 중복 없이 연결해 신규 383개를 추가했다. instance-level
screening 전에는 어느 row도 quota에 세지 않는다.

| 상태 | 개수 | 의미 |
|---|---:|---|
| `screening` | 1,079 | native 언어, evaluator 가능성, license, 격리·예산 중 하나 이상을 아직 독립 판정하지 않음 |
| `excluded` | 51 | local 2개, Korean-bearing probe 27개, explicit multilingual probe 22개 |
| `selected-for-task-authoring` | 0 | 현재 quota에 셀 수 있는 후보 없음 |

local commit diff는 solution lineage이지 원래 task statement가 아니다. 그래서 local
36개는 instruction language를 배정하지 않았다. 외부 dataset 300개는 공식 metadata에
따라 English로만 provisional 분류했지만 원래 issue와의 native-source fidelity는 아직
instance별 `unknown`이다.

Korean-bearing 411개에서는 고정 seed SHA-256 순서와 repository당 최대 1개 조건만으로
29개를 probe했다. agent 결과나 task 내용으로 표본을 고르지 않았다. 29개 원문을 읽어
28 Korean/1 genuinely bilingual requirement와 category
implementation 11/debugging 8/testing 4/refactoring 4/repository-analysis-planning 2로
provisional 분류했다. timeline에서 27개는 같은 repository의 merged PR과 exact base/head,
diff hash, changed-file scope를 복원했고 2개는 못했다. license가 확인된 4개는 base
commit/tree를 실제 upstream에서 materialize했다. 그중 iOS/CoreData 1개는 `xcodebuild`가
macOS 전용이라 Linux에서 provisioning으로도 재현할 수 없어 resource 사유로 추가
제외했다. 이후 수동 판정과 license screening을 거쳐 29개 중 **27개가 제외**됐고
`screening`에 남은 것은 factlog와 swift-tui **2개뿐**이다. 제외 사유는 private·빈 명세,
여러 작업 결합, live external API, manual-only UI verification, subjective-only
evaluation, resource, exact base 부재, 명세 부족, 그리고 license 부재다.

### 4.1 Provisioning 원칙

eligibility는 **screening host에 우연히 설치돼 있는 runtime 상태로 판정하지 않는다.**
그 기준을 쓰면 이 머신의 우발적 tooling이 그대로 selection bias가 된다. Linux에서
재현 가능한 runtime/toolchain은 manifest freeze와 agent 실행 전에 격리된 immutable
environment로 provisioning할 수 있으며, 다음을 모두 충족해야 한다.

- exact version 고정과 전이 의존성 version/artifact hash 고정;
- 양쪽 agent에 byte-equivalent immutable environment 제공;
- agent/evaluator 실행 중 network 금지;
- agent-free base/negative/positive control 재현;
- 사전 resource bucket 내 설치·실행;
- environment epoch와 fixture provenance 기록.

이 조건이 실제로 검증되기 전에는 `reproducible_within_budget`을 `pass`로 두지 않는다.
반대로 macOS 전용 도구처럼 Linux에서 재현 자체가 불가능한 경우는 provisioning 원칙과
무관하게 `resource-budget-exceeded`다.

### 4.2 exact base가 확인된 3개의 현재 상태

| candidate | decision | 상태 |
|---|---|---|
| `ghko-SeoyunL--factlog-academic-issue-314` | `screening` | 11개 중 10개 `pass`, `reproducible_within_budget` 1개만 `unknown` |
| `ghko-Chigo55--Docker-Compose-issue-38` | `excluded` | `subjective-only-evaluation` |
| `ghko-minacle--swift-tui-issue-18` | `screening` | Linux 재현성·resource 검증 대기 |

`factlog`는 issue #314가 native Korean이고 수용 기준 3개(NFC/NFD 혼용 단일 subject가
`duplicate_record`가 아닐 것, 진짜 두 subject의 공유 값은 유지될 것, NFC-only 바이트
동일)를 명시해 deterministic held-out test와 `--strict` exit-code 판정이 가능하다.
정답 test 경로는 base tree에 없어 held-out 가능하다. 남은 `unknown`은 `requires-python
>= 3.11`과 `pyrewire` 의존성을 격리 환경에서 재현하지 못했기 때문이다. base tree의
`AGENTS.md`/`CLAUDE.md`는 삭제·변경하지 않으며, 두 CLI가 받는 effective instruction의
동등성을 증명하기 전에는 environment parity와 reproducibility를 `pass`로 두지 않는다.

`Docker-Compose #38`은 native Korean이지만 산출물이 `[Unreleased]` CHANGELOG 산문이다.
pilot primary set이 허용하는 세 objective mode(deterministic acceptance test, golden
invariant, property/integration) 중 어느 것도 핵심 요구를 판정하지 못하고, 동일하게
유효한 changelog 문구가 다수이므로 병합된 산문을 exact golden으로 강제하지 않는다.
따라서 `subjective-only-evaluation` **단독** 사유로 제외했다. screening host의
`pwsh`/`docker` 부재는 이 문서 전용 변경의 재현 blocker로 확인되지 않았으므로 추가
제외 사유로 기록하지 않았다.

`swift-tui #18`은 runtime 미설치만으로 제외하지 않았다. source가 `Darwin`과 `Glibc`를
조건부로 함께 import하고, SwiftPM 의존성 6개가 `Package.resolved`에 exact revision으로
pin돼 있으며, `platforms: [.macOS(.v15)]`는 지원 플랫폼 제한이 아니라 최소 배포 타겟
선언이다. 선언된 `swift-tools-version: 6.3`은 Linux용 Swift 6.3.3으로 충족될 수 있다.
다만 issue 저자가 macOS의 Apple Swift 6.4-dev에서 검증했으므로 Linux 재현은 미증명이다.
`pass` 전에 확인할 고정 기준은 toolchain을 exact version과 artifact digest로 pin,
의존성 6개 vendoring 후 network 없는 빌드·테스트, agent-free base/control 재현,
획득·빌드·테스트의 시간과 디스크를 사전 resource bucket과 대조하는 것이다. 이 측정
자체가 screening budget을 넘으면 그 기준을 기록하고 `resource-budget-exceeded`로
제외할 수 있다. 병합 solution의 31 files(+1421/−1083)와 source-breaking 성격은
`single_bounded_task` 실패 입증이 아니라 task authoring과 allowlist 범위용 flag로만
기록했다.

명시적 multilingual pool도 고정 seed와 repository당 최대 1개 조건으로 50개를 읽었다.
실제 두 언어 이상이 요구사항에 필요한 row는 21개였고 나머지는 28 Korean/1 English로
분류했다. 하지만 번역만 하는 task 7개, 명시되지 않은 자연스러운 번역 품질을 objective
evaluator로 판정할 수 없는 task, 여러 기능을 결합했거나 live external provider를
요구하는 task 등 22개는 제외했다. provisional language 개수는 eligibility가 아니므로
현재 합계 56 Korean/301 English/22 mixed여도 selected quota는 여전히 0/0/0이다.

[SWE-bench Multilingual](https://www.swebench.com/multilingual.html)과 그
[공식 dataset](https://huggingface.co/datasets/SWE-bench/SWE-bench_Multilingual)의
전체 English pool은 revision과 instance provenance를 pin해 inventory했다. 다만 dataset
이름이나 기존 test 존재만으로 통과시키지 않고 각 instance의 upstream license, exact
base/tree, task 원문, fixture 재현성, assertion coverage를 같은 규칙으로 검사한다.
English task pool이므로 Korean/mixed quota의 대체물도 아니다.

### 4.3 License screening 결과

reviewed Korean-bearing 후보 12개는 pinned base revision을 직접 조회해 판정했다.
default branch가 아니라 **후보 revision의 tree**를 근거로 삼았고, 결과는 12/12 동일했다.

| 확인 항목 | 결과 |
|---|---|
| `LICENSE`/`LICENCE`/`COPYING`/`NOTICE`/`UNLICENSE` | 12개 저장소 전부 부재 |
| build manifest license 필드(`package.json`, `build.gradle`(`.kts`), `pyproject.toml`) | 12개 전부 선언 없음 |

각 행에는 조회한 revision, manifest path, blob SHA와 content SHA-256을 근거로 남겼다.
base와 solution revision 사이의 license 차이는 양쪽 모두 부재라 존재하지 않는다.
따라서 12개는 `license_or_use_basis`가 `fail`이며
`license-or-use-basis-unavailable`로 제외했다.

### 4.4 Repository 단위 license 조기 필터

두 GitHub pool의 screening 행 뒤에 있는 **363개 저장소 전수**를 repository 단위로 dedup해
license 신호를 조회했다. 결과는
[`phase2b-license-probe-2026-07-19.json`](../experiments/phase2b-license-probe-2026-07-19.json)에
있으며 `terminal_status`는 `false`다 — **default branch(HEAD) 기준 신호이므로 후보의 pinned
revision 사실이 아니고, 어떤 행의 판정도 바꾸지 않았다.**

| pool | 저장소 | 신호 있음 | screening 행 | 신호 뒤의 행 |
|---|---:|---:|---:|---:|
| Korean-bearing | 186 | 23 (12%) | 384 | **52** |
| explicit multilingual | 199 | 54 (27%) | 351 | **92** |

explicit pool의 보유율이 Korean pool의 두 배가 넘는다. 반대로, 앞서 exact revision까지
검사한 12개가 전부 license 부재였던 것은 pool 전체의 성질이 아니라 **이전 screening을 통과한
비무작위 부분집합**의 성질이었다. 두 신호(분류기 SPDX 식별 / 파일 존재)는 답하는 질문이
다르므로 하나의 비율로 합치지 않고 방법별로 분리해 기록했다.

조회 경로도 기록해 둔다. 저장소 metadata API는 core 한도(시간당 60)를 쓰고 raw 파일
endpoint는 그 밖이라, 같은 질문을 raw로 물으면 훨씬 빠르다. 겹치는 24개에서 두 방법의
일치율은 23/24였다. 이 신호는 종결 판정이 아니므로 값싼 경로로 수집하는 것이 맞다.

### 4.5 Quota 해석

language 20/20/20과 category 각 12는 **marginal quota**다. Korean pool 안에
`repository-analysis-planning` 12개가 따로 필요하지 않으며, 특정 pool의 category 분포가
치우쳤다는 사실을 3×5 cell 부족이나 전체 category quota 실패로 해석하지 않는다. 현재
reviewed Korean pool의 planning 후보가 2개라는 것은 사실로만 기록한다. 부족분은 번역이나
임의 분류로 채우지 않고 그대로 보고한다.

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

중단됐던 전체 264 unit test는 2026-07-19에 완주해 통과했고, 이번 screening 판정을
고정하는 회귀 테스트를 더해 현재 기준은 265 tests다. focused ledger tests는 7개가
통과한다.

JSON Schema 검증 상태는 두 단계를 구분해 기록한다. 시스템에 설치된 `jsonschema 3.2.0`은
Draft 2020-12 metaschema를 인식하지 못해 **Draft7 fallback으로만** 검증하므로, 그 결과를
단독으로 "Draft 2020-12 검증 통과"라고 부르지 않는다. 이후 `/tmp`의 격리 설치
(`jsonschema 4.26.0`, 프로젝트·전역 미변경)에서 `Draft202012Validator`로 **schema 자체의
metaschema 적합성과 ledger instance 1,130 candidates를 모두 검증해 통과했다.**
`paired-pilot-manifest-v1` schema도 같은 metaschema 검사를 통과했다.

두 결과가 일치한 이유도 확인했다. 이 schema는 Draft7이 조용히 무시하는 2020-12 전용
키워드(`prefixItems`, `unevaluatedProperties`, `unevaluatedItems`, `dependentSchemas`,
`dependentRequired`, `minContains`/`maxContains`, `$dynamicRef`)를 쓰지 않고 array-form
`items`도 없어 두 draft의 공통 부분집합 안에 있다. 이 성질은 schema 수정으로 깨질 수
있으므로, 위 키워드를 도입하면 정식 validator로 다시 검증한다.

그 다음 수동 review에서 남은 Korean 15개, 이어서 explicit-language 28개 순으로
linked PR, upstream license, exact base/tree materialization, objective evaluator 가능성,
격리·예산을 screen한다. 아직 selected row는 없으며 quota가 부족하면 번역이나 임의
분류로 채우지 않고 부족분을 그대로 보고한다. 상세 중단 상태와 순서는
[진행상황 handoff](adaptive-routing-progress.md#2026-07-19-재개-handoff)에 고정했다.
