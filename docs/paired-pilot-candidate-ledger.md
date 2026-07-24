# Phase 2b source candidate ledger

> Schema: `paired-pilot-candidate-ledger-v1`
> Protocol: `phase2b-pilot-prereg-v1.1`
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

`selected-for-task-authoring`으로 바꾸려면 아래 12개가 모두 `pass`여야 한다. 하나라도
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
| `instruction-parity` | exact pinned base가 두 CLI에 의미상 동등한 project instruction을 전달한다. global instruction은 별도 environment gate다. |
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
| `instruction-parity-mismatch` | exact pinned base가 두 CLI에 서로 다른 project instruction을 전달한다. |
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

`instruction-parity-mismatch`도 같은 terminal-path 원칙의 2026-07-22 `v1.1` amendment다.
이전에는 project instruction parity를 `reproducible-within-budget` 안에 넣어 두어 명백한
불일치도 깨끗하게 종결할 수 없었다. 이제 resource 재현과 instruction parity를 독립
판정한다. default branch prevalence는 terminal 근거가 아니며, exact pinned tree inventory와
versioned CLI behavior 또는 official discovery rule이 함께 있는 행만 판정한다.

## 4. 현재 source pool snapshot

현재 snapshot은 네 source pool을 어느 agent의 결과나 leaderboard 성능으로도 거르지
않고 전부 열거했다.

| source pool | rows | 현재 판정 | 한계 |
|---|---:|---|---|
| `adaptive-ai-orchestrator` root–`0e32241` | 36 | screening 34, excluded 2 | 원래 task statement가 없는 단일 Python repo history |
| SWE-bench Multilingual `2b7aced…` default/test 전체 | 300 | screening 291, excluded 9 | English-only instruction, 공개 benchmark 노출; exact terms/base/license, candidate-tree parity, native-source, boundedness 291과 evaluator feasibility 290 완료; evaluator 1·격리·hiding·재현성 미검증 |
| GitHub Korean-bearing fixed-query snapshot | 411 | screening 347, excluded 60, selected-for-task-authoring 4 | query별 최신 100개 cap, manual/contextual/cascade review 포함 |
| GitHub explicit multilingual fixed-query snapshot | 383 | screening 295, excluded 75, selected-for-task-authoring 13 | 전체 query unique 387개 중 기존 pool과 겹친 4개를 중복 제거, deterministic review와 후속 contextual/cascade batch 포함 |

각 pool에는 열거한 원자료 identity의 SHA-256을 기록했다. 외부 pool은 원문,
solution patch, source test patch를 ledger에 복제하지 않고 instance별 SHA-256만 남겼다.
dataset의 300 rows와 41 repository를 편의 표본으로 줄이지 않았다. GitHub pool도 고정된
첫 다섯 query가 반환한 500 rows를 URL로 중복 제거한 411개 전부를 보존했다. 명시적
multilingual query 다섯 개도 500 rows/387 unique를 보존하고, 기존 pool과 겹친 4개를
candidate 중복 없이 연결해 신규 383개를 추가했다. instance-level
screening 전에는 어느 row도 quota에 세지 않는다.

| 상태 | 개수 | 의미 |
|---|---:|---|
| `screening` | 967 | bounded task, evaluator 가능성, instruction parity, 격리·예산 중 하나 이상을 아직 독립 판정하지 않음 |
| `excluded` | 146 | local 2개, SWE-bench 9개, Korean-bearing pool 60개, explicit multilingual pool 75개 |
| `selected-for-task-authoring` | 17 | 12개 inclusion rule을 모두 `pass`한 construction queue 후보; final pilot task가 아님 |

local commit diff는 solution lineage이지 원래 task statement가 아니다. 그래서 local
36개는 instruction language를 배정하지 않았다. 외부 dataset 300개는 공식 metadata에
따라 English로만 provisional 분류했다. Exact dataset terms/base/license와 candidate-tree
instruction parity를 통과한 291행은 현재 공개 GitHub issue의 `title + LF + body + LF`를
다시 구성한 SHA-256이 pinned statement와 291/291 일치해 native-source fidelity도
instance별 `pass`다. 표면 언어 탐지는 이 연결을 보조할 뿐 단독 근거로 쓰지 않았다.
이어진 source-first 의미 검토에서 291행 모두 하나의 bounded top-level outcome으로
판정됐다. Objective evaluator feasibility는 290행이 `pass`이고
`swebm-faker-ruby__faker-2705` 한 행만 `unknown`이다. 이 source는 기본 digit 보장과 이름을
정하지 않은 opt-in parameter 중 어느 쪽도 허용하므로, solution이 택한 API를 보호 oracle이
임의로 강제하지 않는다. 이 부분 적용 뒤에도 291행은 모두 `screening`이다.

Korean-bearing 411개에서는 고정 seed SHA-256 순서와 repository당 최대 1개 조건만으로
29개를 probe했다. agent 결과나 task 내용으로 표본을 고르지 않았다. 29개 원문을 읽어
28 Korean/1 genuinely bilingual requirement와 category
implementation 11/debugging 8/testing 4/refactoring 4/repository-analysis-planning 2로
provisional 분류했다. timeline에서 27개는 같은 repository의 merged PR과 exact base/head,
diff hash, changed-file scope를 복원했고 2개는 못했다. license가 확인된 4개는 base
commit/tree를 실제 upstream에서 materialize했다. 그중 iOS/CoreData 1개는 `xcodebuild`가
macOS 전용이라 Linux에서 provisioning으로도 재현할 수 없어 resource 사유로 추가
제외했다. 이후 수동 판정, license screening, instruction parity 판정을 거쳐 29개 중
초기 29개와 후속 두 행을 합친 현재 31개 중 **28개가 제외**됐고,
`factlog-academic #314/#342`와 `ChunChuGwan #406`은
`selected-for-task-authoring`이다. 제외 사유는 private·빈 명세,
여러 작업 결합, live external API, manual-only UI verification, subjective-only
evaluation, resource, exact base 부재, 명세 부족, 그리고 license 부재다. 이 문단은 초기
31개 probe 범위의 역사적 요약이며, 이후 cascade 결과를 포함한 현재 값은 위 pool 표와
상태 표를 따른다.

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

### 4.2 exact base가 확인된 행의 현재 상태

