# Adaptive Routing 개선 작업 진행상황

> 마지막 갱신: 2026-07-19
> 상태: Phase -1/0/1과 Phase 2a v1/v2 paired smoke 완료, Phase 2b source screening 진행 중
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
- [x] Phase 2a versioned paired manifest/environment validation
- [x] deterministic balanced assignment와 independent exact-base checkout dry run
- [x] event-derived pair projection과 synthetic 2×2 aggregation
- [x] Phase 2a tooling 완료 후 전체 unit test 실행(200 tests)
- [x] 4-task manifest와 canonical/protected evaluator 사전 등록 및 negative control
- [x] explicit gate, CLI version pin, fresh control state, wall-time budget를 강제하는 paired runner
- [x] 실제 manifest validation과 agent-free 8-checkout dry run
- [x] fake-process 8-attempt/8-evaluator/48-event end-to-end 회귀 테스트
- [x] Phase 2a runner 완료 후 전체 unit test 실행(206 tests)
- [x] 실제 4-task/8-execution smoke와 48-event replay 완료
- [x] 8/8 reliability, 8/8 objective observation, evaluator artifact 무결성 확인
- [x] 결과 audit에서 `paired-plan-command` evaluator-contract 불일치 식별
- [x] smoke task 4개 결과를 현재 코드에 독립 검토 후 통합
- [x] non-mutating `paired plan`의 공개 `workspaces` contract와 dry-run path 일치 검증
- [x] replay exact status count와 plan JSON `cost_limit_usd` 입력 경로 추가
- [x] evaluator coverage의 사전 등록 pair 분모 및 secondary metric 결측 보고 추가
- [x] future paired lifecycle에 resource observation과 수정 파일 목록 기록
- [x] v1 historical replay를 유지하는 `paired-smoke-manifest-v2` parser
- [x] evaluator assertion inventory attestation과 task wording exact mapping preflight
- [x] task별 exact modified-file allowlist와 결측 보존 unexpected-file 집계
- [x] 23개 assertion mapping이 있는 v2 4-task rehearsal manifest 사전 등록
- [x] v2 exact-base negative control, plan/validate, agent-free 8-checkout dry-run
- [x] partial projection의 materialized-attempt 과대 집계 수정과 회귀 테스트
- [x] deterministic prefix/finalization/untouched-workspace를 검증하는 `paired resume`
- [x] v2 실제 8-attempt materialization, 48-event replay와 pause/resume audit
- [x] 7/8 objective observation, one-sided infrastructure failure와 unexpected-file 1건 공개
- [x] Phase 2b용 일반 manifest schema와 독립 task/evaluator construction gate 문서화
- [x] JSON/link/diff 검증과 전체 258 unit test 통과
- [x] source candidate ledger schema와 result-blind inclusion/exclusion rule 작성
- [x] local history 36개와 공식 English dataset 300개 전체 candidate inventory 및 hash/Git identity 검증
- [x] Korean-bearing GitHub fixed-query 411개 전체 snapshot과 deterministic 29-row linkage probe
- [x] 29개 원문 수동 분류, 27개 merged PR provenance 복원, 사전 규칙 위반 11개 제외
- [x] license 확인 4개 exact base/tree materialization, iOS/Xcode resource 불가 1개 제외
- [x] explicit multilingual fixed-query 신규 383개 snapshot과 deterministic 50-row 수동 review
- [x] candidate ledger 회귀 테스트 6개 추가
- [x] 확장 candidate ledger 반영 후 전체 264 unit test 완주 통과(2026-07-19)
- [x] exact base 확인 3개 screening 판정과 provisioning 원칙 기록(focused 7 tests, 전체 265 tests)
- [x] 정식 Draft 2020-12 validator(`jsonschema 4.26.0`, `/tmp` 격리 설치)로 ledger schema/instance 검증
- [x] Korean reviewed screening 15개 판정(3 제외 + 12 license 제외, 정정 2건)
- [x] `license-or-use-basis-unavailable` terminal 사유 amendment
- [x] 12행 license 증거 보완(recursive tree·README 5경로 전수 검사)
- [x] Frame B licensed-repository-first source frame 사전등록 문안
- [x] `GET /rate_limit`·`GET /licenses` snapshot 동결(L = 13)
- [ ] Stage 1 exact query 78개 목록 생성·동결 및 수집 승인 요청
- [ ] 기존 411 pool의 repository 단위 early filter(≤179 core 요청)
- [x] 4개 toolchain provisioned 재현 실측과 절차 문서화
- [x] resource bucket(`small`/`medium`) 정의와 첫 selected 2건
- [ ] explicit-language reviewed screening 28개 판정
- [ ] native Korean 20/English 20/mixed 20 task 후보 screening과 provenance ledger 동결
- [ ] 독립 evaluator 제작·validity review, assertion inventory와 negative control 완료
- [ ] 완성된 60-task manifest 검증·동결 및 별도 실행 승인 요청

