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
| SWE-bench Multilingual `2b7aced…` default/test 전체 | 300 | screening 300 | English-only instruction, 공개 benchmark 노출, upstream 재현 미검증 |
| GitHub Korean-bearing fixed-query snapshot | 411 | screening 371, excluded 39, selected-for-task-authoring 1 | query별 최신 100개 cap, 29개 초기 수동 review와 별도 contextual screening 3개 |
| GitHub explicit multilingual fixed-query snapshot | 383 | screening 335, excluded 45, selected-for-task-authoring 3 | 전체 query unique 387개 중 기존 pool과 겹친 4개를 중복 제거, 50개 deterministic review와 별도 contextual screening 3개 |

각 pool에는 열거한 원자료 identity의 SHA-256을 기록했다. 외부 pool은 원문,
solution patch, source test patch를 ledger에 복제하지 않고 instance별 SHA-256만 남겼다.
dataset의 300 rows와 41 repository를 편의 표본으로 줄이지 않았다. GitHub pool도 고정된
첫 다섯 query가 반환한 500 rows를 URL로 중복 제거한 411개 전부를 보존했다. 명시적
multilingual query 다섯 개도 500 rows/387 unique를 보존하고, 기존 pool과 겹친 4개를
candidate 중복 없이 연결해 신규 383개를 추가했다. instance-level
screening 전에는 어느 row도 quota에 세지 않는다.

| 상태 | 개수 | 의미 |
|---|---:|---|
| `screening` | 1,040 | native 언어, evaluator 가능성, license, instruction parity, 격리·예산 중 하나 이상을 아직 독립 판정하지 않음 |
| `excluded` | 86 | local 2개, Korean-bearing pool 39개, explicit multilingual pool 45개 |
| `selected-for-task-authoring` | 4 | 12개 inclusion rule을 모두 `pass`한 construction queue 후보; final pilot task가 아님 |

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
제외했다. 이후 수동 판정, license screening, instruction parity 판정을 거쳐 29개 중
**27개가 제외**됐고 `swift-tui #18` 하나는 `screening`, `factlog-academic #314`는
`selected-for-task-authoring`이다. 제외 사유는 private·빈 명세,
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

### 4.2 exact base가 확인된 행의 현재 상태

`exact_base_resolvable`이 `pass`인 행은 **55개**다. 그중 35개는
`aao-local-history-through-0e32241` pool의 이 저장소 자신의 commit이라 base가 자명하게
해소되며(그중 1개는 Phase 2a smoke에 이미 쓰여 `previous-paired-task-reuse`로 제외),
독립 판정이 필요한 것은 **외부 후보 20개**다. 아래는 그 20개다.

| candidate | decision | pass | 남은 것 |
|---|---|---:|---|
| `ghmix-semantic-reasoning--factlog-issue-26` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-joshua-jingu-lee--ante-issue-2349` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-e7217--anygarden-issue-512` | `selected-for-task-authoring` | 12/12 | — |
| `ghko-SeoyunL--factlog-academic-issue-314` | `selected-for-task-authoring` | 12/12 | — |
| `ghmix-hskim-solv--BidMate-DocAgent-issue-1152` | `excluded` | 11/12 | `instruction-parity-mismatch` |
| `ghmix-YSbookcase--TimePilot-issue-62` | `screening` | 10/12 | evaluator 저술·재현 미완료, instruction parity 미판정 |
| `ghko-minacle--swift-tui-issue-18` | `screening` | 6/12 | 상류 테스트를 evaluator로 쓸 수 없음이 실측 확인됨; instruction parity 미판정 |
| `ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406` | `screening` | 6/12 | exact base·MIT·source evaluator feasibility 확인; instruction parity semantic delivery 미판정 |
| `ghko-SeoyunL--factlog-academic-issue-342` | `screening` | 5/12 | instruction parity 통과, 나머지 미심사 |
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

어떤 candidate도 default-branch prevalence row로 판정하지 않았다. exact pinned inventory가
있는 14개만 판정해 pass 5 / fail 9이고, 나머지는 `unknown`이다. `Docker-Compose #38`도
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

`swift-tui #18`은 runtime 미설치만으로 제외하지 않았고, Linux 재현 자체는 실제로
가능했다 — Swift 6.3.3으로 빌드와 1,064개 테스트가 모두 통과했다(`medium`, 90초).
`Darwin`/`Glibc` 조건부 import, `Package.resolved`의 exact revision pin 6개,
최소 배포 타겟 선언일 뿐인 `platforms: [.macOS(.v15)]`가 그 근거였다.

**막힌 지점은 재현이 아니라 evaluator였다.** 상류 테스트를 evaluator로 쓸 수 없음이
실측으로 확인됐다 — PR의 테스트 hunk를 base에 적용하면 compile error 171개이고,
`RenderedTextInputAnchor` 등 **이슈가 명명하지 않은 내부 타입**을 요구한다. 즉 테스트가
과제 문구가 진술한 수준이 아니라 구현 내부를 검사한다. 테스트 파일 13개를 가지고도
실격이라는 점에서, "정답 PR이 테스트를 건드린다"는 신호가 평가 가능성을 보장하지 않음을
보여주는 사례다. 병합 solution의 31 files(+1421/−1083)와 source-breaking 성격은
`single_bounded_task` 실패 입증이 아니라 task authoring과 allowlist 범위용 flag로만
기록했다. 남은 경로는 역할이 분리된 evaluator 저술이며 §3의 분리 요건을 따른다.

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
`factlog-academic #342`의 `@AGENTS.md` import는 parity만 `pass`이며 나머지 rule이
`unknown`이라 `screening`을 유지한다.

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
현재 합계 57 Korean/301 English/22 mixed이고 construction queue의 language marginal은
ko 4 / en 0 / mixed 0이다.

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
exact-base-only parity 판정, global gate와 contextual screening 경계를 고정하며 **16 tests가
통과했다.** 전체 suite는 Web UI와 전용 queue 제거 뒤 **267 tests가 통과했다.**

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

현재 순서는 다음과 같다.

1. 사전필터를 통과했고 아직 base를 읽지 않은 행의 linked PR·base/tree materialization과
   pinned revision license 판정. **parity 측정과 무관하게 진행할 수 있다.**
2. base가 확정된 행의 나머지 rule 판정. 이 단계에서 대부분 instruction parity에 걸리므로
   §4.2의 parity 기준을 함께 본다.
3. exact pinned tree의 전체 active project-instruction path를 inventory하고 별도
   `instruction-parity` rule 판정. default-branch prevalence는 판정에 쓰지 않는다.
4. explicit-language reviewed 나머지 심사.
5. classifier 기반 license 근거가 남은 행 점검. `factlog #314`에서 실제로 발견돼
   정정했으므로 같은 시기 행에 남아 있을 수 있다.

`selected-for-task-authoring`은 현재 **4건**이다. 이는 candidate construction queue이지
final pilot task가 아니다. quota가 부족하면 번역이나 임의 분류로 채우지 않고 부족분을
그대로 보고하며, 60 tasks와 ko/en/mixed 각 20, category 각 12는 축소하지 않는다. 충족하지
못하면 **construction incomplete / pilot not authorized**로 보고한다. 상세 중단 상태와
근거는 [6차 handoff](adaptive-routing-progress.md#2026-07-22-6차-handoff--codex-discovery와-instruction-parity-v11)에
고정했다.