`exact_base_resolvable`이 `pass`인 행은 **108개**다. 그중 35개는
`aao-local-history-through-0e32241` pool의 이 저장소 자신의 commit이라 base가 자명하게
해소되며(그중 1개는 Phase 2a smoke에 이미 쓰여 `previous-paired-task-reuse`로 제외),
외부 후보는 **73개**다. 아래 표는 cost cascade 전에 수동 판정한 초기 외부 31개와
후속 selected 행을 요약한다.
2026-07-24 rank 5에서 새로 materialize한 30개와 기존 `doc_parser #288` 재확인 결과는
[`phase2b-exact-revision-license-2026-07-24.json`](../experiments/phase2b-exact-revision-license-2026-07-24.json)에
full revision/tree/path/license hash로 고정했다.

| candidate | decision | pass | 남은 것 |
|---|---|---:|---|
| `ghmix-semantic-reasoning--factlog-issue-26` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-joshua-jingu-lee--ante-issue-2349` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-e7217--anygarden-issue-512` | `selected-for-task-authoring` | 12/12 | — |
| `ghko-SeoyunL--factlog-academic-issue-314` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-KoreaNirsa--prompt-booster-issue-10` | `selected-for-task-authoring` | 12/12 | — |
| `ghko-SeoyunL--factlog-academic-issue-342` | `selected-for-task-authoring` | 12/12 | — |
| `ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406` | `selected-for-task-authoring` | 12/12 | — |
| `ghko-hissinger--small-village-issue-54` | `selected-for-task-authoring` | 12/12 | final validity에서 offline roster invariant와 hosted 3-client E2E 문장 범위 대조 필요 |
| `ghmix-genonai--doc_parser-issue-288` | `selected-for-task-authoring` | 12/12 | synthetic XLSX base-negative/solution-positive 통과 |
| `ghmix-Sungho-pk42ac--agentguard-issue-687` | `selected-for-task-authoring` | 12/12 | doctor contract와 sequential full suite 통과 |
| `ghmix-Sungho-pk42ac--agentguard-issue-591` | `selected-for-task-authoring` | 12/12 | machine-output documentation property contract와 sequential full suite 통과 |
| `ghmix-KoreaNirsa--prompt-booster-issue-3` | `selected-for-task-authoring` | 12/12 | source-derived intent 9 assertions 통과 |
| `ghmix-joshua-jingu-lee--ante-issue-2398` | `selected-for-task-authoring` | 12/12 | readiness control 63/63 base-negative, 63/63 solution-positive |
| `ghmix-jinwon-int--a2a-nexus-issue-1190` | `selected-for-task-authoring` | 12/12 | docs policy 10-property base-negative/solution-positive와 Markdown-link health 통과 |
| `ghmix-Ootzk--Wor-chain-dle-issue-173` | `selected-for-task-authoring` | 12/12 | Korean locale에서 fixed English mode-label behavior와 양쪽 App health 통과 |
| `ghmix-Ootzk--Wor-chain-dle-issue-130` | `selected-for-task-authoring` | 12/12 | Patch Notes tab interaction과 양쪽 App health 통과 |
| `ghmix-B-TING--bu-ting-mobile-issue-75` | `selected-for-task-authoring` | 12/12 | memo vertical 4 controls 통과; final rollback evaluator는 behavioral failure-and-restore로 교체 필요 |
| `ghmix-hskim-solv--BidMate-DocAgent-issue-1152` | `excluded` | 11/12 | `instruction-parity-mismatch` |
| `ghmix-YSbookcase--TimePilot-issue-62` | `screening` | 10/12 | evaluator 저술·재현 미완료, instruction parity 미판정 |
| `ghmix-ohhalim--MembershipFlow-issue-79` | `excluded` | 6/12 | exact base 전체에 license/use basis가 없어 `license-or-use-basis-unavailable`; parity는 pass |
| `ghmix-0xkkun--seoul-challenge-issue-30` | `excluded` | 5/12 | exact base에 license/use basis가 없고 task-relevant root `AGENTS.md` only라 license와 parity가 모두 terminal fail |
| `ghmix-Gn0lee--oat-issue-410` | `excluded` | 5/12 | root app use basis가 없고 task-relevant root `CLAUDE.md` only라 license와 parity가 모두 terminal fail |
| `ghmix-handokei--subway-now-issue-1465` | `excluded` | 5/12 | exact base에 code/fixture use basis가 없고 task-relevant root `CLAUDE.md` only라 license와 parity가 모두 terminal fail |
| `ghmix-prgrms-aibe-devcourse--...--JackPot-issue-499` | `excluded` | 6/12 | exact base 전체에 license/use basis가 없어 `license-or-use-basis-unavailable`; parity는 pass |
| `ghmix-SKALA-TEAM5--frontend-issue-66` | `excluded` | 6/12 | PR의 마지막 issue-specific commit을 분리했지만 exact base에 license/use basis가 없음; parity는 pass |
| `ghko-minacle--swift-tui-issue-18` | `excluded` | 6/12 | exact base의 task-relevant root `AGENTS.md` only profile로 `instruction-parity-mismatch` |
| `ghko-Aiddoo--Aido-platform-issue-655` | `excluded` | 5/12 | parity는 통과했지만 독립된 queue retention과 Redis eviction probe를 결합해 `multiple-coupled-issues` |
| `ghko-hissinger--small-village-issue-51` | `excluded` | 5/12 | parity는 통과했지만 transport·polling·render·naming 작업을 결합해 `multiple-coupled-issues` |
| `ghko-Soku-JINSEOK--Soku-Convention-Boilerplate-issue-19` | `excluded` | 4/12 | root `AGENTS.md` only인 `instruction-parity-mismatch` |
| `ghko-Lyainc--filme-issue-432` | `excluded` | 4/12 | `instruction-parity-mismatch`; exact base와 MIT 확인 |
| `ghko-minacle--swift-tui-issue-15` | `excluded` | 4/12 | `instruction-parity-mismatch`; exact base와 Unlicense 확인 |
| `ghko-ohah--zntc-issue-4564` · `#4563` · `#4553` | `excluded` | 4/12 | `instruction-parity-mismatch` |
| `ghmix-SeokRae--blog-issue-12` | `excluded` | 4/12 | `instruction-parity-mismatch` |
| `ghmix-greenheadHQ--nixos-config-issue-918` | `excluded` | 4/12 | `instruction-parity-mismatch` |
| `ghko-itismyfield--AgentDesk-issue-4606` | `excluded` | 4/12 | `instruction-parity-mismatch` |
| `ghko-Chigo55--Docker-Compose-issue-38` | `excluded` | 6/12 | `subjective-only-evaluation`; parity는 default-branch 신호뿐이라 `unknown` |
| `ghmix-seob717--nunchi-issue-35` | `excluded` | 5/12 | `subjective-only-evaluation` |
| `ghko-ProudlyOffbeat--...-MVP-iOS-issue-93` | `excluded` | 5/12 | `resource-budget-exceeded` |