### 2026-07-19 재개 handoff

이 handoff는 source construction 중단 지점만 기록한다. 원래 사전등록한
**60 tasks × 2 agents = 120 executions** variance/discordance/pipeline pilot은 변경하지
않는다. 60 tasks로 language×category 우월성을 확증하거나 winner를 선언하지 않는다.
task 실행, evaluator 제작·실행, agent 호출은 아직 승인·시작하지 않았다.

현재 ledger snapshot은 다음과 같다.

| 항목 | 현재 값 |
|---|---:|
| 전체 candidate | 1,130 |
| `screening` | 1,079 |
| `excluded` | 51 |
| `selected-for-task-authoring` | 0 |
| provisional language | Korean 56 / English 301 / mixed 22 / unassigned 751 |

provisional language/category는 60-task quota에 세지 않는다. Korean-bearing probe는
29개를 읽어 수동 판정과 license screening까지 마친 결과 **27개 제외·2개 screening**으로
남겼고, explicit multilingual probe는 50개를 읽어 22개 제외·28개 screening으로 남겼다.
Korean reviewed pool에서 `screening`으로 남은 것은 factlog와 swift-tui 둘뿐이며, 12개는
pinned base revision에 license artifact와 manifest 선언이 모두 없어
`license-or-use-basis-unavailable`로 제외했다. language 20/20/20과 category 각 12는
marginal quota이므로 이 편중을 3×5 cell 부족이나 category quota 실패로 해석하지 않는다. exact base/tree까지 실제로
materialize한 4개 중 iOS/CoreData row는 `xcodebuild`가 macOS 전용이라 Linux에서
provisioning으로도 재현할 수 없어 `resource-budget-exceeded`로 제외했다.

**eligibility는 screening host에 우연히 설치된 runtime 상태로 판정하지 않는다.** 그
기준은 이 머신의 우발적 tooling을 selection bias로 들여온다. Linux에서 재현 가능한
runtime/toolchain은 manifest freeze와 agent 실행 전에 격리된 immutable environment로
provisioning할 수 있으나, exact version과 전이 의존성 artifact hash 고정, 양쪽 agent의
byte-equivalent 환경, 실행 중 network 금지, agent-free base/negative/positive control
재현, 사전 resource bucket 내 설치·실행, environment epoch·fixture provenance 기록을
모두 충족하기 전에는 `reproducible_within_budget`을 `pass`로 두지 않는다.

base를 확인한 나머지 3개의 현재 판정은 다음과 같다.

| candidate | decision | 상태 |
|---|---|---|
| `ghko-SeoyunL--factlog-academic-issue-314` | `screening` | 11개 중 10개 `pass`, `reproducible_within_budget` 1개만 `unknown` |
| `ghko-Chigo55--Docker-Compose-issue-38` | `excluded` | `subjective-only-evaluation` 단독 사유 |
| `ghko-minacle--swift-tui-issue-18` | `screening` | Linux 재현성·resource 검증 대기 |

`swift-tui`는 runtime 미설치만으로 제외하지 않았다. `Darwin`/`Glibc` 조건부 import,
`Package.resolved`의 exact revision pin 6개, 최소 배포 타겟 선언일 뿐인
`platforms: [.macOS(.v15)]`, Linux용 Swift 6.3.3 배포가 근거다. 다만 issue 저자가
macOS의 Apple Swift 6.4-dev에서 검증했으므로 Linux 재현은 미증명이며, 측정 자체가
screening budget을 넘으면 고정 기준을 기록하고 `resource-budget-exceeded`로 제외할 수
있다. 상세 사유와 고정 기준은
[source candidate ledger](paired-pilot-candidate-ledger.md)에 있다.

검증 상태를 구분해서 읽어야 한다.

- ledger 확장 전 전체 suite는 262 tests까지 통과했다.
- 중단됐던 264 tests는 2026-07-19에 **완주해 통과했다.** 이번 screening 판정을 고정하는
  회귀 테스트를 더해 현재 기준은 **265 tests 통과**이며, focused ledger tests는 **7개**가
  통과한다.
- local 36, SWE-bench Multilingual 300, Korean snapshot 411, explicit multilingual
  snapshot 387(기존 pool overlap 4), linked PR 27과 base tree 4의 source/hash 의미
  검증을 수행했다.
- JSON Schema는 두 단계로 검증했다. 시스템의 `jsonschema 3.2.0`은 Draft 2020-12
  metaschema를 인식하지 못해 **Draft7 fallback**으로만 검증했으므로 그 결과를 단독으로
  "Draft 2020-12 통과"라고 기록하지 않았다. 이후 `/tmp`의 격리 설치(`jsonschema 4.26.0`,
  프로젝트·전역 미변경)에서 `Draft202012Validator`로 **schema 자체의 metaschema 적합성과
  ledger instance(1,130 candidates)를 모두 검증해 통과**했다. `paired-pilot-manifest-v1`
  schema도 같은 metaschema 검사를 통과했다.
- 두 결과가 일치한 이유도 확인했다. ledger schema는 Draft7이 조용히 무시하는 2020-12
  전용 키워드(`prefixItems`, `unevaluatedProperties`, `unevaluatedItems`,
  `dependentSchemas`, `dependentRequired`, `minContains`/`maxContains`, `$dynamicRef`)를
  전혀 쓰지 않고 array-form `items`도 없어 두 draft의 공통 부분집합 안에 있다. 따라서
  이전 fallback 결과가 vacuous하지 않았음이 사후 확인됐다. 이 성질은 schema를 고칠 때
  깨질 수 있으므로 keyword를 추가하면 정식 validator로 다시 검증한다.

### 2026-07-19 2차 handoff — source screening 중단 지점

Korean reviewed 15개 판정과 Frame B 사전등록까지 마쳤다. **candidate 수집은 아직
시작하지 않았다.** 60 tasks × 2 agents = 120 executions 원안과 ko/en/mixed 각 20,
category 각 12는 변경하지 않았고 `selected`는 0이다.

| 항목 | 값 |
|---|---:|
| 전체 candidate | 1,130 |
| `screening` | 1,079 |
| `excluded` | 51 |
| `selected-for-task-authoring` | 0 |
| Korean reviewed pool | 제외 27 / screening 2 |

Korean reviewed pool에서 `screening`으로 남은 것은 `factlog #314`(11개 중 10개 `pass`,
`reproducible_within_budget`만 `unknown`)와 `swift-tui #18`(Linux 재현성·resource 검증
대기) **둘뿐이다.** 12개는 pinned revision의 다섯 경로(LICENSE/COPYING/NOTICE/manifest/
README)를 모두 검사한 `exact-revision-no-license-basis`로 제외했다. 이 pool은 개인·팀·
부트캠프 저장소가 많아 SPDX license 부재가 지배적 탈락 사유이며, 미probe 382개도 같은
분포일 가능성이 높다.

동결한 사전등록 artifact:

- [`experiments/frameb-licenses-snapshot-2026-07-19.json`](../experiments/frameb-licenses-snapshot-2026-07-19.json)
  — `GET /licenses` 전체 13개, canonical JSON SHA-256, `GET /rate_limit` snapshot,
  `L = 13`과 Stage 1 최대 요청 `6 × 13 = 78`.

요청 상한은 bucket별로 다르다. core는 시간당 60, search는 분당 10이며 서로 다른
bucket이므로 단일 한도로 계산하지 않는다.

| 단계 | bucket | 요청 |
|---|---|---:|
| Stage 1 (`6 × L`) | search | 78 |
| Stage 2 (`min(D, 150)`) | search | ≤ 150 |
| 기존 pool early filter | core | ≤ 179 |

### 2026-07-19 3차 handoff — 첫 selected 2건까지

Frame B 사전등록, license 조기 필터 전수, 후보 심사, provisioned 재현 실측을 마쳤다.
**`selected`가 처음으로 0을 벗어나 2건이 됐다.** agent 실행·evaluator 저술·60-task manifest는
여전히 미착수이며 승인되지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 candidate | 1,130 |
| `screening` | 1,066 |
| `excluded` | 62 |
| **`selected-for-task-authoring`** | **2** |

#### selected 2건 (11/11)

| candidate | 언어/범주 | base tree | 라이선스 | bucket |
|---|---|---|---|---|
| `ghmix-semantic-reasoning--factlog-issue-26` | ko / debugging | `12a8b1a1` | Apache-2.0 | `small` (2초) |
| `ghmix-joshua-jingu-lee--ante-issue-2349` | ko / debugging | `c9df9724` | MIT | `small` (<1초) |