#### instruction parity는 독립된 eligibility rule이다

2026-07-22 `v1.1`에서 project instruction parity를 resource reproducibility에서 분리했다.
base tree가 두 CLI에게 서로 다른 지시를 주면 fixture 자체가 비대칭이며
`instruction-parity-mismatch`로 terminal 제외한다. inventory나 discovery 근거가 부족하면
`unknown`에 둔다.

base tree의 agent instruction 파일은 **삭제·변경하지 않는다.** project instruction parity와
global instruction context도 구분한다. 전자는 후보 rule이고, 후자는 manifest 실행 환경
gate다. 측정과 한계는
[parity artifact](../experiments/phase2b-agent-instruction-parity-2026-07-20.json)와
[6차 handoff](adaptive-routing-progress.md#2026-07-22-6차-handoff--codex-discovery와-instruction-parity-v11)에 있다.

Claude Code 2.1.215는 실측으로 `AGENTS.md`를 읽지 않으며 `CLAUDE.md` 안의 `@AGENTS.md`
import는 해석한다. Codex 0.144.6은 2026-07-22 격리된 임시 Git 저장소에서 root
`AGENTS.md` marker를 정확히 출력해 그 한 case만 behaviorally 확인됐다. override precedence,
root-to-cwd traversal, fallback selection은 행동 실측이 아니라
[공식 Codex 문서](https://developers.openai.com/codex/guides/agents-md) 근거다. 로컬 config에
`project_doc_fallback_filenames`가 없으므로 `TEAM_GUIDE.md`와 `.agents.md`는 이 환경의
fallback이 아니다. `v1.1`은 이 기본 empty fallback을 candidate 판정과 future manifest에
고정한다. fallback을 바꾸려면 전체 parity 판정을 새 amendment로 다시 수행한다.

초기 기록이 두 파일 확인에 그쳤던 `factlog #26`, `ante #2349`, `factlog #314`,
`BidMate #1152`는 GitHub의 exact base recursive tree API로 다시 inventory했다. 각 응답은
`truncated=false`였고 Git Commit API의 `tree.sha`가 ledger tree hash와 일치했다. 각각
77/1,057/373/845 entries이며, active path 결과는 없음 / 동일 symlink / import pair /
`CLAUDE.md` only였다. 따라서 이 네 판정도 default-branch나 부분 inventory에 기대지 않는다.

어떤 candidate도 default-branch prevalence row로 판정하지 않았다. 초기 exact pinned
inventory 27개는 pass 13 / fail 14였다. 2026-07-24 rank 6에서 새 exact tree 25개를
추가 판정해 pass 9 / fail 16으로 만들었고, 후속 scope-review exact tree 12개는 pass 4 /
fail 8이었다. 따라서 누적은 **64개, pass 26 / fail 38**이고 나머지는 `unknown`이다.
새 blob/path/effective-chain 근거는
[`phase2b-rank6-instruction-parity-2026-07-24.json`](../experiments/phase2b-rank6-instruction-parity-2026-07-24.json)에
있으며, 후속 12건은
[`phase2b-scope-review-instruction-parity-2026-07-24.json`](../experiments/phase2b-scope-review-instruction-parity-2026-07-24.json)에
있다. `Docker-Compose #38`도
default-branch에서 `CLAUDE.md`만 관찰됐을 뿐 pinned-base parity 근거가 아니므로 기존의
독립적인 subjective exclusion만 유지한다.

`anygarden #512`는 941개
파일 base tree 전수에 두 CLI가 자동 발견하는 경로의 파일이 하나도 없어, Codex 측정과
무관하게 양쪽이 fixture로부터 아무 지시도 받지 않는다.

#### 개별 행의 근거

`factlog #314`는 issue가 native Korean이고 수용 기준 3개(NFC/NFD 혼용 단일 subject가
`duplicate_record`가 아닐 것, 진짜 두 subject의 공유 값은 유지될 것, NFC-only 바이트
동일)를 명시해 deterministic held-out test와 `--strict` exit-code 판정이 가능하다.
정답 test 경로는 base tree에 없어 held-out 가능하다. 2026-07-20에 `requires-python >= 3.11`과
`pyrewire`를 격리 환경에서 재현해 negative control 3실패/6통과(전부 의도한 미구현 동작),
positive control 9/9, evaluator 1.2초 `small`을 확인했으므로 **재현은 더 이상 blocker가
아니다.** pinned tree의 `AGENTS.md` 1,047B를 Claude는 11바이트 `CLAUDE.md`의
`@AGENTS.md` import로 받고, Codex는 root `AGENTS.md` behavioral probe로 받음이 확인돼
parity도 `pass`다. 12/12가 되어 `selected-for-task-authoring`으로 이동했지만 task authoring은
수행하지 않았다. 이 행의 license 근거는 원래 classifier 신호였으나 pinned revision
artifact로 정정했다.

`Docker-Compose #38`은 native Korean이지만 산출물이 `[Unreleased]` CHANGELOG 산문이다.
pilot primary set이 허용하는 세 objective mode(deterministic acceptance test, golden
invariant, property/integration) 중 어느 것도 핵심 요구를 판정하지 못하고, 동일하게
유효한 changelog 문구가 다수이므로 병합된 산문을 exact golden으로 강제하지 않는다.
따라서 `subjective-only-evaluation` **단독** 사유로 제외했다. screening host의
`pwsh`/`docker` 부재는 이 문서 전용 변경의 재현 blocker로 확인되지 않았으므로 추가
제외 사유로 기록하지 않았다.

`swift-tui #18`은 runtime 미설치나 resource 측정으로 제외하지 않았다. Linux 재현 자체는
실제로 가능했다 — Swift 6.3.3으로 빌드와 1,064개 테스트가 모두 통과했다(`medium`, 90초).
`Darwin`/`Glibc` 조건부 import, `Package.resolved`의 exact revision pin 6개,
최소 배포 타겟 선언일 뿐인 `platforms: [.macOS(.v15)]`가 그 근거였다.

상류 테스트를 evaluator로 쓸 수 없음도
실측으로 확인됐다 — PR의 테스트 hunk를 base에 적용하면 compile error 171개이고,
`RenderedTextInputAnchor` 등 **이슈가 명명하지 않은 내부 타입**을 요구한다. 즉 테스트가
과제 문구가 진술한 수준이 아니라 구현 내부를 검사한다. 테스트 파일 13개를 가지고도
실격이라는 점에서, "정답 PR이 테스트를 건드린다"는 신호가 평가 가능성을 보장하지 않음을
보여주는 사례다. 병합 solution의 31 files(+1421/−1083)와 source-breaking 성격은
`single_bounded_task` 실패 입증이 아니라 task authoring과 allowlist 범위용 flag로만
기록했다. 다만 새 evaluator를 저술하기 전에 exact 224-entry base instruction을 완성해
root `AGENTS.md` only profile을 확인했다. 그 지침의 access control, public API documentation,
test organization/name, validation 규칙은 이 31-file refactor에 직접 적용되지만 Claude에는
대응 `CLAUDE.md`나 import가 없다. 따라서 `instruction-parity-mismatch`로 terminal 제외했고,
평가기를 더 저술하지 않았다. Exact-base `UNLICENSE`와 one-commit solution tree도 pinned
artifact로 기록했다.

`TimePilot #62`는 Linux 빌드가 `-p:EnableWindowsTargeting=true`로 성공했으나(0 warning /
0 error, 8초) **정답 PR에 테스트가 0개**라 재구성할 gold test가 없다. `swift-tui`와 같은
이유로 evaluator를 새로 저술해야 하고, 이는 §3 역할 분리 대상이다. 빌드 통과는 negative
control을 대신하지 않는다.

`BidMate #1152`는 2026-07-20에 재현을 마쳤다. impl과 test가 모두 base에 있어 evaluator를
PR 시점으로 재구성했고, negative control 26실패/27통과(24건이 누락 함수 4개의
`AttributeError`, 2건이 존재하지 않는 `--check-fragments` 인자), positive control 53/53,
evaluator 0.6초 `small`이므로 `reproducible-within-budget`은 `pass`다. 그러나 pinned base는
`CLAUDE.md` 12,250B만 있고 Codex가 읽는 project path가 없어 parity가 `fail`이며
`instruction-parity-mismatch`로 제외했다. 별도로 기록해 둔 두 관찰: real-repo sentinel이
base에서 `AttributeError`로 먼저 죽어 문서가 실제로 깨져 있었음을 독립 입증하지는 못하며,
병합 변경이 fragment 검증 추가와 문서 4건 수정을 함께 담고 있다. 이 관찰은 이미 terminal인
parity 판정을 바꾸지 않는다.

같은 exact-base 근거로 `blog #12`와 `AgentDesk #4606`의 `CLAUDE.md`-only profile,
`zntc #4564/#4563/#4553`의 서로 다른 두 root 파일, `nixos-config #918`의 distinct
`AGENTS.override.md`도 `instruction-parity-mismatch`로 제외했다. 반대로
`factlog-academic #342`는 PR #352 전체가 아니라 이슈만 해결하는 첫 atomic commit을
solution으로 고정했다. 보호 evaluator에서 base는 명세의 `JSONDecodeError`로 0.28초에
실패하고 solution은 malformed/normal quoted-string 2/2를 0.27초에 통과했다. Exact-base
Apache-2.0과 `@AGENTS.md` import parity를 포함해 12/12가 되어 선정했다.

`ChunChuGwan #406`은 task-relevant storage/dashboard/testing 경로에서 root `AGENTS.md`가
Codex에게 같은 `CLAUDE.md` SSOT와 canonical path index를 전달하므로 parity가 통과했다.
Mode 0444 평가기 SHA-256 `d79234ed…f41c3e`는 공개 document route의 auth, S3 full/range
byte/header, zero `local_path`, local FileResponse/CSP/attachment를 검사한다. Base는 S3
read-through materialization 때문에 1.37초에 실패했고 one-commit solution은 1.38초에
통과해 12/12로 선정했다. 고정 Starlette TestClient/AnyIO portal hang은 애플리케이션과
분리해 기록했으며 solution private helper를 evaluator contract로 삼지 않았다.

`nunchi #35`는 license와 exact base를 확인했으나 산출물이 objective evaluator로 판정되지
않아 `subjective-only-evaluation`으로 제외했다. 병합 변경 26개 중 실제 산출물은
`commands/compile.md`의 자연어 스펙 절 하나이고 나머지는 LLM 출력 JSON과 결과 서술
문서다. 그 스펙이 의도대로 작동했는지는 LLM 컴파일러를 돌려 판단 품질을 평가해야 알 수
있으므로 세 objective mode 중 어느 것에도 해당하지 않는다. 이 행의 linked PR은 릴리스
자동화 PR(#28)을 집었다가 #37로 정정한 사례이기도 하다. `native_language_source`는
`unknown`으로 남아 있다 — provisional 분류가 `ko`인 것은 배정이지 판정이 아니다.

`iOS #93`은 `xcodebuild`가 macOS 전용이라 Linux에서 provisioning으로도 재현할 수 없어
`resource-budget-exceeded`다. provisioning 원칙과 무관한 자원 사유다.

명시적 multilingual pool도 고정 seed와 repository당 최대 1개 조건으로 50개를 읽었다.
실제 두 언어 이상이 요구사항에 필요한 row는 21개였고 나머지는 28 Korean/1 English로
분류했다. 하지만 번역만 하는 task 7개, 명시되지 않은 자연스러운 번역 품질을 objective
evaluator로 판정할 수 없는 task, 여러 기능을 결합했거나 live external provider를
요구하는 task 등 22개는 제외했다. provisional language 개수는 eligibility가 아니므로
현재 합계 61 Korean/301 English/22 mixed이고 construction queue의 language marginal은
ko 7 / en 0 / mixed 0이다.

2026-07-22에는 위 deterministic 50-row review와 구분되는 contextual screening 3건을
추가했다. 주 검토자가 unresolved mechanical-prefilter 후보 중 작은 batch를 정하고 issue,
linked PR, changed-file 원자료 snapshot을 준비한 뒤, 내용 비교에 적합한 Claude를 수동 지정해
읽기 전용 분석만 맡겼다. 최종 판정은 주 검토자가 원문과 ledger hash를 다시 대조했다.
`ccc-node #34`는 다섯 제안과 여덟 acceptance item을 묶고 원문이 네 PR 분할을 요구하며,
linked PR #35도 첫 slice만 완성했다고 명시하므로 원래 candidate identity 전체를
`multiple-coupled-issues`로 제외했다. 이어서 `filme #432`와 `swift-tui #15`의 linked PR
base/head를 git protocol로 materialize하고 각각 MIT/Unlicense를 pinned tree에서 확인했다.
그러나 전자는 root `CLAUDE.md` only, 후자는 root `AGENTS.md` only라 v1.1 project instruction
parity가 모두 실패해 `instruction-parity-mismatch`로 제외했다. nested
`.claude/skills/react-best-practices/AGENTS.md`는 repository-root working directory의 Codex
root-to-cwd discovery path가 아니므로 `filme`의 동등 지시로 세지 않았다. 이 batch는
`--agent auto` routing evidence가 아니며 candidate agent도 실행하지 않았다.

같은 날 두 번째 contextual batch는 mechanical-prefilter의 아직 미판정인 세 행을 고르고,
정확한 9개 issue/PR/files snapshot만 격리 workspace에서 읽도록 Claude를 수동 지정했다. 첫
호출은 파일명 열거 도구가 없어 내용 분석 전에 끝났고, exact filenames를 제공한 재호출만
내용 자문으로 사용했다. 주 검토자가 원문을 다시 대조한 결과 `factlog #269`는 config
plumbing만 deterministic하게 검사할 수 있고 핵심 narration/gloss 품질은 객관 판정할 수
없어 `subjective-only-evaluation`, `filme #348`은 private ticket/ground truth와 secret-bearing
live Gemini call이 이슈 자체의 필수 검증이라 `unsafe-or-external-side-effect`로 제외했다.
`ChunChuGwan #406`은 cache bypass, Range, header, auth invariant를 원문에서 독립 도출할 수
있어 terminal 판정 없이 linked PR base/head를 materialize했다. Base/head parent, 616-entry
base tree, 7-file diff scope와 pinned MIT를 확인했다. Root `AGENTS.md`가 `CLAUDE.md`를 SSOT로
읽으라고 지시하지만 Codex-specific 안내가 있고 Claude 쪽에는 10개 path rule이 있어,
semantic delivery parity는 path 존재만으로 추정하지 않고 `unknown`에 뒀다. 이 호출들도
manual cohort이며 routing evidence나 candidate agent execution이 아니다.

세 번째 contextual batch는 사전필터 순서상 다음 세 Korean-bearing 행을 처리했다. 모든
linked PR의 API base/head를 partial Git clone으로 materialize하고 ancestry, base/head tree,
base-to-head changed files, PR diff SHA-256을 로컬 Git과 원자료 양쪽에서 대조했다. Pinned
license는 `Aido #655` MIT, `small-village #51` Apache-2.0, `Soku #19` MIT로 직접 읽었다.
`Aido`는 root와 변경 scope인 `apps/api`에서 각각 `CLAUDE.md`가 대응 `AGENTS.md`를 import하고,
`small-village`는 root `CLAUDE.md`가 `AGENTS.md` symlink라 parity를 통과했다. 그러나 `Aido`
원문은 failed-job retention/cleanup과 별도 Redis eviction health probe를, `small-village`
원문은 position transport 외에 reconcile polling, render churn, naming을 독립 후속 과제로
묶으므로 둘 다 `single_bounded_task=fail`과 `multiple-coupled-issues`로 제외했다. `Soku`는
113-entry exact base에 root `AGENTS.md`만 있어 `instruction-parity-mismatch`로 제외하고,
terminal 판정에 필요 없는 boundedness는 `unknown`으로 보존했다.

복합 과업 경계를 교차확인하기 위해 execution
`manual-context-review-2026-07-22`에서 Claude를 명시한 읽기 전용 자문을 한 번 사용했다
(기록 비용 `$0.1283065`). 자문은 `Aido`와 `small-village`가 독립 수용 기준을 묶는다는 해석에
동의했지만, 최종 판정은 주 검토자가 issue/PR 원문과 exact Git objects를 다시 대조해
확정했다. 이 호출은 candidate agent 실행도, objective-quality observation도, auto routing
표본도 아니며 ledger selection이나 routing 성능 근거로 사용하지 않는다.

네 번째 contextual batch는 explicit multilingual pool의 다음 세 행을 처리했다.
`hsr-warp #12`는 기존 한국어 dashboard copy를 영어·중국어·일본어 사전으로 옮기고 각
언어권 통용 game term을 고르는 것이 핵심이라 toggle/persistence 구현이 함께 있어도
`translation-only`로 제외했다. `filme #391`은 fallback 순서·visibility 같은 deterministic
slice가 있지만 quote 문장, 평점 구간별 preset, 실제 렌더 대조로 고를 font, 실측 글자수
상한이 모두 필수이면서 구현자 판단에 맡겨져 있어 그 slice만 채점하면 원 candidate를
축소한다. 따라서 `subjective-only-evaluation`으로 제외했다. 두 terminal 행은 base·license·
parity를 불필요하게 확장하지 않고 `unknown`으로 보존했다.

`doc_parser #288`은 GitHub PR API의 base `b4b2b17…`가 head의 ancestor가 아닌 예외였다.
이를 그대로 쓰면 40-file delta가 되므로 commit graph의 merge-base이자 earliest solution
commit parent `3107d966…`를 exact pre-solution base로 확정했다. 이 base-to-head diff는
GitHub의 현재 17-file PR inventory와 일치한다. 1,167-entry base tree의 root
`pyproject.toml`은 MIT를 선언하고 두 CLI의 project instruction path는 모두 없어 parity도
통과했다. 원 issue 자체는 PDF intermediate 없이 XLSX를 직접 처리해 logical row 분할을
막는 단일 Korean implementation task이며 dummy file을 명시하므로 synthetic XLSX에서
row integrity와 PDF/LibreOffice path 비호출을 offline 판정할 수 있다. PR의 csv/xlsm,
docling/tabular mode, metadata alias, dispatcher refactor는 solution-only design으로 task
requirement에 소급하지 않는다. 현재 11/12이며 `reproducible_within_budget`만 agent-free
negative/positive control 뒤 판정한다.

`prompt-booster #10`은 native Korean으로 prompt pattern library의 schema·loader validation·
sample·optimizer integration·test를 한 묶음으로 명시한 bounded implementation task다. Issue를
직접 해결한 one-commit PR #34의 API base가 head의 ancestor이자 local merge-base임을 확인했고,
exact base `5f6a045…` / tree `7476e28…`의 28 entries와 9-file diff를 materialize했다. Pinned
`LICENSE`와 `README`는 Apache-2.0이고, full base tree에는 양쪽 CLI가 발견하는 project
instruction path가 없어 parity도 통과했다. Agent 없이 pristine base 41 tests, head 47 tests,
test-hunk-only base negative control 5 pass / 2 fail / 1 import error, head targeted positive
control 13/13을 각각 0.14초 이내에 재현했다. 실패는 `PatternLibrary`, `match_patterns`,
`patternMatches`라는 요구 동작 부재에 한정됐다. Source test는 환경·동작 판별 가능성의
근거일 뿐 final evaluator가 아니므로, 독립 evaluator 저술은 다음 역할에 남겨 둔 채 12/12
`selected-for-task-authoring`으로 이동했다.

이 경계 검토를 Claude에 맡긴 첫 orchestration execution
`doc-parser-review-network-blocked`는 `/tmp` read permission이 없어 source 판단 없이
중단됐고(`$0.2033665`), workspace 안의 동일 snapshot으로 재시도한
`doc-parser-review-completed`만 내용 자문을 반환했다(`$0.230582`). 둘 다
`manual`, `routing_evidence_eligible=false`이며 objective quality observation이 아니다.
자문은 issue-only면 bounded, PR 전체를 requirement로 삼으면 과확장이라고 조건부로
구분했고, 주 검토자는 기존 protocol의 source-issue task identity와 solution-breadth precedent를
대조해 screening을 확정했다. 이후 일반 작업·자문 위임은 오케스트레이터 log에 섞지 않고
Claude CLI를 직접 사용하며, 오케스트레이터는 objective evaluator가 있는 routing/lifecycle
실행에만 사용한다.

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

중단됐던 전체 264 unit test는 2026-07-19에 완주해 통과했고, screening 판정을 고정하는
회귀 테스트를 더해 265 tests가 됐다. 2026-07-20 전체 suite 270 tests는 역사적 기록이다.
2026-07-22 `v1.1` focused ledger suite는 behavioral/documentary provenance 분리,
exact-base-only parity 판정, global gate와 네 번째 contextual batch의 source/Git boundary를
고정하고 다섯 번째 batch의 agent-free reproducibility control, Chun route reproduction,
여섯 번째 swift-tui exact-base parity를 추가해 **21 tests가 통과했다.** Web UI 제거와
Python package 책임 경계 정리까지 반영한 전체 suite는 **274 tests가 통과했다.**
2026-07-24 rank 5 적용 뒤에는 focused candidate-ledger **35 tests**, 전체 suite
**288 tests**가 통과했다.
Rank 6 parity 적용 뒤에는 focused **36 tests**, 전체 suite **289 tests**가 통과했다.
Rank 7 semantics/reproduction 적용 뒤에는 focused **37 tests**, 전체 suite **290 tests**가
통과했다. SWE-bench semantic triage/review와 partial ledger application까지 반영한 현재
snapshot은 focused **47 tests**, 전체 suite **300 tests**가 통과했다.

JSON Schema 검증 상태는 두 단계를 구분해 기록한다. 시스템에 설치된 `jsonschema 3.2.0`은
Draft 2020-12 metaschema를 인식하지 못해 **Draft7 fallback으로만** 검증하므로, 그 결과를
단독으로 "Draft 2020-12 검증 통과"라고 부르지 않는다. 2026-07-20의 amendment 전 schema는
`/tmp` 격리 `jsonschema 4.26.0` `Draft202012Validator`로 metaschema와 1,130-row instance,
manifest schema까지 통과했다. 2026-07-22 `v1.1` 변경 뒤에도 동일한 4.26.0
`Draft202012Validator`로 candidate/manifest schema metaschema와 현재 1,130-row ledger
instance를 다시 검증해 통과했다. 시스템 Draft7 fallback 결과와 정식 결과를 구분해 남긴다.

두 결과가 일치한 이유도 확인했다. 이 schema는 Draft7이 조용히 무시하는 2020-12 전용
키워드(`prefixItems`, `unevaluatedProperties`, `unevaluatedItems`, `dependentSchemas`,
`dependentRequired`, `minContains`/`maxContains`, `$dynamicRef`)를 쓰지 않고 array-form
`items`도 없어 두 draft의 공통 부분집합 안에 있다. 이 성질은 schema 수정으로 깨질 수
있으므로, 위 키워드를 도입하면 정식 validator로 다시 검증한다.

## 6. 심사 순서

초기 순서는 pool을 순차 수동 review하는 것이었다(남은 Korean 15개, 이어서
explicit-language 28개). 2026-07-19에 **이 순서를 바꿨다.** 수동 읽기가 파이프라인에서
가장 비싼 단계인데 맨 앞에 있었고, `selected`에 도달한 후보는 모두 정답 PR이 테스트
파일을 건드렸으며 그 성질은 issue HTML과 `.diff`로 API 한도 없이 판정된다. 기계적
사전필터를 앞에 두어 수동 읽기 대상을 141행에서 36행으로 줄였다
([사전필터 artifact](../experiments/phase2b-mechanical-prefilter-2026-07-19.json)).

**이 필터는 우선순위 도구이지 판정이 아니다.** `terminal_status`는 `false`이며 어떤
inclusion rule도 결정하지 않는다. 통과한 30행을 읽어 9행을 제외했고, `swift-tui #18`은
테스트 13개를 가지고도 내부 API를 검사해 실격이다. 정답 PR이 테스트를 건드린다는 사실이
평가 가능성을 보장하지 않는다.

2026-07-24에는 이 원칙을 전체 현재 ledger에 적용한
[license-priority artifact](../experiments/phase2b-license-priority-2026-07-24.json)를
추가했다. 이는 새 eligibility rule이나 source-frame amendment가 아니라 **심사 순서만
바꾸는 nonterminal artifact**다. Frozen repository-level probe를 source pool과 무관하게
같은 저장소의 행에 재사용해 cascade 시작 시점의 GitHub `screening` 691건을 다음처럼 분리했다.

이 license queue는 다시
[cost-ordered screening cascade](../experiments/phase2b-screening-cascade-2026-07-24.json)의
rank 2–3에 들어간다. Cascade는 cached ledger/source identity → repository license signal
→ license type → issue/PR/test-scope metadata → exact base와 pinned license → exact-tree
instruction inventory → manual boundedness/evaluator/reproduction 순이다. Rank 0–4는
nonterminal priority이고 exact-revision evidence가 생기는 rank 5부터만 pass/fail을 허용한다.

| bucket | rows | 의미 |
|---|---:|---|
| exact pinned license pass | 2 | `TimePilot #62`, `doc_parser #288`; 나머지 rule 심사 가능 |
| permissive classifier signal | 36 | exact pre-solution revision에서 허용 license를 재확인해야 함 |
| license-file-only signal | 66 | current HEAD 분류 완료: 허용형 64, GPL-3.0 1, PolyForm Noncommercial 1; exact revision 재확인 필요 |
| ineligible copyleft classifier signal | 2 | GPL-3.0/AGPL-3.0 신호; exact revision 확인 전에는 제외 아님 |
| `none-observed` | 585 | license 부재의 terminal 증거가 아니며 signal-positive queue 뒤로 보류 |
| not probed | 0 | 현재 GitHub screening 저장소는 frozen probe가 모두 덮음 |

File-only 분류 결과는
[current-HEAD classification artifact](../experiments/phase2b-license-file-classification-2026-07-24.json)에
고정했다. 33 repositories 모두 full HEAD SHA와 license blob/content hash를 얻었고,
GitHub `NOASSERTION` 3개만 원문을 두 번 대조했다. 그 결과 MIT 2개와 PolyForm
Noncommercial 1개였으며 별도의 GitHub SPDX 1개는 GPL-3.0이었다. 이 관측으로 66건 중
64건만 다음 cheap metadata 단계로 전진한다.

따라서 expensive source/PR/parity 검토의 우선 queue는 691건이 아니라 **102건**
(pinned pass 2 + permissive signal 36 + file-only permissive 64)이다. 기존 copyleft 신호
2건과 새 GPL-3.0/PolyForm 신호 2건은 exact revision에서 빠르게 확인해 terminal 여부를
정하고, `none-observed` 585건은 삭제하거나
제외하지 않은 채 뒤로 미룬다. SWE-bench Multilingual 300건은 base revision만 기록된
상태에서 dataset card MIT가 upstream code의 use basis를 대신하지 않으므로, 41개 upstream
repository fetch 안에서 300개 exact base/tree와 path-scoped license를 별도로 확인했다.
그 결과 dataset terms와 exact base 300/300, upstream license 291/300이 통과했다. Frozen
allow-list 밖인 Terraform BUSL-1.1 5건, Redis RSALv2/SSPLv1 2건, jq `docs/` CC BY 3.0
2건은 `license-or-use-basis-unavailable`로 terminal 제외했다. 근거는
[`phase2b-swebench-license-terms-2026-07-24.json`](../experiments/phase2b-swebench-license-terms-2026-07-24.json),
적용 경계는
[`phase2b-swebench-license-terms-ledger-application-2026-07-24.json`](../experiments/phase2b-swebench-license-terms-ledger-application-2026-07-24.json)에 있다.
Root artifact만으로 끝내지 않고 모든 changed file의 ancestor directory도 재검사했다.
55개 행에서 61개 task-path artifact(고유 blob 14개)를 추가로 찾았고, symlink 6개는 exact
root target까지 해석했다. 모두 기존 허용 판정과 일치해 row decision은 변하지 않았다.
그 291개 license-pass exact tree의 leaf entry 684,580개도 frozen instruction-discovery
contract로 전수 검사했다. Exact `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`,
`CLAUDE.local.md`, `.claude/rules/**/*.md`와 대소문자 변형은 모두 0건이었다. 중앙 전체
scan과 97/98/96행의 세 disjoint shard가 candidate/revision/tree/entry count까지 일치했으므로
291건 모두 candidate-tree instruction parity를 통과했다. 이 결과는 global instruction
gate나 source semantics를 대신하지 않는다. 근거와 적용 경계는 각각
[`phase2b-swebench-instruction-parity-2026-07-24.json`](../experiments/phase2b-swebench-instruction-parity-2026-07-24.json),
[`phase2b-swebench-instruction-parity-ledger-application-2026-07-24.json`](../experiments/phase2b-swebench-instruction-parity-ledger-application-2026-07-24.json)에 있다.
공식 방법론만으로 직접 작성·비번역 여부를 추정하지 않고 291개 resolving PR에서 같은
repository의 source issue를 복원했다. 98/96/97행의 세 disjoint shard 모두 현재 issue
`title + LF + body + LF`와 pinned statement hash가 정확히 일치했고, 중앙 재검사도
line-ending 정규화나 trim 없이 291/291 일치했다. Pinned parquet은 Git LFS pointer blob,
LFS payload, 300-row canonical inventory hash를 분리해 검증했으며 raw statement·patch·issue
body는 public artifact에 넣지 않았다. 근거와 적용 경계는 각각
[`phase2b-swebench-native-source-fidelity-2026-07-24.json`](../experiments/phase2b-swebench-native-source-fidelity-2026-07-24.json),
[`phase2b-swebench-native-source-fidelity-ledger-application-2026-07-24.json`](../experiments/phase2b-swebench-native-source-fidelity-ledger-application-2026-07-24.json)에 있다.
기계적 shape signal은 의미 판정이 아니라 review 순서로만 사용했다. Public-safe
[`phase2b-swebench-semantic-triage-2026-07-24.json`](../experiments/phase2b-swebench-semantic-triage-2026-07-24.json)은
291행을 priority 28/33/73/157로 정렬할 뿐 `screening_updates`와 terminal 판정은 비워 둔다.
세 개의 disjoint 98/96/97행 검토를 중앙에서 정규화하고 민감 행을 다시 읽은
[`phase2b-swebench-semantic-review-2026-07-24.json`](../experiments/phase2b-swebench-semantic-review-2026-07-24.json)은
boundedness 291 pass, evaluator feasibility 290 pass / 1 unknown을 기록한다. 적용 artifact
[`phase2b-swebench-semantic-review-ledger-application-2026-07-24.json`](../experiments/phase2b-swebench-semantic-review-ledger-application-2026-07-24.json)은
해결된 field만 원장에 반영하고 Faker evaluator field를 `unknown`으로 보존한다. 역적용하면
pre-semantic ledger SHA-256이 정확히 복원되며 decision/exclusion과 967/146/17 집계는 변하지
않는다.

현재 순서는 다음과 같다.

1. file-only 66건의 현재 license 종류 분류는 완료됐다. Signal은 nonterminal로 유지한다.
2. signal-positive 106건의 linked solution, changed-file, test-touch metadata 수집은 완료됐다.
   결과는 eligible exact queue 27 / scope-review 18 / no-test-touch 57과 suspected-ineligible
   exact-confirm queue 4다.
3. rank 5의 31건 exact base와 pinned revision license 확인은 완료됐다. MIT 21,
   Apache-2.0 6은 pass, GPL-3.0 2, AGPL-3.0 1, exact-base use basis 부재 1은 fail이다.
4. Exact-tree instruction inventory 25건도 완료됐다. No-instruction 5, byte-equivalent
   symlink 3, explicit adapter 1은 pass했고, one-sided active instruction 16건은
   `instruction-parity-mismatch`로 제외했다.
5. Rank 7의 10건 의미 필터와 reproduction은 완료됐다. Translation-only 3건과
   multiple-coupled 1건을 제외했고, 여섯 survivor는 agent-free base-negative와
   solution-positive를 통과해 selected-for-task-authoring으로 이동했다.
6. solution-scope 18건 + MIT-at-base 반환 1건도 완료됐다. Source terminal 7, exact
   instruction-parity terminal 8, agent-free reproduction pass 4로 종결했다.
7. SWE-bench 300건의 pinned dataset terms, 300개 exact base/tree와 upstream license
   확인은 완료됐다. 291건은 screening 유지, 9건은 license terminal 제외다.
8. 291개 license-pass exact tree의 task-relevant instruction inventory도 완료됐다.
   Project instruction이 모두 부재해 parity 291/291 pass다.
9. 291개 parity-pass statement의 native-source fidelity도 완료됐다. Resolving PR에서 복원한
   현재 GitHub issue title/body와 291/291 exact hash match해 모두 pass다.
10. 291건의 single bounded task와 objective evaluator 의미 검토는 완료됐다. Boundedness는
    291 pass, evaluator feasibility는 290 pass / 1 unknown이며 terminal 제외는 없다.
11. 다음은 의미 gate를 통과한 290건의 isolation, evaluator hiding, fixture health,
    reproducibility와 resource budget 검토다. Faker 1건은 별도 semantic adjudication에 둔다.
12. no-test-touch 57건은 보류한다. Test 미접촉만으로 pass/fail하지 않는다.
13. signal-positive queue가 소진된 뒤에만 `none-observed` 행을 exact-revision 근거로
   재검토한다. classifier나 default branch 신호만으로 pass/fail 처리하지 않는다.
14. classifier 기반 license 근거가 남은 과거 판정도 계속 점검한다. `factlog #314`에서
   실제로 발견돼 정정했으므로 같은 시기 행에 남아 있을 수 있다.

Linked-solution 결과는
[prefilter artifact](../experiments/phase2b-linked-solution-prefilter-2026-07-24.json)에 고정했다.
106/106 issue HTML, 107/107 unique PR HTML과 `.diff`가 성공했고 full head revision과 각
content hash를 보존한다. Direct closing PR은 103건이 단일, 3건이 복수였다. Eligible 102건
중 단일 closing PR은 99건이며 test-touch 37 / no-test-touch 62다. Test-touch가 있어도
multiple-closing, PR body의 obvious multi-issue 신호, 또는 다른 priority PR commit set을
포함하는 stacked superset이면 scope-review로 보낸다. 더 작은 self-contained prefix PR은
후속 PR이 쌓였다는 이유만으로 보류하지 않는다. 최종 advance는 27건이다. `docs/specs/`와
`test_cases.md`를 실행 test로 잘못 센 초안 오탐은
Claude anomaly review와 주 검토자의 source-rule 대조로 제거했다. Prefilter route 자체는
`terminal_status=false`이며 당시 ledger 행을 바꾸지 않았다. 후속 rank 5 exact evidence가
생긴 뒤에만 네 행이 license terminal exclusion으로 바뀌었다.

Rank 5는 31/31 head·commit ancestry·single-parent base·changed-path set을 검증했다.
License pass 27건 중 broad release 1건은 scope review로 되돌려 26건이 남았고, GPL/AGPL
3건과 exact base에 use basis가 없는 `secure-doc #22`를 제외했다. Current HEAD가
PolyForm Noncommercial이던 `oh-my-customcode #1415`는 candidate base가 MIT였고, 반대로
current HEAD가 MIT이던 `secure-doc #22`는 candidate base에 license가 없었다. 이 두 반례
때문에 current-HEAD signal을 terminal로 승격하지 않는다. 여기에 SWE-bench exact/path
license 실패 9건을 더한 현재 license terminal exclusion은 총 **34건**이다.

Rank 7 상세 evidence는
[`phase2b-rank7-semantic-prefilter-2026-07-24.json`](../experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json),
[`phase2b-rank7-agent-free-reproduction-2026-07-24.json`](../experiments/phase2b-rank7-agent-free-reproduction-2026-07-24.json),
[`phase2b-rank7-ledger-application-2026-07-24.json`](../experiments/phase2b-rank7-ledger-application-2026-07-24.json)에
분리했다. 첫 artifact는 원문 hash와 source-semantic terminal 판정을, 둘째는 protected
control hash·exact tree·resource bucket을, 셋째는 pre/post ledger hash와 10개 mutation을
고정한다. `small-village #54`에서 solution test를 byte-identical control로 사용한 것은
screening evidence일 뿐 final evaluator 승인이 아니며, hosted 3-client 문장을 offline
invariant가 충분히 덮는지는 독립 validity reviewer가 다시 확인한다. 어느 단계에서도
candidate agent를 실행하거나 결과를 읽지 않았다.

후속 scope-review evidence는 source-semantic, exact solution segmentation, pinned license,
exact-tree instruction parity, survivor semantic/reproduction과 두 ledger-application 경계로
분리했다. 19건 중 source 7건과 parity 8건을 terminal 제외하고 4건을
selected-for-task-authoring으로 이동했다. 모바일 `B-TING #75`의 final evaluator는 screening의
rollback 구조 검사를 실제 mocked failure-and-restore behavior로 교체해야 한다.

`selected-for-task-authoring`은 현재 **17건**이다. 이는 candidate construction queue이지
final pilot task가 아니다. quota가 부족하면 번역이나 임의 분류로 채우지 않고 부족분을
그대로 보고하며, 60 tasks와 ko/en/mixed 각 20, category 각 12는 축소하지 않는다. 충족하지
못하면 **construction incomplete / pilot not authorized**로 보고한다. 상세 중단 상태와
근거는 [28차 handoff](adaptive-routing-progress.md#2026-07-24-28차-handoff--swe-bench-boundedness와-evaluator-feasibility-검토)에
고정했다. Cascade, exact-revision, parity, semantics/reproduction과 세대별
ledger-application invariants를 포함한 focused suite는 43 tests, 전체 suite는 296 tests가
통과했다. 28차 SWE-bench semantic review와 exact reverse invariant까지 포함한 최신 값은
focused 47 tests, 전체 suite 300 tests다.