둘 다 digest 고정 toolchain으로 base·negative·positive control을 agent 없이 재현했다. 상세
절차와 수치는 [provisioned-environment 재현 절차](provisioned-reproduction.md)와
[측정 artifact](../experiments/phase2b-provisioning-measurements-2026-07-19.json)에 있다.

#### 근접 후보와 각각의 정확한 장애물

| candidate | pass | 남은 것과 이유 |
|---|---|---|
| `ghko-SeoyunL--factlog-academic-issue-314` | 10/11 | `reproducible_within_budget` 미실측. Python 3.11 + `pyrewire`. 같은 계열인 `factlog #26`이 pyrewire 없이도 evaluator가 도는 것을 확인했으므로 재현 비용은 낮을 가능성이 크다 |
| `ghmix-hskim-solv--BidMate-DocAgent-issue-1152` | 10/11 | `reproducible_within_budget` 미실측. Python(버전 미확인), 정답 PR이 `tests/test_doc_links.py`를 수정하므로 PR 시점 재구성 가능 |
| `ghmix-YSbookcase--TimePilot-issue-62` | 10/11 | 정답 PR에 **테스트가 0개**라 재구성할 gold test가 없다. evaluator를 새로 저술해야 하며 이는 §3 역할 분리 대상 — task-source 판정을 한 역할이 같은 맥락에서 채점 기준을 쓰면 독립 construction이 아니다 |
| `ghko-minacle--swift-tui-issue-18` | 6/11 | 상류 테스트를 evaluator로 **쓸 수 없음이 실측으로 확인**됐다. PR 테스트 hunk를 base에 적용하면 compile error 171개이며, `RenderedTextInputAnchor` 등 이슈가 명명하지 않은 내부 타입을 요구한다 |

#### 이번 세션에서 확정된 규칙

- **linked PR 선정**: merged이고, **이 이슈 번호를 실제로 참조**하며, **릴리스 자동화 PR이
  아니어야** 한다. "timeline의 첫 merged PR"은 두 번 틀렸다 — 릴리스 PR과 다른 이슈의 PR.
- **base tree hash 출처**: `git rev-parse HEAD^{tree}`. `GET /git/trees/{commit_sha}`는 입력
  SHA를 되돌려주므로 tree hash로 쓰면 안 된다(3개 행이 이 오류로 들어갔다 정정됨).
- **license 판정**: pinned revision의 artifact를 직접 읽는다. classifier는 우선순위 신호일
  뿐이며, selected 5건 후보 전부 classifier가 `spdx=None`이었는데 실제로는 MIT/Apache였다.
- **resource bucket**: evaluator wall time 기준 `small` ≤ 30초, `medium` ≤ 120초(cold 측정).
  manifest schema에 용량 필드가 없으므로 디스크로 판정하지 않는다.
- **objective evaluator 판정 기준**: 상류 테스트의 **존재**가 아니라 그 테스트가 **과제 문구가
  진술한 수준**을 검사하는지다.

#### API 없이 되는 경로 (core 한도 밖)

core는 미인증 시간당 60이라 쉽게 소진된다. 다음은 한도를 쓰지 않는다.

```text
raw.githubusercontent.com/{repo}/{ref}/{path}     파일 내용 (임의 ref 가능)
github.com/{repo}/pull/{n}.diff                   PR unified diff
github.com/{repo}/commit/{short}.patch            첫 줄에서 full SHA 해석
git fetch --depth 1 origin {full_sha}             base materialize (짧은 SHA는 안 받음)
```

#### 휘발성 artifact와 재구성

`/tmp` 아래는 세션과 함께 사라진다. 재구성을 가능하게 하는 것은 기록된 identity다.

| 경로 | 내용 | 재구성 근거 |
|---|---|---|
| `/tmp/claude-1000/py311`, `py313` | CPython 3.11.15 / 3.13.14 | 측정 artifact의 digest |
| `/tmp/claude-1000/dotnet` | .NET SDK 8.0.423 | `dotnet-install.sh --channel 8.0` |
| `/tmp/claude-1000/swift` | Swift 6.3.3 ubuntu22.04 | download.swift.org URL |
| `/tmp/claude-1000/repro/*` | base checkout과 control 사본 | ledger의 base_revision |
| `/tmp/claude-1000/frameB/*` | license probe 원자료 | 결론은 probe artifact에 반영됨 |
| `/tmp/phase2b-schema-lib` | jsonschema 4.26.0 | Draft 2020-12 검증용 재설치 필요 |

#### 다음에 할 수 있는 것

1. `factlog #314`와 `BidMate #1152`의 provisioned 재현 — 절차가 이미 문서화돼 있고 상류
   테스트도 있으므로 가장 짧은 경로다. 통과하면 selected 4건.
2. `TimePilot`·`swift-tui`의 **역할 분리된 evaluator 저술** — 별도 역할/세션이 task 문구만
   보고 작성해야 한다.
3. explicit-language reviewed 나머지 15개와 Korean reviewed 미판정분 심사.
4. Frame B Stage 1 수집 — exact query 78개(6 KO_TERM × 13 license) 목록 동결과 별도 승인 필요.

quota는 ko 2/20이고 selected 2건이 모두 `debugging`이다. marginal quota이므로 현 단계에서
문제로 보지 않지만, category 편중은 기록해 둔다.

### 2026-07-19 4차 handoff — Frame B 측정과 기계적 사전필터까지

Frame B를 수집·측정했고, 그 결과로 **수율 병목이 소스가 아니라 파이프라인 순서**임을
확인했다. 기계적 사전필터를 도입해 수동 읽기 대상을 141행에서 36행으로 줄였고 그중 30행을
판정했다. agent 실행·evaluator 저술·60-task manifest는 여전히 미착수다.

| 항목 | 값 |
|---|---:|
| `screening` | 1,054 |
| `excluded` | 74 |
| `selected-for-task-authoring` | **2** |

#### Frame B의 결론: 수집은 했으나 확장하지 않는다

Stage 1은 78 query로 저장소 **1,855개**를 모았고 permissive 한정으로 **1,055개**가 eligible이다
([query 동결](../experiments/frameb-stage1-queries-2026-07-19.json)). 그러나 Stage 2를 seed
순서 앞 25개로 측정하니 **closed+linked 이슈를 가진 저장소가 1개뿐**이었다.

원인은 Stage 1이 "한국어 단어 + license + 최근 push"만 걸렀고 **이슈 활동 조건이 없었다**는
것이다. repo-first로 모으면 이슈를 안 쓰는 저장소가 대량으로 들어온다. 기존 pool은
issue-first라 모든 행이 실제 이슈다.

**Frame B는 폐기가 아니라 보류다.** 수집 결과는 보존하되 Stage 2를 확장하지 않는다. 다시 쓰려면
issue 활동을 Stage 1 조건에 넣어 재설계해야 하고, 그러면 기존 Korean pool 수집 방식과 사실상
같아진다.

#### 기계적 사전필터 — 도입 이유와 한계

수동 읽기가 파이프라인의 비싼 단계인데 앞에 있었다. selected에 도달한 후보들은 모두 정답
PR이 테스트 파일을 건드렸고, 그 성질은 issue HTML과 `.diff`로 **API 한도 없이** 판정된다.

| | |
|---|---:|
| license 있는 저장소의 미심사 후보 | 141 |
| → 필터 통과 | **36** |
| 절약된 수동 읽기 | 105 |

**그러나 예측자로서의 정밀도는 낮다.** 필터를 통과한 30행을 읽어 9행을 제외했고, 그 9행 전부가
필터를 통과한 것들이다. "정답 PR이 테스트를 건드린다"는 **평가 가능성을 보장하지 않는다** —
`swift-tui #18`은 테스트 13개를 가지고도 내부 API를 검사해 실격이다. 필터는 우선순위 도구이지
판정이 아니다.

#### license 범위 축소와 그 적용 누락

§4.3이 eligible을 permissive 7종으로 한정했는데, **141행을 고를 때 적용하지 않았다.** 조건이
"라이선스가 있다"였지 "permissive다"가 아니었다. 종류 미상 23건의 LICENSE를 읽어 3건을
제외했다.

- `digitie/kor-travel-geo` — GPL-3.0
- `cops-and-robbers-FE` — Source-Available License v1.5 (비상업 제한)
- `SeniorAILab/eldercare-fall-ai` — **All rights reserved**, 본문이 "not open-source software.
  No license is granted to use, copy, modify"라고 명시

**라이선스 파일이 있다는 것과 사용 권한이 있다는 것은 다르다.** 파일 존재만으로 통과시켰다면
세 번째를 그대로 썼을 것이다.

이 3건은 base revision이 없어 **default branch 기준** 판정이다. 기존 12건(pinned revision 기준)과
증거 등급이 다르므로 회귀 테스트가 둘을 구분하도록 고쳤다. **default branch 증거는 제외에만
쓰고 통과 근거로는 쓰지 않는다.**

#### 남은 24행과 유망 후보

필터를 통과해 아직 `screening`인 24행 중, 문구가 구체적이고 결정적 판정이 가능해 보이는 것:

| 후보 | 성격 |
|---|---|
| `ohah/zntc #4564 · #4563 · #4553` | 번들러 cross-chunk 심볼·TDZ shadowing·manualChunks. 근본 원인이 코드 라인 수준 |
| `factlog-academic #342` | `validate_query:142` 가드 누락 → JSONDecodeError, 재현 실측 포함 |
| `SeokRae/blog #12` | 한국어 검색 0건 — lunr trimmer의 `\W`가 한글 토큰을 잘라냄. node 실증표 포함 |
| `nixos-config #918` | 정규식 어순 의존 — `100줄 제한`은 통과, `제한 100줄`은 차단 |
| `anygarden #512` | 지난 날짜 타임스탬프, 출력 형식 정확히 명시 |
| `AgentDesk #4606` | 큐 리액션 enum 매핑 정확히 명시 |

`blog #12`와 `nixos-config #918`은 **한국어 자체가 버그의 원인**이라 번역으로 성립하지 않는
native Korean task다. quota 관점에서 가치가 크다.

#### 이 세션에서 확정된 추가 규칙

- **API 밖 경로로 대부분 처리 가능**: issue HTML(linked PR), `pull/{n}.diff`(변경 파일),
  `commit/{short}.patch`(full SHA), `raw`(파일 내용), `git fetch`(base). core는 저장소
  metadata와 timeline에만 필요하다.
- **분류기는 종결 근거가 아니다**: selected 5건 후보 전부 classifier가 `spdx=None`이었으나
  pinned revision에는 MIT/Apache 전문이 있었다.
- **비싼 단계를 파이프라인 뒤로**: 수율이 낮아 보이면 소스를 바꾸기 전에 처리 순서를 먼저
  본다. 2,370건이라는 추정은 사람 읽기를 앞에 둔 계산이었다.

#### 다음에 할 수 있는 것

1. 남은 24행의 base 확정과 나머지 rule 판정 — 유망 6건부터
2. `factlog #314`·`BidMate #1152`(각 10/11)의 provisioned 재현 — 절차는 문서화돼 있다
3. `TimePilot`·`swift-tui`의 evaluator 저술 — §3 역할 분리 대상이라 별도 역할 필요
4. 제공자 데이터 취급 확인 — 60-task 실행 승인 전 필수 (§4.3에 미확인으로 기록됨)

다음 세션의 순서는 고정한다.

0. 아래 절차 전에 이 handoff와 [사전등록 §4.4](paired-pilot-preregistration.md)를 읽는다.
   Stage 1/2 수집, 기존 pool의 179개 조회, task authoring, evaluator/agent 실행은
   **아직 승인되지 않았다.** 각각 별도 승인을 받는다.

1. `git status --short --branch`로 이 handoff commit과 사용자 소유의 별도 untracked
   파일을 구분한다.
2. 아래 focused test를 다시 실행한다(현재 7개).
   `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_phase2b_candidate_ledger.py' -v`
3. localhost socket을 쓰는 기존 `test_web_ui` 3개가 허용되는 환경에서 아래 전체
   suite를 실행한다(현재 265개).
   `PYTHONPATH=src python3 -m unittest discover -s tests -v`
4. `/tmp` source artifact가 사라졌다면 ledger의 고정 query·cutoff·dataset revision으로
   snapshot을 다시 받아 source/hash 의미 검증을 재실행한다. 임시 artifact 자체를
   provenance로 간주하지 않는다. `/tmp/phase2b-base-*`는 외부 후보의 solution 이전
   commit/tree 검증용 임시 partial fetch이며 working tree/HEAD가 없을 수 있고, 이
   저장소의 복사본이나 작업 workspace가 아니다. 여기에 commit이나 push를 하지 않는다.
5. schema 또는 ledger schema의 keyword를 바꿨다면 정식 Draft 2020-12 validator로 다시
   검증한다. 시스템 `jsonschema 3.2.0`은 Draft7로 fallback하므로 이 검증에 쓰지 않고,
   `/tmp` 격리 설치를 사용하며 프로젝트나 전역에 dependency를 추가하지 않는다. 도구
   획득에 network 승인이 필요하면 먼저 보고한다. 2026-07-19 기준 검증은 통과했다.
6. Korean reviewed 15개와 exact base 3개는 판정을 마쳤다. 다음 작업은 순서대로
   ① Frame B Stage 1의 exact query 78개(6 KO_TERM × 13 license) 목록을 생성해 문서에
   동결하고 수집 승인을 요청, ② 기존 411 pool을 repository ID로 dedup해 early filter
   적용(≤179 core 요청, 동일 repository 재요청 금지, classifier 결과는 우선순위
   신호일 뿐 terminal 판정 아님), ③ explicit-language reviewed 28개 판정이다.
7. 11개 inclusion rule이 전부 `pass`가 되기 전에는 어떤 row도 `selected`로 바꾸지
   않는다. 부족 quota를 번역이나 임의 분류로 채우지 않는다. 60 tasks × 2 agents =
   120 executions 원안과 ko/en/mixed 각 20, category 각 12는 그대로 유지하며 현재
   `selected`는 0이다. 충족하지 못하면 축소 실행하지 않고
   **construction incomplete / pilot not authorized**로 보고한다.
8. 인증 토큰을 쓰지 않는다. 저장된 credential을 탐색하거나 출력하지 않는다. 응답의
   `x-ratelimit-resource`/`remaining`/`reset`/`retry-after`를 따르고 403/429 시 reset
   전에 재요청하지 않는다.
9. Frame D(조직 frame)는 열지 않는다. Frame C(native task authoring)는 Frame B의 실제
   수율을 확인할 때까지 보류한다.

재개 시에도 사용자 요청 없이 60-task 설계를 바꾸거나 agent/evaluator/task 실행,
production traffic 탐색, 외부 push를 시작하지 않는다. evaluator author와 validity
reviewer 분리는 이후 construction gate에서 유지한다.

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

### Phase 2a — paired smoke tooling/runner (실제 smoke 완료)

agent-free 검증 뒤 실제 agent 8회를 실행해 다음 control path를 검증했다.

- versioned paired manifest와 task/evaluator/base revision schema validation;
- 동일 clean base에서 격리 workspace A/B 생성과 base hash 비교;
- seed 기반 agent 실행 순서 배정과 pair/task/attempt ID 고정;
- 양쪽에 동일한 외부 evaluator artifact/version/hash 적용;
- `paired` cohort, one-sided failure, incomplete pair projection;
- 실행 없는 synthetic 2×2 결과가 수동 집계와 같은지 검증;
- 희소 stratum, CI 미구현, target workload weight 부재를 promotion blocker로 유지.
- 사전 등록 4-task manifest, canonical evaluator source와 외부 0444 protected copy;
- explicit gate, installed CLI version pin, fresh workspace/control directory와
  agent/evaluator count 및 wall-time budget guard;
- 인프라 또는 evaluator error/timeout 뒤 finalized partial log를 남기고 즉시 pause.

4개 low-risk task, 보호 objective evaluator와 resource budget은 결과를 보기 전에
manifest로 사전 등록했고, evaluator negative control, `paired validate`, agent-free
`paired dry-run` 뒤 실제 smoke를 완료했다. 결과는 pass/pass 3쌍과 Claude fail/Codex
pass 1쌍이지만, 후자는 task에 명시되지 않은 JSON key를 evaluator가 요구한 contract
불일치가 있어 agent 비교 근거로 쓰지 않는다. smoke가 찾은 4개 유지보수 변경과
secondary metric reporting을 통합했고, 다음 v2 schema에는 evaluator assertion/task
wording의 사전 coverage review와 modified-file allowlist를 필수화했다. 이 schema도
Phase 2a의 4-task smoke 전용이다. v2 4-task 계약 rehearsal은 agent-free preflight와
실제 8-attempt materialization까지 마쳤다. Claude session quota로 한 행의 quality가
missing이 되었지만 해당 행을 제외하거나 0으로 바꾸지 않았다. runner는 3개 finalized
attempt에서 pause한 뒤 exact prefix와 untouched suffix를 검증하고 나머지 5개만 재개했다.
최종 objective coverage는 attempt 7/8, pair 3/4이며 task allowlist 밖 문서 수정 한 건도
그대로 보고했다. 다음 gate는 60-task pilot용 일반 schema와 task/evaluator construction
workflow를 별도로 설계하는 것이다.

### Phase 2b 이후

- smoke 전용 v2를 확장하지 않고 일반 `paired-pilot-manifest-v1` schema를 사용;
- task author, evaluator author, validity reviewer를 분리하고 결과를 보지 않은 상태에서
  provenance, assertion inventory, negative control과 exact artifact hash를 동결;
- native Korean 20/English 20/mixed 20의 60-task manifest를 agent-free 검증한 뒤에만
  별도 승인을 받아 120-execution paired pilot 실행;
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

그 다음 이 문서의 “지금 작업 중”에서 첫 미완료 항목을 선택한다. Phase -1/0/1과
Phase 2a v1/v2 smoke는 완료됐으므로
[Phase 2b pilot 사전등록 계약](paired-pilot-preregistration.md)에 따라 task provenance
ledger와 독립 evaluator construction부터 진행한다. 사용자 요청 없이 production
traffic 탐색, 실제 120회 agent 실행, 외부 push를 시작하지 않는다.

## 9. 작업상 주의사항

- 2026-07-18 중단 시점의 `docs/adaptive-routing-v2.md` 변경은 Phase 2b의 다음 gate만
  고친 작은 diff였고, 문서 동기화 때 보존했다.
- 현재 branch는 `main`; 이 문서 작성 시작 시 `origin/main`과 같은 위치였다.
- 설계 문서 작성 당시 별도 shell 변경을 포함한 136 tests가 통과했다. Phase -1
  기준선은 152 tests, Phase 0은 161 tests, Phase 1은 191 tests, Phase 2a tooling은
  200 tests였다. v1/v2 smoke와 Phase 2b construction 계약 동기화 뒤 258 tests,
  최초 candidate ledger 뒤 262 tests가 통과했다. 현재 확장 ledger의 264-test 전체
  실행은 2026-07-19에 완주해 통과했고, 이번 screening 회귀 테스트를 더해 265 tests가
  통과한다.
- 연구 링크는 외부 자료이며 최신 preprint 상태가 바뀔 수 있다.
- KB/Wiki prior는 설계 힌트이지 ground truth가 아니다. 현재 코드로 확인한 사실만
  구현 진단으로 기록했다.
- commit/push는 별도 사용자 요청이 있을 때 한다. 문서 동기화 계속 요청은 로컬
  commit 범위로 해석하되 외부 push는 별도 승인 없이는 하지 않는다.

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
| 2026-07-18 | smoke schema와 pilot schema 분리 | v2의 고정 4-task 계약을 60-task 실행에 암묵적으로 확대하지 않음 |
| 2026-07-18 | task/evaluator/reviewer 역할 분리 | evaluator leakage와 결과를 본 뒤 기준 변경을 차단 |
| 2026-07-19 | screening host의 설치 상태를 eligibility로 쓰지 않음 | 머신의 우발적 tooling이 그대로 selection bias가 됨 |
| 2026-07-19 | Linux 재현 가능 runtime은 조건부 provisioning 허용 | 조건 미검증 상태에서는 `reproducible_within_budget`을 `pass`로 두지 않음 |
| 2026-07-19 | 산문 산출물 task는 `subjective-only-evaluation`으로 제외 | 동일하게 유효한 문구가 다수라 병합 산문을 exact golden으로 강제할 수 없음 |
| 2026-07-19 | `license-or-use-basis-unavailable` terminal 사유 추가 | 필수 inclusion criterion에 대응 exclusion이 없어 충족 불가 후보가 무기한 screening에 남던 schema 누락 |
| 2026-07-19 | license는 exact pinned revision artifact로만 판정 | classifier 추정·default branch 소급·public 사실 자체를 use basis로 쓰지 않음 |
| 2026-07-19 | language/category quota는 marginal로 해석 | 특정 pool의 category 편중을 3×5 cell 부족이나 전체 quota 실패로 오독하지 않음 |
| 2026-07-19 | licensed-repository-first Frame B 사전등록 (result-blind) | agent 결과와 무관한 eligibility 실패(license 근거 부재)가 근거이며, 기존 pool과 제외 row는 감사 위해 보존 |
| 2026-07-19 | license 상태를 4단계로 분리 | classifier 결과를 terminal 판정으로 쓰지 않기 위함. 이미 제외한 12행은 README/하위 경로 미검사라 증거 보완 필요 |
| 2026-07-19 | license keyword를 `GET /licenses` 전체 목록으로 고정 | 임의 allowlist는 license type에 따른 불필요한 source selection을 만듦 |
| 2026-07-19 | Frame D 미개방, Frame C 보류 | D는 객관적 외부 조직 목록 부재, C는 B 수율 확인 전 source-construction confounding 위험 |

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
