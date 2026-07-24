# Adaptive Routing 개선 작업 진행상황

> 마지막 갱신: 2026-07-24
> 상태: Phase -1/0/1과 Phase 2a v1/v2 paired smoke 완료, Phase 2b source screening 17/60, cost-ordered cheap-filter cascade 적용 및 global instruction gate 미해결
> 목적: 다른 세션이 결정 근거와 다음 순서를 잃지 않고 작업을 이어간다.
>
> 공개 독자 안내: 이 문서는 세션 간 인계를 위한 상세 작업 로그다. 설치와
> 프로젝트 개요는 [README](../README.md), 규범적 설계는
> [architecture](architecture.md)와 [Phase 2b 사전등록 계약](paired-pilot-preregistration.md)을
> 먼저 본다. 이 로그의 중간 판정은 릴리스된 벤치마크나 agent 순위가 아니다.

## 0. 한눈에 보는 다음 작업

> **지금 할 일:** agent 실행이나 task authoring이 아니라, candidate ledger의
> **cost-ordered cheap-filter cascade의 다음 미완료 단계**를 처리한다.

| 구분 | 내용 |
|---|---|
| 현재 위치 | Phase 2b construction, source screening |
| 현재 수치 | 1,130 candidates = screening 967 + excluded 146 + selected 17 |
| 목표 | selected candidate 60개; Korean 20 / English 20 / mixed 20; category 각 12 |
| 바로 할 작업 | SWE-bench 의미 gate 통과 290개의 isolation·evaluator hiding·fixture health·reproducibility·resource budget 검토; Faker evaluator 1건 별도 adjudication |
| 병렬 blocker | Claude/Codex global instruction을 동등화하거나 isolated empty home으로 격리하고 effective hash pin |
| 다음 단계 진입 조건 | candidate 60개 ledger freeze **그리고** global instruction gate 해결 |
| 금지 | quota 완화, 임의 번역/분류, task/evaluator 동시 저술, agent 결과 열람, 120-run 실행, learned policy 승격 |
| 부족할 때 | `construction incomplete / pilot not authorized`로 수치와 원인을 그대로 보고 |

### 다음 저비용 screening cascade

1. [screening cascade artifact](../experiments/phase2b-screening-cascade-2026-07-24.json)의
   rank를 건너뛰지 않는다. Cached identity/source/license 신호는 이미 적용됐고 GitHub
   `none-observed` 585건은 제외가 아니라 보류다.
2. file-only 66건의 current-HEAD license 분류는 완료됐다. 64건을 전진시키고 GPL-3.0 1건과
   PolyForm Noncommercial 1건은 exact-revision 확인 queue로 보냈다. 이 결과는 nonterminal이다.
3. signal-positive 106건의 issue timeline, direct closing PR, changed-file와 test-touch metadata
   수집은 완료됐다. Eligible 102건은 exact 단계 27 / scope-review 18 / no-test-touch 57로
   나뉘며, suspected-ineligible 4건도 direct solution을 확인했다.
4. rank 5 exact-base/tree와 pinned-license 확인은 31/31 완료됐다. License pass 27 / fail 4이며,
   broad release 1건은 MIT exact base를 확인했지만 scope review로 되돌렸다. Default branch나
   classifier 추정은 끝까지 pass/fail 근거로 사용하지 않았다.
5. 25개 exact tree의 active `AGENTS.md`, `CLAUDE.md`, symlink/import/path-rule inventory는
   완료됐다. Parity pass 9 / fail 16이며 fail 행은 terminal 제외했다.
6. rank 7의 10건 의미 판정과 agent-free reproduction도 완료됐다. 번역 전용 3건과
   다중 결합 1건을 제외했고, 6건은 intended base-negative/solution-positive를 통과해
   `selected-for-task-authoring`으로 이동했다. Candidate agent는 실행하지 않았다.
7. scope-review 18건과 rank 5 반환 1건도 완료됐다. Source 의미 필터에서 7건을 terminal
   제외했고, 12건을 exact base/license/parity로 좁혀 parity 8건을 추가 제외했다. 남은
   4건은 agent-free base-negative/solution-positive control을 통과해
   `selected-for-task-authoring`으로 이동했다.
8. SWE-bench 300건의 dataset terms와 41개 upstream repository의 300개 exact-base license
   확인도 완료됐다. Dataset terms와 exact base는 300/300 pass, upstream license는
   291 pass / 9 terminal fail이다. Terraform BUSL-1.1 5건, Redis RSALv2/SSPLv1 2건,
   jq의 CC BY 3.0 `docs/` 경로 2건만 frozen allow-list 밖이었다.
9. SWE-bench license-pass 291건의 exact-tree instruction inventory도 완료됐다. 서로 다른
   291개 tree의 entry 684,580개에서 project instruction path가 한 건도 발견되지 않아
   candidate-tree parity는 291/291 pass다.
10. SWE-bench 291건의 native-source fidelity도 완료됐다. Resolving PR에서 복원한 현재
    GitHub issue `title + LF + body + LF`가 pinned statement와 291/291 exact match했다.
11. Public-safe mechanical triage로 291건을 28/33/73/157 우선순위로 나눠 읽었고, 세 개의
    disjoint shard와 중앙 교차검토를 완료했다. Boundedness는 291 pass, objective evaluator
    feasibility는 290 pass / 1 unknown이다. Faker 한 행은 alternative API contract 때문에
    implementation-specific oracle을 피하려고 `unknown`으로 보존했다.
12. 다음 queue는 의미 gate를 통과한 290건의 isolation, evaluator hiding, fixture health,
    reproducibility와 resource budget 검토다. Faker 1건은 별도 adjudication하며, 57개
    no-test-touch 행은 test 미접촉만으로 제외하지 않고 계속 보류한다.
13. ledger JSON, summary count, candidate-ledger 문서와 진행 snapshot을 같은 변경에서
    동기화한다. `selected-for-task-authoring`은 12개 rule이 모두 `pass`일 때만 허용한다.
14. 아래 검증을 통과한 뒤 다음 batch로 넘어간다.

```bash
PYTHONPATH=src python3 -m unittest tests/test_phase2b_candidate_ledger.py -v
PYTHONPATH=src python3 -m unittest discover -s tests
git diff --check
```

전체 단계와 이후 task/evaluator construction 순서는
[현재 재개 지점과 고정 작업 순서](#현재-재개-지점과-고정-작업-순서-2026-07-24)에,
중단·승인 조건은 [Phase 2b 사전등록 계약](paired-pilot-preregistration.md)에 있다.

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
2건이 더해져 당시 18건이었다. 이후 parity amendment 1건과 contextual source review
5건이 더해져 현재 파일은 24건(Claude 15, Codex 9; completed 20, failed 3, timed out 1)이다.
후기 6건은 모두 `routing_evidence_eligible=false`이며 앞선 18건도 propensity와 objective
quality 근거가 없어 policy 성능 표본으로 합치지 않는다. 2026-07-22 운영 원칙을 다시
정리해, 주 검토자가 모델을 수동 선택하는 일반 작업·자문은 이후 Claude CLI를 직접
사용하고 오케스트레이터는 objective evaluator가 있는 routing/lifecycle 실행에만 쓴다.

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

### 현재 재개 지점과 고정 작업 순서 (2026-07-24)

이 절이 **다음 작업의 현재 진입점**이다. 아래의 오래된 handoff들은 판단 근거와 감사
기록이며, 작업 순서는 이 절을 우선한다.

| 항목 | 현재 값 |
|---|---:|
| 전체 candidate | 1,130 |
| `screening` | 967 |
| `excluded` | 146 |
| `selected-for-task-authoring` | **17** |
| 목표 native task | 60 (Korean 20 / English 20 / mixed 20) |
| category quota | 각 12 |
| global instruction gate | `unresolved` |
| 현재 focused / 전체 unit tests | **47 / 300 passed** |

#### Portable resume checkpoint — 28차 handoff

이 절만 읽어도 새 clone이나 다른 세션에서 현재 source-screening을 이어갈 수 있어야 한다.
`/tmp` clone, 로컬 CLI history, 이 대화는 근거의 단일 출처가 아니다. 임시 clone은 공개
Git object를 확인하기 위한 cache일 뿐이며, 재개에 필요한 full revision/tree/diff hash와
판정 사유는 저장소 안에 보존한다.

Authoritative 파일의 역할은 다음과 같다.

| 파일 | 재개 시 신뢰할 내용 |
|---|---|
| `experiments/phase2b-candidate-ledger-v1.json` | 1,130개 row, full revision/tree/artifact hash, 12-rule 상태, terminal 사유와 summary count |
| `experiments/phase2b-license-priority-2026-07-24.json` | 현재 screening 전체의 nonterminal license bucket, frozen ledger 순서와 입력 hash |
| `experiments/phase2b-license-file-classification-2026-07-24.json` | file-only 33 repositories/66 rows의 exact current-HEAD license 관측, content hash와 nonterminal 분류 |
| `experiments/phase2b-linked-solution-prefilter-2026-07-24.json` | signal-positive 106 rows의 direct closing PR, HTML/diff hash, test-touch와 nonterminal next route |
| `experiments/phase2b-exact-revision-license-2026-07-24.json` | rank 5의 31개 exact base/tree, complete PR commit lineage, changed-path 대조와 pinned license terminal evidence |
| `experiments/phase2b-rank5-ledger-application-2026-07-24.json` | pre-rank-5 ledger/evidence/output ledger hash 연결, 31개 mutation과 decision-count invariant |
| `experiments/phase2b-rank6-instruction-parity-2026-07-24.json` | 25개 exact tree의 active instruction blob/content hash, effective Claude/Codex chain과 parity terminal 판정 |
| `experiments/phase2b-rank6-ledger-application-2026-07-24.json` | pre-rank-6 ledger/parity evidence/output ledger hash 연결과 25개 mutation |
| `experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json` | rank 7 10건의 source hash 결합, translation/coupling terminal 판정과 6건 reproduction route |
| `experiments/phase2b-rank7-agent-free-reproduction-2026-07-24.json` | 6건의 exact base-negative/solution-positive, evaluator/control hash, resource bucket과 local evidence 위치 |
| `experiments/phase2b-rank7-ledger-application-2026-07-24.json` | pre-rank-7 ledger와 두 evidence hash, 4개 terminal + 6개 selected mutation, 현재 ledger hash |
| `experiments/phase2b-scope-review-source-semantic-2026-07-24.json` | frozen 19건의 source hash와 저비용 terminal 의미 판정; 7개 제외, 12개 exact route |
| `experiments/phase2b-scope-review-solution-segmentation-2026-07-24.json` | 12개 survivor의 exact task-relevant base/solution/path/diff lineage |
| `experiments/phase2b-scope-review-exact-revision-license-2026-07-24.json` | 12개 exact base의 pinned license와 blob/content hash; MIT 11, Apache-2.0 1 |
| `experiments/phase2b-scope-review-instruction-parity-2026-07-24.json` | 12개 exact tree의 parity: pass 4 / fail 8과 active instruction chain |
| `experiments/phase2b-scope-review-exact-parity-ledger-application-2026-07-24.json` | source review 뒤 exact/license/parity evidence와 12개 mutation을 연결한 중간 ledger snapshot |
| `experiments/phase2b-scope-review-survivor-semantic-2026-07-24.json` | parity survivor 4건의 boundedness/isolation/evaluator/hiding pass 근거 |
| `experiments/phase2b-scope-review-survivor-agent-free-reproduction-2026-07-24.json` | 4건의 byte-identical base-negative/solution-positive screening control, health seam과 authoring limitation |
| `experiments/phase2b-scope-review-survivor-ledger-application-2026-07-24.json` | 4개 survivor를 selected-for-task-authoring으로 이동한 최종 evidence/ledger hash 연결 |
| `experiments/phase2b-swebench-license-terms-2026-07-24.json` | pinned dataset README MIT 근거, 41개 repository/300개 exact tree의 root·task-path ancestor license blob/symlink, 291 pass/9 terminal 판정 |
| `experiments/phase2b-swebench-license-terms-ledger-application-2026-07-24.json` | pre/post ledger hash, 300개 exact-base/license mutation과 9개 terminal 제외 연결 |
| `experiments/phase2b-swebench-instruction-parity-2026-07-24.json` | 291개 license-pass exact tree의 684,580개 entry 전수 inventory, project instruction 부재와 parity 291 pass |
| `experiments/phase2b-swebench-instruction-parity-ledger-application-2026-07-24.json` | pre/post ledger hash, 291개 instruction-parity mutation과 decision-count 불변 연결 |
| `experiments/phase2b-swebench-native-source-fidelity-2026-07-24.json` | pinned LFS payload와 291개 current GitHub source issue exact reconstruction, native-source 291 pass |
| `experiments/phase2b-swebench-native-source-fidelity-ledger-application-2026-07-24.json` | pre/post ledger hash, 291개 native-source mutation과 stale reason 교체, decision-count 불변 연결 |
| `experiments/phase2b-swebench-semantic-triage-2026-07-24.json` | 291개 semantic review의 nonterminal 공개 priority cue와 28/33/73/157 review 순서; 판정·mutation 없음 |
| `experiments/phase2b-swebench-semantic-review-2026-07-24.json` | disjoint 98/96/97행 source-first 검토와 중앙 교차판정; bounded 291 pass, evaluator 290 pass / 1 unknown |
| `experiments/phase2b-swebench-semantic-review-ledger-application-2026-07-24.json` | pre/post ledger hash, bounded 291·evaluator 290 partial field mutation, Faker unknown·decision-count 불변과 exact reverse 연결 |
| `experiments/phase2b-screening-cascade-2026-07-24.json` | 저비용 cached filter부터 exact/manual review까지 비용 증가 순서와 evidence boundary |
| `experiments/phase2b-agent-instruction-parity-2026-07-20.json` | exact pinned tree별 active instruction inventory와 parity 판정 27건(pass 13 / fail 14) |
| `docs/paired-pilot-candidate-ledger.md` | inclusion/exclusion 규칙, pool별 현재 수치, 심사 우선순위 |
| `docs/paired-pilot-preregistration.md` | result-blind 역할 분리, global instruction gate, 실행 승인·중단 조건 |
| 이 문서 | 완료 순서, 현재 진입점, 다음 작업과 검증 snapshot |

13–18차 source-screening에서 확정한 최신 연속 batch는 아래와 같다. 표의 abbreviated SHA는
사람용 표기이며 실제 재현에는 ledger JSON의 full SHA를 사용한다.

| 차수 | candidate | exact base / tree | 결과 |
|---:|---|---|---|
| 13 | `ghmix-ohhalim--MembershipFlow-issue-79` | `b2bc8ba…` / `43678ee…` | license/use basis 부재; parity pass |
| 14 | `ghmix-0xkkun--seoul-challenge-issue-30` | `075464d…` / `f9058ee…` | license 부재 + task-relevant `AGENTS.md` only |
| 15 | `ghmix-Gn0lee--oat-issue-410` | `b19b34b…` / `2ea4b5e…` | root app license 부재 + task-relevant `CLAUDE.md` only |
| 16 | `ghmix-handokei--subway-now-issue-1465` | `1c73ae5…` / `158cfba…` | 잘못된 API base 정정; license 부재 + `CLAUDE.md` only |
| 17 | `ghmix-prgrms-aibe-devcourse--AIBE5_FinalProject_Team7_JackPot-issue-499` | `9ae892a…` / `6722de4…` | license/use basis 부재; parity pass |
| 18 | `ghmix-SKALA-TEAM5--frontend-issue-66` | `0950a8e…` / `55524f7…` | multi-issue PR의 final atomic commit 분리; license 부재; parity pass |

2026-07-24부터 단일 issue 순차 심사를 중단하고 cost-ordered cascade를 사용한다. License
filter는 그 첫 remote-data stage다. Cascade 시작 snapshot의
GitHub `screening` 691건은 pinned license pass 2, permissive classifier 36,
license-file-only 66, copyleft classifier 2, `none-observed` 585로 나뉜다. Repository-level
probe는 source pool과 무관하게 재사용하므로 미탐색 저장소는 0개다. File-only 66건은
2026-07-24 current HEAD를 full revision으로 고정한 뒤 GitHub license endpoint와 body hash로
모두 분류했다. 64건은 허용형 신호, 1건은 GPL-3.0, 1건은 PolyForm Noncommercial이었다.
따라서 license-priority queue는 **102건**이며 candidate decision과 12-rule 값은 이
분류만으로 바뀌지 않았다. 후속 linked-solution prefilter는 eligible 102건을 exact 단계 27,
scope-review 18, no-test-touch 보류 57로 나눴다. Suspected-ineligible 4건까지 합친 rank 5
queue 31건은 모두 exact base/tree와 pinned license를 확인했다. 그 결과 27건이 license를
통과하고 4건이 terminal 제외됐으며, 통과 행 중 broad release 1건은 scope review로 되돌아가
**26건**이 다음 rule로 전진했다. 이어진 rank 6에서 새 25건은 parity pass 9 / fail 16으로
판정됐다. 기존 parity pass `doc_parser #288`을 합친 rank 7 work queue **10건**도 모두
처리했다. Source 의미 필터에서 translation-only 3 / multiple-coupled 1을 terminal 제외했고,
나머지 6건은 agent-free base-negative와 solution-positive를 통과해 construction queue로
이동했다. 이어서 scope-review 19건도 frozen ledger 순서대로 끝냈다. Source 단계에서 7건,
exact-tree instruction parity에서 8건을 terminal 제외했고, 마지막 4건은 모든 저비용 의미
gate와 agent-free reproduction을 통과해 construction queue로 이동했다. 현재 ledger는
screening 976 / excluded 137 / selected-for-task-authoring 17이었다. 이어 SWE-bench 300건의
pinned dataset terms와 300개 서로 다른 exact base를 41개 repository fetch로 묶어 확인했다.
MIT dataset terms와 exact base는 모두 통과했고, upstream path license는 291 pass / 9 fail이었다.
2차 exact-tree ancestor scan은 55개 행의 변경 경로에 걸리는 하위 license artifact 61개
(고유 blob 14개, 기존 inventory에 없던 blob 5개)를 추가했고, 모두 기존 MIT/Apache-2.0/
Unlicense 또는 root MIT symlink와 일치해 판정 수는 바뀌지 않았다.
이어 291개 license-pass exact tree의 entry 684,580개를 전수 검사했다. Exact
`AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, `.claude/rules/**/*.md`,
대소문자 변형이 모두 0건이었다. 중앙 전체 스캔과 저장소를 97/98/96행으로 나눈 세
read-only shard가 candidate ID, revision, tree hash, leaf-entry count까지 일치했다. 따라서
291건 모두 candidate-tree instruction parity를 통과했고 candidate decision 수는 바뀌지 않았다.
그 뒤 98/96/97행의 provenance shard가 각 resolving PR의 current GitHub source issue를
복원했다. `title + LF + body + LF` reconstruction은 pinned statement와 291/291 exact
SHA-256 match했고 중앙 재검사도 동일했다. 이어 291행을 98/96/97 disjoint semantic shard로
읽고 중앙에서 민감 행을 다시 판정했다. Single bounded task는 291/291 pass, objective
evaluator feasibility는 290 pass / 1 unknown이다. Faker 한 행은 source가 default 보장과
이름 없는 opt-in API를 모두 허용해 solution-specific oracle을 피하려고 보류했다.
현재 ledger는 screening 967 / excluded 146 / selected-for-task-authoring 17이다.

이전 다음 후보였던 `ghmix-yt010108--kr-gov-job-mcp-issue-51`은 frozen probe에서
`none-observed`인 저장소의 행이다. 탈락시키지 않고 585건 보류 queue로 옮겼다. 지금의
순서는 다음과 같다.

1. file-only 66건의 license 종류 분류는 완료됐다. Current HEAD signal로만 기록돼 있다.
2. signal-positive 106건의 linked solution/test-touch metadata prefilter는 완료됐다.
3. rank 5 exact pre-solution base/tree와 pinned license 31건은 완료됐다. GPL-3.0 2건,
   AGPL-3.0 1건, exact base에 license/use basis가 없는 1건은 terminal 제외했다.
4. Exact-tree instruction inventory 25건은 완료됐다. 9건은 parity를 통과했고 16건은
   `instruction-parity-mismatch`로 terminal 제외했다.
5. rank 7 10건은 완료됐다. 4건 terminal 제외, 6건 selected-for-task-authoring이며 pending은 0이다.
6. solution-scope 18건 + MIT-at-base 반환 1건도 완료됐다. Source 7건과 parity 8건을
   terminal 제외하고, 재현까지 통과한 4건을 selected-for-task-authoring으로 이동했다.
7. SWE-bench 300건의 dataset terms, exact base/tree와 upstream pinned license 확인은
   완료됐다. 291건은 다음 rule로 전진하고 9건은 license terminal 제외됐다.
8. SWE-bench 291건의 exact-tree instruction inventory는 완료됐다. 291건 모두 project
   instruction이 없어 parity를 통과했다.
9. SWE-bench 291건의 native-source fidelity도 완료됐다. Current GitHub issue의 exact
   title/body reconstruction과 모두 일치했다.
10. 291건의 single bounded task와 objective evaluator semantics는 완료됐다. Boundedness
   291 pass, evaluator 290 pass / 1 unknown이며 terminal 제외는 없다.
11. 다음은 290 semantic-pass 행의 isolation·evaluator hiding·fixture health·reproducibility·
   resource 검토다. Faker evaluator 1건은 별도 semantic adjudication에 둔다.
12. 57개 no-test-touch 행은 계속 보류한다. Test 미접촉은 evaluator 저술 비용 신호이지
   terminal 제외 사유가 아니다.
13. Candidate decision이나 frozen screening 값이 변할 때만 ledger summary, 관련 evidence artifact, 문서와
   candidate-specific 회귀 테스트를 함께 동기화한다.

재개하는 세션은 먼저 `git status --short`와 `git diff --stat`로 checkout 이후의 로컬 변경을
확인하고, 파일을 되돌리거나 전체 add하지 않는다. 이 checkpoint가 기록한 의도된 변경 경계는
`experiments/README.md`, `docs/adaptive-routing-progress.md`,
`docs/paired-pilot-candidate-ledger.md`, `docs/paired-pilot-preregistration.md`, scope-review
source/segmentation/exact-license/parity/survivor-semantic/reproduction/application JSON artifact,
SWE-bench exact-license/instruction-parity/native-source/semantic-triage/semantic-review 및 네
ledger-application artifact, candidate ledger와
`tests/test_phase2b_candidate_ledger.py`다. Local `security_best_practices_report.md`는 제거된
Web UI를 전제로 한 오래된 review라 `.gitignore`에 두고 이 변경에 포함하지 않는다. 다시
공개하려면 현재 source 기준으로 scope와 finding을 먼저 재검증한다.

재개와 pre-commit 검증은 특정 `/tmp` package path에 의존하지 않고 다음을 사용한다.

```bash
python3 -m json.tool experiments/phase2b-candidate-ledger-v1.json >/dev/null
python3 -m json.tool experiments/phase2b-agent-instruction-parity-2026-07-20.json >/dev/null
python3 -m json.tool experiments/phase2b-license-file-classification-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-linked-solution-prefilter-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-exact-revision-license-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-license-terms-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-license-terms-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-instruction-parity-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-instruction-parity-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-native-source-fidelity-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-native-source-fidelity-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-semantic-triage-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-semantic-review-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-swebench-semantic-review-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank5-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank6-instruction-parity-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank6-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank7-agent-free-reproduction-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-rank7-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-source-semantic-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-solution-segmentation-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-exact-revision-license-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-instruction-parity-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-survivor-semantic-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-survivor-agent-free-reproduction-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-scope-review-survivor-ledger-application-2026-07-24.json >/dev/null
python3 -m json.tool experiments/phase2b-screening-cascade-2026-07-24.json >/dev/null
PYTHONPATH=src python3 -m unittest tests/test_phase2b_candidate_ledger.py -v
PYTHONPATH=src python3 -m unittest discover -s tests
git diff --check
```

Draft 2020-12 schema는 `jsonschema>=4`가 있는 환경에서
`experiments/schemas/paired-pilot-candidate-ledger-v1.schema.json`을
`Draft202012Validator`로 검증한다. 시스템 package가 오래됐으면 Draft7 성공을 정식
2020-12 성공으로 보고하지 말고, 격리된 환경에 호환 버전을 설치해 다시 실행한다.

다음 작업은 순서대로 진행한다.

1. **Source screening 완료**
   - license type, linked-solution/test metadata, rank 5 exact-base/pinned-license,
     rank 6 exact-tree instruction, 첫 rank 7 semantics/reproduction stage는 완료됐다.
   - scope-review 19건은 완료됐다. Source terminal 7, parity terminal 8, reproduction
     pass와 selected-for-task-authoring 4로 종결했다.
   - SWE-bench 300행의 pinned dataset terms/exact base/upstream license와 license-pass 291행의
     exact-tree instruction parity, exact current-issue native-source fidelity, single bounded
     task 291행과 objective evaluator feasibility 290행까지 완료했다. 다음은 semantic-pass
     290행만 isolation/evaluator hiding/fixture/reproducibility/resource review로 보내고,
     Faker evaluator 1행은 별도 adjudication한다.
   - No-test-touch 57건은 nonterminal deferred 상태로 보존한다.
   - instruction parity와 나머지 inclusion rule을 판정하고 classifier 기반 license
     근거가 남은 과거 행을 재점검한다.
   - 60개 quota를 채우지 못하면 기준을 완화하지 않고
     `construction incomplete / pilot not authorized`로 보고한다.
2. **Global instruction gate 해결**
   - Claude/Codex 전역 지침을 의미상 동등화하거나 양쪽을 isolated empty agent home으로
     격리한다.
   - 실행에 실제 적용되는 effective instruction과 hash를 manifest에 pin한다.
3. **Candidate ledger 동결**
   - result-blind provenance와 60개 language/category quota를 모두 충족한 snapshot만
     동결한다.
4. **역할 분리 task/evaluator construction**
   - task author가 60개 prompt, acceptance criteria, exact modified-file allowlist와
     resource bucket을 작성한다.
   - 별도 evaluator author가 보호 evaluator 60개, assertion inventory와
     base-negative/solution-positive control을 작성한다.
5. **독립 validity review와 manifest/tooling 완성**
   - reviewer가 agent 결과 없이 provenance, leakage, evaluator completeness를 검토한다.
   - `paired-pilot-manifest-v1` instance와 별도 Phase 2b semantic validator를 완성한다.
6. **Agent-free 120-workspace dry run**
   - unique identity, exact base/fixture, evaluator hash, workspace 격리와 전체 budget을
     agent 호출 없이 검증하고 manifest를 freeze한다.
7. **별도 승인 요청 후에만 120 execution 실행**
   - 승인 전에는 Phase 2b runner 실행, prospective exploration, learned-policy 승격을
     시작하지 않는다.

현재 바로 착수할 항목은 **1번 source screening의 다음 batch**다. 1번과 2번은 독립적으로
진행할 수 있지만, 둘 다 닫히기 전에는 task authoring으로 넘어가지 않는다.

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
- [x] Stage 1 exact query 78개 목록 생성·동결과 수집(저장소 1,855개, permissive 1,055개)
- [x] 기존 411 pool의 repository 단위 early filter
- [x] 4개 toolchain provisioned 재현 실측과 절차 문서화
- [x] resource bucket(`small`/`medium`) 정의와 첫 selected 2건
- [x] LLMRouterBench 원문 대조로 §3.3 "단순 baseline 우선" 근거 검증
- [x] base tree의 agent instruction 파일 비대칭 발견과 70개 저장소 prevalence 측정
- [x] Claude Code discovery 실측과 Codex 0.144.6 root `AGENTS.md` behavioral probe
- [x] 사전필터 유망 8건 원문 판독과 base·tree·license 확정
- [x] `factlog #314`·`BidMate #1152`·`anygarden #512` provisioned 재현(negative/positive control 완료)
- [x] `anygarden #512` 당시 11/11 판정과 세 번째 `selected-for-task-authoring` 승격
- [x] `factlog #314` license 근거를 classifier 신호에서 pinned revision artifact로 정정
- [x] 위 판정을 고정하는 회귀 테스트 2개 추가(focused 12 tests, 전체 270 tests)
- [x] official Codex discovery rule 확인, exact-base parity 12행 판정, protocol `v1.1` amendment
- [x] `factlog #314` 네 번째 `selected-for-task-authoring`, mismatch 7행 terminal 제외
- [x] `v1.1` candidate/manifest schema와 1,130-row ledger 정식 Draft 2020-12 검증, focused 15 / 전체 273 tests 통과
- [x] 수동 agent 선택 방식의 3-row contextual screening, exact-base materialization 2건과 terminal 제외 3건(focused 16 / 전체 274 tests)
- [x] 의도된 동작을 하지 않던 Web UI와 전용 background queue 범위 제거(전용 테스트 7개 포함, 전체 267 tests)
- [x] 수동 Claude 자문을 교차검증한 2차 3-row contextual screening(2 제외, 1 exact-base materialization)
- [x] Python package를 책임별 하위 package로 재배치하고 기존 CLI/public import 호환 유지(전체 269 tests)
- [x] 3차 3-row contextual screening: exact base·license·parity 확정, boundedness 2건과 parity 1건을 분리해 terminal 제외(focused 17 / 전체 270 tests)
- [x] 4차 3-row contextual screening: translation/subjectivity 2건 제외, API base 불일치가 있는 `doc_parser #288` exact merge-base와 11/12 판정 확정(focused 18 / 전체 271 tests)
- [x] 수동 일반 작업·자문은 직접 Claude CLI, objective routing/lifecycle 실행만 오케스트레이터를 쓰도록 운영 경계 분리
- [x] `prompt-booster #10` agent-free base/head control과 다섯 번째 contextual parity로 12/12 선정
- [x] base-known 세 후보 종결: `factlog-academic #342`·`ChunChuGwan #406` 선정, `swift-tui #18` parity mismatch 제외(focused 21 / 전체 274 tests)
- [ ] global instruction을 의미상 동등화하거나 양쪽 isolated empty agent home으로 격리한 뒤 manifest hash pin
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
3. 2026-07-22 제거된 Web UI/socket 테스트는 더 이상 없다. 아래 전체 suite를 실행한다.
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

### 2026-07-20 5차 handoff — 연구 근거 검증, instruction parity, 재현 3건

이 세션은 설계를 바꾸지 않았다. 60 tasks × 2 agents = 120 executions 원안과 ko/en/mixed
각 20, category 각 12는 그대로다. agent에게 task를 실행시키지 않았고 evaluator 저술도
하지 않았다. `selected`는 2건에서 **3건**이 됐다.

| 항목 | 값 |
|---|---:|
| `screening` | 1,053 |
| `excluded` | 74 |
| `selected-for-task-authoring` | **3** |
| 전체 unit test | **270** (focused ledger 12) |

selected 3건의 marginal quota는 ko 3 / en 0 / mixed 0이고 category는 debugging 2 /
implementation 1이다.

#### LLMRouterBench 원문 대조 — §3.3의 근거는 튼튼하다

[연구 검토](routing-research-review.md) §4.1이 인용한 수치를 원문(Findings of ACL 2026,
pages 37733–37754)과 대조했다. **23,945 prompt / 391,645 instance / 21 dataset / 33 model은
모두 원문에 그대로 있다** — 검토 문서의 인용은 정확하며, 오히려 "over 400K instances"로
반올림한 초록보다 정확하다.

다만 출처를 정확히 적어 둔다. 이 총계는 §3.5 **본문**의 문장에서 왔고 Table 3이 아니다.
Table 3은 설정별로 나눠 싣는데 그 합이 총계와 맞지 않는다 — prompt는 11,480 + 12,446 =
23,926으로 19 부족하고, instance는 229,600 + 161,520 = 391,120으로 525 부족하다. dataset도
15 + 10 = 25이고 본문의 21은 두 설정에 겹치는 dataset을 제거한 고유 수인데, 그 중복 관계는
확인하지 않았다. **원문 자체의 표와 본문이 정합하지 않는 것이며 검토 문서의 인용 오류가
아니다.** 재인용 시 "Table 3과 일치"라고 쓰지 말고 본문 총계임을 밝힌다.

내용 쪽 확인 결과: clustering 기반 Avengers가 neural 학습 없이 경쟁력을 보인다는 서술,
coarse domain structure 기여, 희소 사례(정답 모델 ≤3, 410 queries/11.9%)에서 Avengers
24.6% · EmbedLLM 23.2%라는 낮은 recall, 상용 router(OpenRouter)가 best-single을 이기지
못한다는 결과가 모두 원문에 있다.

정밀도 차이 3건은 기록만 해 둔다 — 프레임워크가 통합한 baseline은 10개지만 실험에서
평가한 것은 9개이고, coarse domain structure는 원문이 `may be attributable`로 완화하며,
상용 router는 "더 나빴다"가 아니라 "이기지 못했다"이다.

원문에 있으나 검토 문서가 아직 수확하지 않은 결과 둘은 현재 설계를 **보강**한다.
embedding ablation이 "backbone embedding이 routing 성능에 거의 영향이 없다"고 보고하므로
§6의 *prompt embedding/neural router 보류*가 표본 부족 외의 직접 근거를 얻는다. 그리고
"모델을 늘리는 것보다 신중한 curation이 낫다"는 diminishing-returns 결과는
constitution의 *최소 충분 지능*과 현재 2-agent 범위를 지지한다.

#### base tree의 agent instruction 파일 비대칭 (이 세션의 핵심 발견)

Claude Code는 `CLAUDE.md`를, Codex는 `AGENTS.md`를 읽는다. 후보의 base tree가 둘 중
하나만 갖거나 둘의 내용이 다르면, **fixture 자체가 두 agent에게 다른 지시를 준다.**
이는 task 품질 문제가 아니라 비교 타당성 문제다.

license 신호가 있는 저장소와 사전필터 통과 저장소의 합집합 **70개**(뒤에 candidate
144행)를 default branch 기준으로 측정했다
([artifact](../experiments/phase2b-agent-instruction-parity-2026-07-20.json),
`terminal_status: false` — pinned revision 사실이 아니므로 어떤 행의 판정도 바꾸지 않는다).

| 상태 | 저장소 | rows |
|---|---:|---:|
| `asymmetric-one-sided` | 30 | 66 |
| `clean-neither` | 17 | 28 |
| `asymmetric-divergent` | 13 | 24 |
| `symmetric-symlink` | 6 | 15 |
| `equivalent-by-import` | 4 | 11 |

**파일 존재의 분포는 한쪽으로 치우치지 않았다.** 한쪽만 존재하는 30건은 `CLAUDE.md`만
16 대 `AGENTS.md`만 14, 내용이 다른 13건은 7 대 6이다.

**그러나 이것을 "agent 편향이 없다"로 읽으면 안 된다.** 파일 존재의 균형과 *실효 지시*의
균형은 다른 명제이고, 후자는 Codex가 무엇을 읽는지를 알아야 판정된다. 예를 들어 Codex가
`AGENTS.md`를 읽지 않는다면 `AGENTS.md`만 있는 14건은 양쪽 모두 지시를 못 받아 대칭이 되는
반면, `CLAUDE.md`만 있는 16건과 내용이 다른 13건은 Claude에게만 지시가 가는 **방향성 있는**
비대칭이 된다. Codex 측이 미측정인 동안 이 문장은 파일 분포에 대한 서술로만 읽어야 한다.

방향성 여부와 별개로, 이 pilot의 primary estimand가 **discordant-pair rate와 분산**이므로
평균 상쇄는 애초에 방어가 되지 않는다. task마다 한쪽만 저장소 지시를 받으면 agent 능력과
무관한 discordance가 주입되고, 그 수치로 확증 round의 표본수를 계산하게 되어 오염이 다음
단계로 전파된다.

parity 발견 당시의 `selected` 2건은 검증을 통과했다. `ante #2349`의 `CLAUDE.md`는 mode `120000` symlink라
`AGENTS.md`와 byte-identical이고, `factlog #26`은 두 파일이 모두 없다.

#### CLI instruction discovery 실측 — Claude 완료, Codex 차단

자기보고가 아니라 행동 관찰로 측정했다. 격리된 빈 디렉터리에 서로 다른 출력 마커를 지시하는
instruction 파일을 두고 파일 접근이 불필요한 사소한 질문을 던져, 어느 마커가 나오는지로
auto-inject를 판별했다. Claude 쪽은 파일 읽기 도구를 차단해 tool-read 경로를 배제했다.

Claude Code 2.1.215 결과: 둘 다 있으면 `CLAUDE.md`만 읽고, **`AGENTS.md`만 있으면 아무것도
읽지 않으며**, `CLAUDE.md`가 `@AGENTS.md` import이면 **그 import를 해석해 AGENTS 내용을
주입한다.** 즉 "Claude도 `AGENTS.md`를 읽으므로 30건이 구제된다"는 가설은 거짓이고,
`equivalent-by-import` 유형은 실제로 동등하다.

Codex 0.144.6은 **측정하지 못했다.** 4회 호출이 전부 usage limit에 막혔고 모델 호출 이전
단계라 토큰·비용은 0이다. CLI가 보고한 해제 시각은 **2026-07-25 13:54**다.

**이 절반이 없으면 어떤 행의 parity도 판정할 수 없다.** 각 범주가 대칭인지 아닌지가
Codex의 동작에 달려 있는데 그 동작이 미측정이기 때문이다. 통과 가능 행의 수를 추정하지
않는다 — 추정하려면 Codex가 무엇을 읽는지 가정해야 하고, 그 가정에는 현재 근거가 없다.

#### 이 측정의 한계 — 두 파일만 봤다

prevalence probe는 `CLAUDE.md`와 `AGENTS.md` **두 파일만** 조회했다. 그런데 이 세션에서
읽은 제3자 문서(`nixos-config`의 `using-codex-exec` skill)는 Codex의 discovery가
`AGENTS.override.md > AGENTS.md > TEAM_GUIDE.md > .agents.md` 우선순위 체인이라고 서술한다.
실제로 `nixos-config`의 base tree에 `AGENTS.override.md`가 존재했다.

따라서 다음이 아직 성립하지 않는다.

- `clean-neither` 17개도 대칭이 보장되지 않는다. 두 파일이 없을 뿐 체인의 다른 파일이
  있으면 Codex만 지시를 받는다.
- 체인 자체의 출처가 제3자 문서다. Codex 공식 문서나 실측으로 확인해야 한다.

재측정 시 범위를 체인 전체로 넓히고, Claude 쪽도 같은 방식으로 다시 확인한다.

설치본이 Phase 2a v2의 pin(2.1.212 / 0.144.5)에서 patch 단위로 drift했으므로(2.1.215 /
0.144.6), Phase 2b는 자기 manifest가 pin하는 버전으로 다시 측정해야 한다.

#### 사전필터 유망 8건 판독과 base 확정

8건 모두 원문이 native Korean이고 근본 원인이 코드 라인 수준으로 명시돼 있었다. 전부
base·tree·license를 확정해 ledger에 반영했다. instruction 파일은 뒤늦게 발견한 한계를
반영해 **넓힌 7개 이름 집합**으로 조사했다.

| candidate | base tree | license @ pinned | instruction 파일 |
|---|---|---|---|
| `nixos-config #918` | `4a6191c6` | MIT | symlink 동일 + Codex 전용 `AGENTS.override.md` |
| `factlog-academic #342` | `3f20d12a` | Apache-2.0 (+NOTICE, pyproject 선언) | `@AGENTS.md` import |
| `blog #12` | `9d3226c1` | MIT (저작권자는 상류 Chirpy 테마 저자) | `CLAUDE.md`만 |
| `zntc #4564` | `e8f90423` | MIT (+NOTICE) | 불일치 |
| `zntc #4563` | `7944edc0` | MIT (+NOTICE) | 불일치 |
| `zntc #4553` | `2addf621` | MIT (+NOTICE) | 불일치 |
| `anygarden #512` | `14d7dfb7` | Apache-2.0 | **전무** |
| `AgentDesk #4606` | `64cc2b88` | MIT (+NOTICE) | `CLAUDE.md`만 |

8건 중 instruction 파일이 없는 것은 `anygarden #512` 하나뿐이다. 유망 후보군이 parity
문제에 광범위하게 걸려 있다는 prevalence 측정과 일치한다.

`zntc #4553`은 `single_bounded_task`를 `unknown`으로 뒀다. 이슈가 스스로 #4548/#4549/#4551을
함께 해소한다고 밝히고 #4542·#4552·#1027까지 참조한다. `AgentDesk #4606`은 병합 변경이
생성 문서 레지스트리를 포함해 11개 파일이고, 이슈 본문이 다른 이슈와 표면이 겹쳐 순서
조율이 필요하다고 적고 있다.

#### `anygarden #512` — Codex 차단과 무관하게 완주해 세 번째 selected

941개 파일 base tree 전수에 두 CLI가 자동 발견하는 경로의 파일이 하나도 없어, **parity가
Codex 측정에 의존하지 않는 유일한 후보**였다. Node v22.14.0을 게시자 `SHASUMS256.txt`와
대조해 고정하고 저장소 자체 lockfile로 `npm ci`(1,036 패키지, 35초)한 뒤 재현했다.

evaluator는 PR 시점 재구성(base에 test·impl 모두 존재)이고, 적응 2건은 모두 evaluator를
checkout 밖에 두기 위한 것으로 assertion 11개는 불변이다. negative control 4실패/6통과이며
4건 모두 `formatMessageTimestamp`가 base에 없어서다. positive control은 impl만 적용해
10/10 통과했다. evaluator 0.9초로 `small`, 보호 hash 불변, pristine base clean.

남은 4개 rule도 판정했다. `native_language_source`는 **native Korean**으로 분류했다 —
사전등록 §4.1이 "mixed는 identifier만 영어인 것을 뜻하지 않고 지시·문서·acceptance
criteria에서 두 언어가 실제로 필요해야 한다"고 정의하는데, 이 후보는 지시·수용 기준·요구
출력 형식이 모두 한국어이고 영어는 identifier와 경로뿐이다. `ghmix-` 접두사는 발견된
pool을 기록할 뿐 분류가 아니다. 11개 rule이 모두 `pass`가 되어 `selected`로 옮겼다.
task 저술, evaluator 저술, validity review는 별도 역할이며 여기서 수행하지 않았다.

#### provisioned 재현 2건 — 성공했으나 승격은 못 한다

| | `factlog #314` | `BidMate #1152` |
|---|---|---|
| evaluator 출처 | PR 318 신규 테스트(base에 없음 → held-out) | PR 시점 재구성(test hunk +195만 적용) |
| 적응 | 1줄, assertion 13→13 | 1 import + 1줄, assertion 47→47 |
| negative | **3 실패 / 6 통과**, 전부 의도 | **26 실패 / 27 통과**, 전부 의도 |
| positive | **9/9** | **53/53** |
| evaluator 시간 | 1.2초 → `small` | 0.6초 → `small` |

보호 artifact hash는 실행 전후 불변, pristine base는 clean하고 tree hash가 유지됐다.
재다운로드한 CPython 3.11.15의 SHA-256이 2026-07-19 측정 artifact의 digest와 일치해,
"디렉터리가 아니라 기록된 identity가 재구성을 가능하게 한다"는 원칙이 실증됐다. ledger가
blocker로 적어 둔 `pyrewire` 의존성은 4초에 설치됐다.

그럼에도 두 행 모두 `reproducible_within_budget`은 `unknown`이다. ledger가 environment
parity를 이 rule에 묶어 두었고 Codex 측 discovery가 미측정이기 때문이다. **막힌 이유가
rule 전체에서 한 항목으로 좁혀졌다.** `BidMate`는 `CLAUDE.md` 12,250B에 `AGENTS.md`가
없어 지금까지 관측한 것 중 가장 큰 일방 비대칭이다.

#### license 근거 정정

`factlog #314`의 `license_or_use_basis`가 "upstream repository metadata declares SPDX
Apache-2.0"이었다. 이는 **classifier 신호**이며 2026-07-19에 확정한 "exact pinned revision
artifact로만 판정한다"는 규칙에 어긋나는데도 `pass`로 남아 있었다. 규칙 확정 이전에 기록된
행이 소급 점검되지 않은 것이다. pinned revision을 materialize해 Apache-2.0 LICENSE와 NOTICE,
`pyproject.toml` 선언을 확인했으므로 판정은 유지하고 근거만 승격했다. 같은 시기의 다른 행에도
classifier 기반 근거가 남아 있을 수 있어 한 번 훑을 가치가 있다.

새 회귀 테스트는 license 근거 문자열이 **자기 `base_revision`을 포함**하도록 강제해 이
경로를 막는다.

#### 일부러 결정하지 않은 것

- **`provisional_classification` 미기입**: 4건의 원문을 읽었지만 language/category를 비워
  뒀다. 회귀 테스트가 "수동 검토됨"을 `task_category is not None`으로 정의하는데, 기존
  29/50건은 고정 seed의 결정적 표본이고 오늘 4건은 기계적 사전필터라는 다른 경로로 왔다.
  섞으면 selection bias 감사 흔적이 흐려진다. 관측은 `decision_reasons`에 남겼다.
- **`source_kind` 미변경**: 4건이 이제 linked PR·base·changed_files를 갖췄으므로 실질적으로
  `public-issue-pr-pair`이지만 `public-issue-discovery`로 남겼다. 기존 27건이 수집 시점
  분류인지 provenance 복원 후 재분류인지 확실하지 않다. 바꾸려면 Korean pool의
  `{discovery: 384, pr-pair: 27}` 고정 테스트도 함께 갱신해야 한다.

#### 운영 사실 — quota는 예약 예산으로 다뤄야 한다

4회짜리 probe로 Codex 할당량이 5일 소진됐다. Phase 2a v2 smoke는 이미 **Claude**
session-quota로 한 행의 quality를 잃었다. 120-execution pilot은 양쪽 계정에 지속적 여유가
필요하므로, 사전등록 §8이 실행 승인 전에 요구하는 "CLI quota 상태"는 시점 확인이 아니라
**예약된 예산**으로 다뤄야 한다.

#### 이 세션에서 확정된 작업 규칙

**이 저장소에 `AGENTS.md`는 없다. 찾거나 만들지 마라.** 이번 세션이 instruction parity를
전면에 올렸기 때문에 "parity를 맞추려면 이 저장소에도 `AGENTS.md`를 두어야 하나"로
오해할 여지가 생겼다. parity는 **후보 저장소의 base tree** 성질이지 이 저장소의 설정이
아니다. 후보 base tree의 instruction 파일도 삭제·변경하지 않는다.

**base 해소는 git protocol로 한다 — core 한도를 쓰지 않는다.**

```text
github.com/{repo}/pull/{n}.patch                PR 커밋 SHA 목록 (From 줄)
git fetch --depth N origin refs/pull/{n}/head   PR head를 N=커밋수+1로 가져옴
git rev-parse {최초_PR_커밋}^                   그 부모가 base
git fetch --depth 1 origin {base}; git checkout
git rev-parse 'HEAD^{tree}'                     tree hash는 반드시 여기서 읽는다
```

`GET /git/trees/{commit_sha}`는 입력 SHA를 되돌려주므로 tree hash 출처로 쓰면 안 된다.
오늘 8건을 이 경로로 해소했고 core 요청은 한 건도 쓰지 않았다.

**보호 evaluator는 PR 시점으로 재구성한다.** default branch의 테스트를 그대로 쓰면 그 PR
이후 변경들의 assertion까지 실패해 negative control이 의도한 이유로만 실패하지 않는다.
PR diff에서 테스트 hunk만 뽑아 base 테스트에 적용한다. 테스트가 base에 없는 신규 파일이면
그대로 held-out이다.

evaluator를 agent-writable checkout 밖으로 옮기면 repo-local 컨텍스트를 잃는다. 오늘 세
가지 형태가 나왔다.

| 형태 | 대응 |
|---|---|
| `Path(__file__).parents[N]`로 repo root 유도 | root를 환경변수로 주입 가능하게 한 줄 수정 |
| 상대경로 subprocess가 cwd를 repo root로 가정 | 파일 수정 없이 cwd를 workspace로 지정 |
| 상대 import(`./datetime`)가 subject를 못 찾음 | import 지정자를 별칭으로 바꾸고 보호 config에서 alias 주입 |

이 적응은 evaluator 제작의 일부이며 **assertion 수가 불변임을 반드시 대조**한다(오늘
13→13, 47→47, 11→11). 보호 artifact는 `0444`로 두고 실행 전후 hash 동일성을 확인한다.

#### 다음에 할 수 있는 것

1. 사전필터 통과 후 미판정 나머지 행의 base·license 확정 — parity와 무관하게 진행 가능하다.
2. 2026-07-25 이후 Codex discovery 측정(체인 전체 범위로) → parity 기준 확정 → 두 재현
   행의 `reproducible_within_budget` 판정. 그 결과로 `selected`가 몇 건이 될지는 지금
   추정하지 않는다.
3. parity 기준이 정해진 뒤, 통과 가능 후보가 quota에 못 미치면 pool 확장(Frame B 재설계 또는
   Frame C 개방)이나 프로토콜 개정이 필요하다. **둘 다 사전등록 개정 사안이며 이 세션에서
   결정하지 않았다.**
4. classifier 기반 license 근거가 남은 다른 행 점검.
5. 제공자 데이터 취급 확인 — 60-task 실행 승인 전 필수(§4.3에 미확인으로 기록됨).

### 2026-07-22 6차 handoff — Codex discovery와 instruction parity v1.1

이번 handoff는 2026-07-20 blocker의 **evidence와 candidate decision만** 갱신했다. candidate
agent output은 보지 않았고, task/evaluator를 저술하거나 agent를 실행하지 않았다.
`selected-for-task-authoring`은 final pilot task가 아니라 다음 역할 분리 construction으로
넘길 수 있는 queue 상태다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,045 |
| `excluded` | 81 |
| `selected-for-task-authoring` | **4** |
| exact-base parity 판정 | pass 5 / fail 7 / 그 밖은 unknown |
| focused candidate-ledger tests | **15 passed** |
| 전체 unit tests | **273 passed** |

construction queue의 marginal은 ko 4 / en 0 / mixed 0, category는 debugging 3 /
implementation 1이다. 60-task quota는 여전히 충족되지 않았고 pilot은 승인되지 않았다.

#### 세 evidence 층을 분리했다

**Behavioral evidence.** 설치된 Codex CLI는 0.144.6이다. 격리된 임시 Git 저장소 root의
`AGENTS.md`에 `PROJECT_AGENTS_MARKER_7F31` exact-output 지시를 두고 다음을 실행했다.

```text
codex exec --ephemeral --json -s read-only -C <repo> -c model_reasoning_effort=none
```

trivial no-tool prompt의 final answer가 marker와 byte-for-byte 같았다. usage는 input 12,706 /
output 13 / reasoning 0 tokens다. 이 결과가 행동으로 입증하는 것은 **0.144.6이 non-empty
root `AGENTS.md`를 load한다는 한 case뿐**이다.

**Official-document evidence.** [Codex 공식 문서](https://developers.openai.com/codex/guides/agents-md)는
global에서 첫 non-empty `AGENTS.override.md` else `AGENTS.md`, project에서 root→cwd를 걸으며
디렉터리마다 `AGENTS.override.md`, `AGENTS.md`, configured fallback 순으로 최대 하나를
읽는다고 설명한다. 로컬 `$HOME/.codex/config.toml`에는
`project_doc_fallback_filenames`가 없어 effective fallback은 empty다. 따라서
`TEAM_GUIDE.md`와 `.agents.md`는 이 환경에서 자동 instruction이 아니다.

override precedence, root-to-cwd merge, configured fallback selection은 이 handoff에서
behaviorally probe하지 않았다. 이 세 claim은 공식 문서 근거이며 marker 실측이라고 쓰지
않는다.

**Unmeasured or non-terminal evidence.** 70-repository prevalence는 여전히 default branch의
두 파일만 본 자료다. 16:14, 7:6이라는 file-presence 균형은 effective directional bias가
없다는 증거가 아니다. Codex 측정 전에는 방향이 unknown이었고, 지금도 pinned candidate와
global instruction을 대신하지 못한다. 따라서 prevalence row로 candidate를 승격·제외하지
않았다.

#### `v1.1` protocol amendment

project instruction parity가 material eligibility인데 `reproducible-within-budget` 안에 묻혀
clean terminal path가 없었다. `phase2b-pilot-prereg-v1.1`은 다음 최소 변경만 한다.

- inclusion rule `instruction-parity` 추가;
- terminal exclusion `instruction-parity-mismatch` 추가;
- resource reproduction과 project instruction parity 분리;
- future manifest의 `environment.global_instruction_context`에 resolution, inventory hash,
  두 effective-instruction hash, empty Codex fallback 배열, 검증 시각 요구.

candidate base instruction 파일이나 양쪽 global 파일은 수정하지 않았다. manifest schema
이름은 아직 instance가 없는 `paired-pilot-manifest-v1`을 유지하고 protocol version만 1.1로
올렸다.

#### pinned-base decision

판정은 recorded exact-base tree inventory가 있는 12행에만 적용했다. 초기 기록이 두 파일
확인에 그쳤던 `factlog #26`, `ante #2349`, `factlog #314`, `BidMate #1152`는 exact base의
recursive GitHub tree를 재조회했다. 77/1,057/373/845 entries 모두 `truncated=false`였고
Git Commit API의 `tree.sha`도 ledger hash와 일치했다.

| profile | candidate | parity | decision effect |
|---|---|---|---|
| `AGENTS.md` + `CLAUDE.md`가 `@AGENTS.md` import | `factlog-academic #314`, `#342` | pass | `#314` selected-for-task-authoring, `#342` screening 유지 |
| byte-equivalent symlink | `ante #2349` | pass | selected 유지 |
| discovered path 없음 | `factlog #26`, full-tree `anygarden #512` | pass | selected 유지 |
| `CLAUDE.md` only | `BidMate #1152`, `blog #12`, `AgentDesk #4606` | fail | terminal 제외 |
| 서로 다른 `CLAUDE.md` / `AGENTS.md` | `zntc #4564/#4563/#4553` | fail | terminal 제외 |
| 동일 symlink 외 별도 `AGENTS.override.md` | `nixos-config #918` | fail | terminal 제외; override는 official-document 근거 |

`factlog #314`와 `BidMate #1152`의 agent-free reproduction은 모두 이미 끝났으므로 양쪽
`reproducible-within-budget`은 `pass`다. 전자는 parity도 pass라 12/12 construction queue로
가고, 후자는 parity fail이라 제외된다. 이 분리가 amendment의 목적이다.

`Docker-Compose #38`은 default-branch prevalence에만 instruction 신호가 있어 parity를
`unknown`으로 유지했다. 기존 `subjective-only-evaluation` 제외만 유지하며, candidate
ledger 문서의 중복 문단 하나를 제거했다.

#### global instruction gate는 아직 열려 있다

비공개 user-level instruction inventory를 result-blind하게 비교한 결과, 양쪽 global
instruction은 존재하지만 의미상 같지 않았다. 개인 지식·도구 환경의 경로, 파일명, import와
내용은 repository 근거가 아니므로 공개 문서와 artifact에서 의도적으로 제외한다.
Project-level candidate pass가 이 confounder를 없애지는 않는다.

실행 전에는 의미상 동등화 또는 양쪽 isolated empty agent home이 필요하고, 그 결과의
effective instruction을 manifest에 hash로 pin해야 한다. 알려진 비대칭 상태의 hash만 남기는
것은 confounder를 문서화할 뿐 gate를 닫지 않는다. 현재 `gate_status=unresolved`다. global
파일은 이 repository 밖이며 이번 handoff에서 수정하지 않았다.

#### 다음 gate

1. 미판정 후보의 exact-base active instruction path inventory와 나머지 inclusion screening;
2. global instruction context를 동등화/격리한 뒤 manifest instance에 hash pin;
3. 60개 candidate quota가 채워진 뒤에만 역할 분리 task/evaluator construction;
4. 별도 validity review와 agent-free controls 후 manifest freeze;
5. 그 뒤에도 사용자 별도 승인 전에는 120-run pilot을 실행하지 않음.

### 2026-07-22 7차 handoff — 수동 agent 선택 contextual screening

오케스트레이터 운영은 `--agent auto` 호출에서 **주 검토자가 작업물을 먼저 보고 적합한
agent를 수동 선택하는 방식**으로 바꿨다. 이번 3-row batch는 issue/PR 내용의 구조 비교가
핵심이라 Claude를 명시했으며, 주 검토자가 primary snapshot을 준비하고 결과를 독립
재검증했다. Claude 결과 자체는 candidate 판정 근거도 routing evidence도 아니다.

`ccc-node #34`는 issue 한 건에 다섯 제안과 여덟 acceptance item이 결합됐고 원문과 linked
PR #35가 네 단계 중 첫 slice만 구현됐음을 함께 보여 `multiple-coupled-issues`로 terminal
제외했다. 이어서 `filme #432`와 `swift-tui #15`의 linked PR base/head를 실제 Git object로
materialize해 parent 관계, tree hash, changed-file scope, PR diff hash를 확인했다. pinned
base license는 각각 MIT와 Unlicense로 통과했지만 exact tree가 각각 root `CLAUDE.md` only와
root `AGENTS.md` only여서 v1.1 `instruction-parity-mismatch`로 terminal 제외했다. `filme`의
nested skill `AGENTS.md`는 repository-root working directory의 Codex discovery chain 밖이다.
candidate agent, task authoring, evaluator 저술·실행은 하지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,042 |
| `excluded` | 84 |
| `selected-for-task-authoring` | **4** |
| exact-base parity 판정 | pass 5 / fail 9 / 그 밖은 unknown |
| focused candidate-ledger tests | **16 passed** |
| 전체 unit tests | **267 passed** |

#### Web UI scope removal

현재 프로젝트에서 의도한 제어 동작을 하지 않으며 핵심 routing/experiment 범위를 넓히던
stdlib Web UI를 제거했다. `web_ui.py`와 그 UI만 소비하던 `control.py` single-worker queue,
전용 테스트 7개, README 실행 안내를 함께 삭제했다. CLI, interactive shell, curses TUI는
이 모듈을 import하지 않아 유지된다. `.orchestrator/jobs.jsonl`의 기존 로컬 데이터는
삭제하지 않았다.

### 2026-07-22 8차 handoff — 2차 contextual screening

mechanical-prefilter를 통과하고 아직 terminal 판정이 없던 `factlog #269`,
`ChunChuGwan #406`, `filme #348`의 issue/PR/files primary snapshot 9개를 `/tmp` 격리
workspace에 준비했다. 원문 의미와 evaluator derivability 비교가 핵심이라 Claude를 수동
지정했다. 첫 호출은 non-Bash file enumeration 도구가 없어 내용 분석 전에 중단됐고, exact
filenames를 명시한 재호출만 자문으로 사용했다. 두 호출 모두 manual cohort이고 objective
quality evaluator가 없으므로 routing evidence에는 들어가지 않는다.

주 검토자가 원문을 다시 대조해 다음처럼 확정했다.

- `factlog #269`: 설정 저장은 deterministic하게 검사할 수 있지만 candidate 핵심인 LLM
  narration·summary·gloss 적절성은 objective mode로 판정할 수 없다.
  `subjective-only-evaluation`으로 제외했다.
- `filme #348`: 이슈 자체가 gitignored private ticket/ground truth와 API key가 필요한 live
  Gemini STRICT 검증을 definition of done으로 요구한다. Offline label/undo test만 채점하면
  핵심 OCR extraction을 사후 축소하므로 `unsafe-or-external-side-effect`로 제외했다.
- `ChunChuGwan #406`: cache bypass, Range byte semantics, attachment/CSP header, auth gate,
  local-mode invariant를 원문에서 독립 도출할 수 있다. linked PR base/head를 materialize해
  616-entry base tree, 7-file scope와 pinned MIT를 확인했다. Root `AGENTS.md`가
  `CLAUDE.md`를 SSOT로 읽으라고 지시하지만 별도 Codex 안내와 Claude path rules가 있어
  semantic instruction parity는 `unknown`으로 유지했다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,040 |
| `excluded` | 86 |
| `selected-for-task-authoring` | **4** |
| focused candidate-ledger tests | **16 passed** |
| 전체 unit tests | **267 passed** |

### 2026-07-22 9차 handoff — 3차 contextual screening

mechanical-prefilter의 다음 순서인 `Aido #655`, `small-village #51`, `Soku #19`를
result-blind하게 심사했다. 세 linked PR의 API base/head를 partial Git clone으로
materialize하고 `merge-base --is-ancestor`, base/head tree, base-to-head changed files와 PR
diff SHA-256을 확인했다. Pinned license는 차례로 MIT, Apache-2.0, MIT다.

- `Aido #655`: 2-commit/13-file solution이다. Root와 변경 scope인 `apps/api`에서
  `CLAUDE.md`가 각각 대응 `AGENTS.md`를 import해 project parity는 `pass`다. 그러나 원 이슈는
  failed-job retention/cleanup·dispatch fail-open과, 관측된 실패의 원인이 아니라고 명시한
  Redis maxmemory eviction health probe 및 별도 운영 parameter-group 조치를 묶는다.
  `single_bounded_task=fail`, `multiple-coupled-issues`로 제외했다.
- `small-village #51`: 6-commit/19-file solution이다. Root `CLAUDE.md` symlink가
  `AGENTS.md`를 가리켜 parity는 `pass`다. 원문은 position/membership 분리의 대안 A/B와 함께
  reconcile O(N) fetch, heartbeat Map 재생성·re-render, naming cleanup을 별도 후속 기회로
  열거하므로 `multiple-coupled-issues`로 제외했다.
- `Soku #19`: 3-commit/26-file solution이다. 113-entry exact base에 root `AGENTS.md`만 있고
  `CLAUDE.md`가 없어 `instruction-parity-mismatch`로 제외했다. Terminal parity 판정에
  불필요한 boundedness와 나머지 rule은 `unknown`으로 남겼다.

복합 과업 경계가 핵심인 앞의 두 행만 execution
`manual-context-review-2026-07-22`에서 Claude Opus 4.8 읽기 전용 자문으로
교차확인했다(기록 비용 `$0.1283065`). 주 검토자가 issue/PR 원문과 exact Git objects를 다시
대조해 최종 판정을 확정했다. 이 호출은 manual advisory이며 candidate agent execution,
objective quality observation, auto-routing evidence가 아니다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,037 |
| `excluded` | 89 |
| `selected-for-task-authoring` | **4** |
| exact-base parity 판정 | pass 7 / fail 10 / 그 밖은 unknown |
| focused candidate-ledger tests | **17 passed** |
| 전체 unit tests | **270 passed** |

## 2026-07-22 — Python 패키지 책임 경계 정리

평면적인 `src/adaptive_orchestrator/*.py` 구현을 책임별 하위 패키지로 이동했다.

- `core`: domain contract
- `execution`: agent/process/verifier/tool adapter
- `orchestration`: kernel/planning/workflow/escalation
- `routing`: analysis/context/policy/state
- `infrastructure`: configuration/event/history/log/memory/state path
- `experiments`: paired experiment contract와 runner
- `operations`: diagnostics/report/replay/notification/usage
- `interfaces`: CLI/shell/TUI/example

내부 코드와 테스트는 새 canonical import 경로를 사용한다. 기존
`python -m adaptive_orchestrator.cli`, `shell`, `tui`, `example` 명령은 루트의 얇은
호환 모듈이 `interfaces` 구현으로 위임하므로 그대로 유지된다. 루트
`adaptive_orchestrator` 공개 re-export도 유지했다. 호환 위임을 검증하는 전용 테스트
2개를 추가했으며 전체 unit test **269개**가 통과했다.

## 2026-07-22 10차 handoff — 4차 contextual screening과 위임 경계 정리

사전필터의 다음 explicit multilingual 세 행을 처리했다.

- `hsr-warp #12`: 기존 Korean dashboard label을 en/zh/ja로 옮기고 언어권별 공식·통용
  game term을 선택하는 것이 핵심이므로 `translation-only`로 제외했다.
- `filme #391`: deterministic fallback/visibility 외에 quote 문장, rating preset 문구,
  실제 render 비교로 정할 font, 실측 글자수 제한이 모두 필수라 plumbing만 채점하면 원
  candidate를 축소한다. `subjective-only-evaluation`으로 제외했다.
- `doc_parser #288`: GitHub API base `b4b2b17…`가 PR head의 ancestor가 아니어서 그대로
  쓰면 40-file delta가 됐다. Commit graph의 merge-base이자 earliest solution commit parent
  `3107d966…`를 exact base로 확정했고, 이 base-to-head 17-file diff가 GitHub PR snapshot과
  일치함을 확인했다. Pinned root `pyproject.toml`의 MIT 선언과 1,167-entry full tree의
  instruction path 없음으로 license/parity를 통과했다. Issue-derived synthetic XLSX evaluator는
  offline objective 판정이 가능하지만 pinned base-negative/solution-positive와 resource
  재현은 아직 실행하지 않아 `reproducible_within_budget`만 `unknown`, 총 11/12 screening이다.

`doc_parser` task/solution 경계는 Claude 자문으로 교차확인했다. 첫 execution
`doc-parser-review-network-blocked`는 `/tmp` permission 때문에 source 판단 없이
끝났고, workspace snapshot을 읽은 `doc-parser-review-completed`만 내용 자문을
반환했다. 둘 다 manual/ineligible이고 objective quality observation이 없다. 자문은 issue는
bounded지만 PR 전체를 requirement로 소급하면 separable scope라고 구분했으며, 주 검토자는
기존 protocol의 source-issue identity와 solution-breadth precedent를 대조해 screen-forward를
확정했다.

이 사례를 계기로 모델 수동 선택 자체를 routing 성능 데이터로 오인하지 않도록 운영 경계를
바꿨다. 앞으로 주 검토자가 Claude가 적합하다고 판단한 일반 작업·자문은 Claude CLI를 직접
사용한다. 오케스트레이터는 objective evaluator, lifecycle logging, retry/verification 또는
실제 routing 관측이 필요한 실행에만 사용한다. 현재 24-row execution log 중 후기 6건은
명시적으로 `routing_evidence_eligible=false`이고, 기존 18건도 confirmatory policy evidence가
아니다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,035 |
| `excluded` | 91 |
| `selected-for-task-authoring` | **4** |
| exact-base parity 판정 | pass 8 / fail 10 / 그 밖은 unknown |
| focused candidate-ledger tests | **18 passed** |
| 전체 unit tests | **271 passed** |

## 2026-07-22 11차 handoff — prompt-booster #10 선정과 agent-free control

explicit multilingual pool의 다음 우선 후보 `KoreaNirsa/prompt-booster #10`을 source부터
재현성까지 판정했다. 이슈는 native Korean으로 prompt pattern library의 schema,
중복 text reference를 피하는 locale 구조, fail-fast validation, 기본 sample, optimizer
integration, test와 향후 multilingual/agent rendering 확장을 하나의 구현 과제로 명시한다.
주관적 산문 산출물이 아니라 schema field, loader behavior와 optimizer output을 assertion으로
결정할 수 있어 `single_bounded_task`와 `objective_evaluator_feasible`을 통과했다.

PR #34는 이슈를 직접 해결하는 one-commit/9-file 변경이다. GitHub API base
`5f6a045…`가 head `0533e40…`의 ancestor이자 local merge-base임을 확인했다. Exact base tree
`7476e28…`는 28 entries이고 pinned `LICENSE`와 `README`가 Apache-2.0을 선언한다. Full tree에
`AGENTS.md`, `CLAUDE.md`, `AGENTS.override.md` 또는 다른 자동 발견 instruction path가 없어
project instruction parity는 pass다.

Agent 실행 없이 다음 control을 수행했다.

| control | 결과 | wall time |
|---|---:|---:|
| pristine exact-base full suite | 41 passed | 0.11 s |
| solution-head full suite | 47 passed | 0.14 s |
| base + source test hunks negative | 5 passed / 2 failed / 1 import error | 0.08 s |
| head targeted pattern-library + optimizer positive | 13 passed | 0.08 s |

Negative control의 두 assertion failure는 base에 `match_patterns` pipeline step과
`patternMatches` serialization이 없는 이유였고, import error는 `PatternLibrary` 자체가 없는
이유였다. 따라서 환경 파손이 아니라 요구 동작 부재를 검출했다. Source test는 이
screening control의 근거일 뿐, future task의 독립 held-out evaluator로 그대로 쓰지 않는다.
Schema/loader의 `supportedLocales`와 `agentProfiles`도 확인해 이슈의 확장성 요구를 solution이
구조적으로 다룸을 확인했다. 12개 rule이 모두 pass여서 다섯 번째
`selected-for-task-authoring`으로 이동했다.

현재 검증은 focused ledger 19 tests, 전체 unit 272 tests, `jsonschema 4.26.0`
`Draft202012Validator`의 두 schema metaschema와 1,130-row instance를 모두 통과한다. 시스템
기본 `jsonschema 3.2.0`은 Draft 2020-12 validator가 없으므로 정식 결과로 세지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 (변경 없음) |
| `screening` | 1,034 |
| `excluded` | 91 |
| `selected-for-task-authoring` | **5** |
| exact-base parity 판정 | pass 9 / fail 10 / 그 밖은 unknown |
| focused candidate-ledger tests | **19 passed** |
| 전체 unit tests | **272 passed** |

다음 source-screening 순서는 이미 exact base가 알려진 `factlog-academic #342`,
`ChunChuGwan #406`, `swift-tui #18`의 남은 inclusion rule을 먼저 닫고, 그 뒤 아직 base를
읽지 않은 explicit-language 후보로 돌아가는 것이다. 일반 구현·검토를 특정 모델에 맡길
때는 직접 CLI를 사용하고, 오케스트레이터에는 objective evaluator와 검증 명령이 있는
auto-routing 실행만 남긴다.

## 2026-07-22 12차 handoff — base-known 세 후보 종결

11차 handoff에서 지정한 세 후보를 순서대로 닫았다. 결과는 `factlog-academic #342`와
`ChunChuGwan #406` 선정, `swift-tui #18` 제외다. 어떤 candidate agent도 실행하지 않았고,
source screening과 agent-free control만 수행했다.

### `factlog-academic #342`: atomic issue commit으로 선정

PR #352 전체는 여섯 이슈를 묶지만 첫 commit `6a31ec8…`만 #342의 JSONDecodeError를
해결한다. 따라서 solution을 PR 전체가 아니라 이 atomic commit으로 고정했고, parent
`07817b2…` / tree `3f20d12…`, solution tree `5286d5f…`, 변경 파일 2개를 확인했다.
보호 evaluator는 malformed quoted JSON-like argument와 정상 quoted string 두 경우만
검사한다. Base는 0.28초에 원문과 같은 `JSONDecodeError`로 실패했고 atomic solution은
2/2를 0.27초에 통과했다. Exact-base Apache-2.0, `CLAUDE.md`의 `@AGENTS.md` import parity,
나머지 rule까지 12/12가 되어 선정했다.

### `ChunChuGwan #406`: 공개 route 독립 평가로 선정

PR #408의 one-commit base/head와 7-file scope, 616-entry base, pinned MIT를 확인했다.
Root `AGENTS.md`는 Codex에게 `CLAUDE.md` 전체를 SSOT로 읽게 하고, issue 경로의
storage/dashboard/testing 규칙도 같은 canonical index로 전달하므로 task-relevant project
instruction parity가 통과한다.

Publisher CPython 3.12.13 archive SHA-256 `5854aa6e…0b79`, uv 0.11.30 wheel SHA-256
`cc28cb55…80b2`를 고정하고 lockfile 70 packages를 설치했다. 상류 `TestClient`와 고정
AnyIO thread portal은 애플리케이션 동작 전 단계에서 멈췄으므로 final screening control은
solution private helper가 아니라 공개 `/document/{sha256}/{name}` route endpoint를 직접
호출한다. Starlette의 sync iterator scheduling만 inline으로 대체하고 다음을 검사한다.

- 미인증 요청 401;
- S3 full GET과 `bytes=2-5`의 정확한 본문·헤더·range delegation;
- S3 모드에서 `local_path` 호출 0회;
- local mode가 기존 `FileResponse`, attachment, CSP 경계를 유지함.

Mode 0444, 8,451-byte 평가기 SHA-256은
`d79234edccf77e9b1368a29ab929c645cc641e74d7f7cf87e3bedbe268f41c3e`다. Pristine base는
S3 route가 `local_path`를 호출해 read-through materialization을 시도한 이유만으로 1.37초에
실패했고, solution은 1.38초에 전부 통과했다. 두 checkout과 evaluator hash는 변하지 않았다.
12/12가 되어 선정했다.

이 parity 교차검토를 위한 direct Claude CLI는 앞선 두 번의 무출력 종료 뒤, 수정된
재시도에서 176초를 기다린 후 `API Error: Unable to connect to API (ENOTIMP)`를 반환했다.
토큰과 비용은 0이고 Claude 판단은 사용하지 않았다. 앞으로 분석 호출은 최소 5분을
허용하고 30초마다 poll하며, 무출력만으로 실패 처리하지 않는다.

### `swift-tui #18`: 재현성이 아니라 instruction parity로 제외

기존 Swift 6.3.3 Linux build와 90 suites/1,064 tests 통과 측정은 유효하다. 새 full clone으로
exact base `8d63a79…` / tree `56bf597…`, one-commit solution `420da47…` / tree
`9625957…`, 31 files(+1421/−1083)를 재확인했다. Exact base `UNLICENSE`의 blob은
`efb9808…`, content SHA-256은 `b5065838…e6c`다.

하지만 224-entry base에는 root `AGENTS.md`만 있고 `CLAUDE.md`, `AGENTS.override.md` 또는
Claude import가 없다. 이 지침은 access control, public API documentation, test organization,
test naming, validation command를 규정해 #18의 source/document/test refactor에 직접 영향을
준다. Codex만 이를 자동 수신하므로 `instruction-parity-mismatch`로 terminal 제외했다.
상류 테스트 hunk가 내부 타입을 요구해 compile error 171개였다는 evaluator 관찰은 그대로
보존하지만, parity가 이미 terminal이므로 새 evaluator 저술은 진행하지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,031 |
| `excluded` | 92 |
| `selected-for-task-authoring` | **7** |
| exact-base parity 판정 | pass 10 / fail 11 / 그 밖은 unknown |
| focused candidate-ledger tests | **21 passed** |
| 전체 unit tests | **274 passed** |

다음 source-screening은 이미 닫힌 세 후보를 다시 보지 않고, 아직 exact base를 읽지 않은
explicit-language 우선 후보로 돌아간다. Source screening과 global instruction gate는
독립적으로 진행할 수 있지만, 60-candidate ledger와 global gate가 모두 닫히기 전에는
task/evaluator authoring이나 agent 실행으로 넘어가지 않는다.

## 2026-07-22 13차 handoff — MembershipFlow #79 license terminal 제외

12차 handoff의 지시대로 아직 exact base가 없던 explicit-language 후보
`ghmix-ohhalim--MembershipFlow-issue-79`를 먼저 판정했다. 공개 issue의 title, 두 newline,
body SHA-256은 원장에 고정된 `941185cb…f9f9f`와 일치한다. 문제와 구체적인 매핑 예시는
한국어로 작성된 단일 debugging task라 `native-language-source`와
`single-bounded-task`는 통과한다.

Issue timeline에서 #79를 실제로 닫은 merged PR #80을 solution으로 고정했다. PR의 유일한
commit `b848a74…`의 parent는 API base `b2bc8ba…`와 같고,
`MembershipTypeMapper.java` 한 파일만 바꾼다. 이후 PR #84는 이미 #80 commit이 들어간
develop을 main으로 승격하면서 `Closes #79`를 반복한 release PR이므로 별도 gold로 보지
않는다. PR #80 `.diff` SHA-256은 `4eb0a909…18e`, base tree는 `43678ee…f40`,
solution tree는 `5686d22…3fc`다.

Full public clone으로 materialize한 exact base는 155 entries이고 clean했다. 전체 tree에
`AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`가 하나도 없어 두 CLI 모두 candidate-tree
project instruction을 받지 않으므로 parity는 통과한다. 그러나 다음 어느 곳에도 사용
허가가 없다.

- tree 전체: LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE 없음;
- `README.md`: blob `69400e9…`, content SHA-256 `ea37e1c…fcc`, license grant 없음;
- `build.gradle`: blob `432ba68…`, content SHA-256 `fdc4114…561c`, license 선언 없음.

공개 열람 가능성만으로 use basis를 만들지 않는 사전등록 규칙에 따라 evaluator를 만들기
전에 `license-or-use-basis-unavailable`로 terminal 제외했다. 이 판정은 새 사용권을
부여하지 않으며, 저작권자가 나중에 license를 선언하면 기존 행을 소급 수정하지 않고 새
candidate ID와 lineage를 만든다.

동기화 과정에서 `my-sim #10`의 오래된 원장 불일치도 바로잡았다. 이 행은 base revision과
tree가 모두 null인데 `exact_base_resolvable=pass`, license 근거 없이
`license_or_use_basis=fail`이었다. 독립적인 `subjective-only-evaluation` 제외는 그대로
두고 두 무근거 상태만 `unknown`으로 복구했으며, exact-base pass에는 revision과 tree가
반드시 있어야 한다는 회귀 검사를 추가했다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,030 |
| `excluded` | 93 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 61 (local 35 + external 26) |
| exact-base parity 판정 | pass 11 / fail 11 / 그 밖은 unknown |
| focused candidate-ledger tests | **23 passed** |
| 전체 unit tests | **276 passed** |

다음 source-screening은 사전등록된 explicit-language 순서에서 아직 exact base가 없는
`0xkkun/seoul-challenge #30`부터 이어간다. License나 다른 terminal rule이 먼저 실패하면
평가기 저술로 범위를 넓히지 않는다.

## 2026-07-22 14차 handoff — seoul-challenge #30 이중 terminal 제외

`ghmix-0xkkun--seoul-challenge-issue-30`의 공개 원문 SHA-256 `89630da…f4eb`는
원장과 일치했다. 한국어 issue는 `RunController`, demo scene, integration test와 정확한
owned-file 경계를 명시해 단일 native Korean implementation task로 판정했다.

Timeline에서 issue를 닫은 merged PR #44를 solution으로 고정했다. One-commit head
`91cc1b4…`의 parent가 API base `075464d…`와 정확히 같고, materialized diff의 8개 파일도
GitHub PR file inventory와 일치한다. Base tree는 `f9058ee…338`, solution tree는
`ff6e4ad…96f`, PR `.diff` SHA-256은 `356e160…d35c`다. 이후 PR #45는 본문에서 #44의
post-review follow-up이라고 명시하므로 original gold에 합치지 않았다.

Exact base는 146-entry clean tree다. License terminal 근거는 다음과 같다.

- tree 전체에 LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE 없음;
- `README.md`, `project.godot`, `requirements.txt` 어디에도 license grant/declaration 없음;
- 따라서 공개 열람 가능성 외에 pinned revision을 사용할 근거가 없다.

동시에 root `AGENTS.md`만 있고 `CLAUDE.md`나 `AGENTS.override.md`는 없다. 그 파일은
Godot 4.6.3 pin, quick/full gate, neutral naming, Godot MCP/runtime 검증, worktree와 review
workflow를 규정한다. Issue #30도 `AGENTS.md ## Worktree`와 한글 PR/commit 규칙을
명시적으로 요구하고 source/test/demo 작업이 같은 validation 제약을 받으므로, Codex에만
전달되는 지침은 task-relevant하다. 따라서 `license-or-use-basis-unavailable`과
`instruction-parity-mismatch`를 모두 독립 terminal 사유로 기록하고 evaluator를 만들지
않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,029 |
| `excluded` | 94 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 62 (local 35 + external 27) |
| exact-base parity 판정 | pass 11 / fail 12 / 그 밖은 unknown |
| focused candidate-ledger tests | **24 passed** |
| 전체 unit tests | **277 passed** |

다음은 already-base-known evaluator 대기 행을 건너뛰고, 아직 exact base가 없는
explicit-language 순서의 `Gn0lee/oat #410`부터 이어간다. `doc_parser #288`의 evaluator
재현은 source/solution/base/license/parity를 아직 읽지 않은 행들을 먼저 종결한 뒤 돌아온다.

## 2026-07-22 15차 handoff — oat #410 scoped license와 Claude-only 제외

`ghmix-Gn0lee--oat-issue-410`의 title/body SHA-256 `8bc5aa4…60b7`는 원장과
일치했다. Issue는 AI-assisted triage 표기를 갖지만 고정된 한국어 contract 자체가 금융 행의
정보 위계, 포함·제외 범위, 10개 UI 정책, mobile regression 조건을 구체적으로 정한다.
여러 component family를 다루더라도 하나의 일관된 row-layout refactor로 경계가 닫혀 있어
native Korean bounded task 판정은 유지했다.

Merged PR #411은 first commit parent가 API base `b19b34b…`와 같고 reviewer-feedback
second commit까지 모두 #410 범위다. Materialized 14-file diff가 GitHub inventory와
일치해 two-commit head `15c72d5…`를 solution으로 고정했다. Base tree는
`2ea4b5e…6dd`, solution tree는 `b400c2c…d4`, PR `.diff` SHA-256은
`6f43810…5111`이다.

Pinned 717-entry base의 license는 경로 scope를 구분해 판정했다.

- root/application scope에 LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE 없음;
- root `package.json`은 `private: true`이고 license field가 없으며 README grant도 없음;
- `packages/mcp-bridge/LICENSE`와 그 package의 MIT 선언은 별도
  `@oat-app/mcp-bridge`에만 적용되며, PR의 root UI component 14개를 허가하지 않는다.

따라서 root app에는 use basis가 없어 `license-or-use-basis-unavailable`이다. Exact base는
동시에 317-line root `CLAUDE.md`만 갖고 `AGENTS.md`/`AGENTS.override.md`가 없다. 이 파일은
UI-work activation, DESIGN, frontend convention, screen primitive, styling, testing, naming,
privacy와 command 제약을 #410의 React UI/test scope에 직접 전달하므로 Claude-only
task-relevant guidance다. `instruction-parity-mismatch`도 독립 terminal 사유로 기록했고,
visual/component evaluator는 만들지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,028 |
| `excluded` | 95 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 63 (local 35 + external 28) |
| exact-base parity 판정 | pass 11 / fail 13 / 그 밖은 unknown |
| focused candidate-ledger tests | **25 passed** |
| 전체 unit tests | **278 passed** |

다음 unmaterialized explicit-language 후보는 `handokei/subway-now #1465`다. 동일하게
issue hash와 linked solution을 먼저 고정하고 pinned license/parity가 terminal이면 evaluator
저술 전에 종결한다.

## 2026-07-22 16차 handoff — subway-now #1465 API base 정정과 이중 terminal 제외

`ghmix-handokei--subway-now-issue-1465`의 title/body SHA-256 `34c97cb…54a`는 원장과
일치했다. 한국어 issue는 서울 지하철 1–8호선의 역사 환경을 제공 CSV와 정적
`stations.json` 사이에서 교차검증하고, 분류·보정 규칙과 제외 열·노선, 테스트·데이터 검증
기준을 고정한 단일 bounded testing task다.

Merged PR #1467의 현재 API base `b4b4678…`는 head의 ancestor가 아니어서 pre-solution
base로 사용할 수 없었다. Git graph에서 merge-base이자 최초 solution commit의 parent인
`1c73ae5…920`을 exact base로 복원했으며, 이 base-to-head range만 GitHub의 5-file PR
inventory와 일치한다. Three-commit solution은 `c538927…596`, base tree는
`158cfba…d22`, solution tree는 `c0fb21b…8aa`, PR `.diff` SHA-256은
`0486323…185`다.

Pinned 985-entry clean base에는 LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE가 없다. Root
`package.json`은 `private: true`이고 license field가 없으며, README의 ODbL 표기는
OpenStreetMap 지도 데이터 귀속에만 적용돼 repository code나 solution에서 처음 나타난
station-depth CSV의 use basis가 아니다. 따라서 `license-or-use-basis-unavailable`이다.

동시에 exact base에는 287-line root `CLAUDE.md`만 있고 `AGENTS.md`나
`AGENTS.override.md`는 없다. 이 문서의 dev-branch workflow, static-data validation, 100%
coverage, station-name normalization, architecture/test/coding rules는 #1465의 script, fixture,
`stations.json`, 44-test 범위에 직접 적용된다. Claude만 task-relevant project guidance를
받으므로 `instruction-parity-mismatch`도 독립 terminal 사유다. 두 사유가 이미 종결적이라
solution-only CSV를 evaluator fixture로 추출하거나 별도 provenance를 확장하지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,027 |
| `excluded` | 96 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 64 (local 35 + external 29) |
| exact-base parity 판정 | pass 11 / fail 14 / 그 밖은 unknown |
| focused candidate-ledger tests | **26 passed** |
| 전체 unit tests | **279 passed** |

다음 unmaterialized explicit-language 후보는
`prgrms-aibe-devcourse/AIBE5_FinalProject_Team7_JackPot #499`다. 같은 순서로 issue/solution lineage와
exact base를 먼저 고정하고, pinned license와 parity가 terminal이면 evaluator 저술 전에
종결한다.

## 2026-07-22 17차 handoff — JackPot #499 license-only 제외

`ghmix-prgrms-aibe-devcourse--AIBE5_FinalProject_Team7_JackPot-issue-499`의 title/body
SHA-256 `0102718…169f`는 원장과 일치했다. 한국어 contract는 라틴 glyph에는 Roboto Flex,
한글에는 기존 Pretendard fallback을 적용하고 의도적인 serif wordmark는 유지하라고 해
mixed-language typography 동작과 3개 설정 지점을 닫힌 범위로 정한다.

Issue timeline이 직접 연결한 merged PR #500은 one-commit head `e323f65…b4e`이며, sole
parent가 API base `9ae892a…1f8`와 같다. 이 base는 merge-base이자 head ancestor이고,
materialized diff의 `frontend/index.html`, `global.css`, `wireframe.css`가 GitHub의 3-file
inventory와 정확히 일치한다. Base tree는 `6722de4…342`, solution tree는
`2d37ba4…866`, PR `.diff` SHA-256은 `c9e2b6e…7b5`다.

Exact base는 520-entry clean tree이고 전체 경로에
LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE가 없다. Root README, frontend `package.json`,
backend `build.gradle`에도 license grant/declaration이 없어 공개 열람 외의 use basis가 없다.
따라서 `license-or-use-basis-unavailable`로 terminal 제외했다.

반면 exact tree에는 `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`가 전혀 없어 두 CLI 모두
candidate-tree guidance를 받지 않는다. Project instruction parity는 `pass`이며 global
instruction gate는 별도 unresolved 상태다. License가 이미 종결적이므로 webfont runtime
evaluator는 만들지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,026 |
| `excluded` | 97 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 65 (local 35 + external 30) |
| exact-base parity 판정 | pass 12 / fail 14 / 그 밖은 unknown |
| focused candidate-ledger tests | **27 passed** |
| 전체 unit tests | **280 passed** |

다음 unmaterialized explicit-language 후보는 `SKALA-TEAM5/frontend #66`이다. 동일하게
issue hash와 linked solution을 먼저 고정하고 pinned license/parity가 terminal이면 evaluator
저술 전에 종결한다.

## 2026-07-22 18차 handoff — SKALA #66 atomic commit 분리와 license 제외

`ghmix-SKALA-TEAM5--frontend-issue-66`의 title/body SHA-256 `e5f3121…bc84`는 원장과
일치했다. 한국어 issue는 10개 영문 증빙 코드의 한글 표시, 세부내역 기준 그룹화,
접기/펼치기, 미지정 fallback, 중복 유지와 기존 완료 동작을 하나의 TODO sidebar 범위로
명시한다.

Merged PR #69는 #66·#67·#68을 함께 닫아 PR 전체를 gold로 쓸 수 없다. 현재 API base
`b1f7963…ad6`도 head ancestor가 아니며, 앞의 두 commit은 로그인과 챗봇 변경이다. 다만
마지막 commit `7c5dcde…ba2`는 sole parent `0950a8e…fa4`에서
`UsageStatementDetailScreen.tsx` 한 파일만 바꾸며 commit message와 diff가 #66 범위에
정확히 대응한다. 따라서 parent→final-commit만 issue-specific lineage로 고정했다. Base
tree는 `55524f7…6a9`, solution tree는 `1f2a972…d69`, isolated commit `.diff` SHA-256은
`afab6ba…929`다.

Exact base는 68-entry clean tree이고 LICENSE/LICENCE/COPYING/NOTICE/UNLICENSE가 없다.
Root README와 `package.json`에도 license grant/declaration이 없어
`license-or-use-basis-unavailable`로 terminal 제외했다. 전체 tree에
`AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`는 없어 project instruction parity는
`pass`다. License가 이미 종결적이므로 TODO rendering evaluator는 만들지 않았다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` | 1,025 |
| `excluded` | 98 |
| `selected-for-task-authoring` | **7** |
| `exact_base_resolvable=pass` | 66 (local 35 + external 31) |
| exact-base parity 판정 | pass 13 / fail 14 / 그 밖은 unknown |
| focused candidate-ledger tests | **28 passed** |
| 전체 unit tests | **281 passed** |

다음 unmaterialized explicit-language 후보는 `yt010108/kr-gov-job-mcp #51`이다. 동일한
순서로 source/solution/base/license/parity를 판정한다.

## 2026-07-24 19차 handoff — 전체 ledger license-first triage와 cost cascade

단일 issue를 순차적으로 깊게 읽기 전에 현재 후보 전체에 공통으로 적용할 수 있는 저비용
필터를 먼저 쓰도록 순서를 바꿨다. 이는 agent 결과를 보거나 eligibility 기준을 바꾼 protocol
amendment가 아니다. 기존 사전등록이 이미 classifier/default-branch license를 priority cache로
허용하므로, **운영 순서만 비용 증가형 cascade로 고정**했다. 따라서 연구 설계나 논문의
결론을 다시 해석할 필요는 없었다. 이후 어떤 cheap signal을 terminal exclusion으로 바꾸거나
source frame, quota, instruction discovery, eligibility rule을 바꾸려면 그때는 사전등록과
근거 연구를 다시 읽고 amendment를 먼저 작성한다.

현재 `screening` 1,025건을 pool별로 나누면 local history 34, GitHub 691, SWE-bench
Multilingual 300이다. Local 34건은 exact code lineage와 이 저장소의 license는 있지만 native
task statement가 없어 source-adaptation queue로 분리한다. SWE-bench 300건은 base revision과
patch hash는 있으나 base tree와 upstream pinned license가 없고 dataset card MIT가 upstream
code use basis를 대신하지 않으므로, 41개 repository 단위의 dataset-terms/pinned-license
검사가 먼저다.

Frozen license probe는 source pool이 아니라 **repository 단위 관측**이다. 같은 repository가
Korean-bearing/explicit pool 양쪽에 있어도 한 번의 probe를 재사용한다. 이 기준으로 GitHub
screening 691건의 저장소는 모두 probe됐고 결과는 다음과 같다.

| license bucket | rows | 현재 효력 |
|---|---:|---|
| exact pinned permissive pass | 2 | 나머지 rule 심사 가능 |
| permissive classifier | 36 | exact revision 확인 전 nonterminal |
| license-file-only | 66 | license 종류와 exact revision 모두 미확인 |
| GPL-3.0 / AGPL-3.0 classifier | 2 | exact revision 확인 전 제외 아님 |
| `none-observed` | 585 | terminal 부재 근거가 아니므로 보류 |

따라서 license signal만으로도 expensive review의 우선 queue는 691→104건으로 줄었다. 이
104건은 Korean-bearing 31 / explicit multilingual 73, 55 repositories다. 104건 모두 source
statement와 hash는 있지만 base가 알려진 것은 `TimePilot #62`, `doc_parser #288` 두 건뿐이고,
기존 mechanical prefilter가 덮는 행도 1건뿐이다. 나머지 102건에는 같은 값싼
issue-timeline/linked-PR/test-touch prefilter를 확대 적용해야 한다.

[`phase2b-screening-cascade-2026-07-24.json`](../experiments/phase2b-screening-cascade-2026-07-24.json)은
다음 비용 순서를 고정한다.

1. local ledger identity·hash·기존 terminal state;
2. source statement 존재와 adaptation 필요 여부;
3. cached repository license signal;
4. license content만 읽는 종류 분류;
5. issue timeline, linked solution, changed-file와 test-touch metadata;
6. Git graph, exact base/tree와 pinned license;
7. exact-tree project instruction inventory;
8. 마지막에만 boundedness, evaluator feasibility와 agent-free reproduction.

Rank 0–4는 어떤 candidate decision이나 inclusion value도 바꾸지 못한다. Rank 5의 exact
revision evidence부터만 license pass/fail이 가능하다. Default-branch instruction prevalence,
repository language, test-touch와 file count도 계속 priority signal일 뿐 terminal 근거가 아니다.

Claude에는 이 cascade를 로컬 artifact만으로 독립 검산하는 읽기 전용 작업을 맡겼으나 현재
세션의 외부 API가 `ENOTIMP`로 차단돼 비용 `$0`, 파일 변경 없이 실패했다. GitHub DNS도 같은
환경에서 차단돼 remote stage는 수행하지 않았다. 권한을 우회하지 않았으며, 연결 가능한
환경에서 같은 bounded 검산과 rank 3–4 수집을 재개한다.

| 항목 | 값 |
|---|---:|
| 전체 inventory | 1,130 |
| `screening` / `excluded` / `selected` | 1,025 / 98 / 7 |
| GitHub cheap-license deep queue | **104 / 691** |
| GitHub suspected-ineligible exact-confirm queue | 2 |
| GitHub `none-observed` deferred | 585 |
| SWE-bench pinned-license queue | 300 rows / 41 repositories |
| focused candidate-ledger tests | **32 passed** |
| 전체 unit tests | **285 passed** |

다음 작업은 file-only 66건의 license 종류 분류다. 이어서 permissive 36건과 file-only의
허용 subset에 linked-solution/test-scope prefilter를 적용하고, surviving row만 exact Git과
pinned-license 단계로 넘긴다. `yt010108/kr-gov-job-mcp #51`은 `none-observed` 585건의
보류 queue에 있으며 제외되지 않았다.

## 2026-07-24 20차 handoff — file-only license 분류 완료

19차 handoff 뒤 network-enabled sandbox에서 rank 3을 재개했다. Frozen priority artifact의
file-only 후보 66건은 중복을 제거하면 33 repositories다. 각 repository에 대해 `git
ls-remote <repo>.git HEAD`로 관측 시점의 full revision을 고정하고, GitHub repository license
endpoint에 그 SHA를 `ref`로 전달했다. 33/33 HEAD와 33/33 license response를 얻었다. Tracked
artifact에는 repository URL, exact blob URL, HEAD SHA, Git blob SHA, decoded byte length와
content SHA-256만 넣었고 license 원문 전체는 복제하지 않았다.

GitHub SPDX가 직접 분류한 30 repositories는 MIT 26, Apache-2.0 3, GPL-3.0 1이었다.
`NOASSERTION` 3개만 원문을 읽었다. 이 좁은 작업은 Claude CLI에 read-only로 독립 판정을
맡기고 주 검토자가 같은 content hash의 원문을 다시 대조했다. 3/3 결과가 일치했다.

| current-HEAD 분류 | repositories | candidate rows | 다음 route |
|---|---:|---:|---|
| preregistered permissive | 31 | 64 | linked-solution/test-scope prefilter |
| GPL-3.0 suspected ineligible | 1 | 1 | exact candidate revision 확인 |
| PolyForm Noncommercial suspected ineligible | 1 | 1 | exact candidate revision 확인 |
| unknown | 0 | 0 | 없음 |

`lvis-project/lvis-app`과 `yvshdjcsldhdjt/ChunChuGwan`의 `NOASSERTION` body는 표준 MIT grant로
확인됐다. `baekenough/oh-my-customcode`는 PolyForm Noncommercial 1.0.0으로, grant의 permitted
purpose가 noncommercial use로 제한된다. 별도로 `hsu3046/MarkMind`는 GitHub가 GPL-3.0으로
식별했다. 이 네 설명은 **현재 HEAD signal**이며 과거 candidate base의 pass/fail이 아니다.
저작권 조건이 candidate 시점에 달랐을 수 있으므로 exact pre-solution revision을 확인하기
전까지 ledger의 `license_or_use_basis=unknown`, `decision=screening`을 그대로 유지했다.

새 artifact는
[`phase2b-license-file-classification-2026-07-24.json`](../experiments/phase2b-license-file-classification-2026-07-24.json)이며,
input priority artifact hash와 33개 license body integrity를 고정한다. 이에 따라 GitHub 다음
deep-review queue는 104→**102 rows**(Korean-bearing 31 / explicit multilingual 71,
53 repositories)로 줄었다. Suspected-ineligible exact-confirm queue는 기존 GPL/AGPL classifier
2건에 새 GPL-3.0/PolyForm 2건을 더한 **4 rows**다. `none-observed` 585건은 계속 보류다.

Cascade rank 3은 완료됐고 다음 진입점은 rank 4다. 102 rows 중 exact base가 이미 있는 것은
`TimePilot #62`, `doc_parser #288` 두 건이며, 기존 mechanical prefilter가 덮는 것은
`doc_parser #288` 한 건뿐이다. 나머지 100건은 issue timeline에서 direct closing solution,
changed-file count, test-touch와 명백한 multi-issue scope를 값싼 metadata로 먼저 수집한다.
이 단계에서도 issue 의미나 evaluator를 깊게 읽지 않고 candidate decision을 바꾸지 않는다.

이어서 rank 4도 같은 세션에서 완료했다. Eligible current-HEAD queue 102건과
suspected-ineligible confirmation 4건, 합계 106건의 공개 issue HTML을 읽었다. 106/106에서
`closedByPullRequestsReferences`를 복원했고, 103건은 단일 merged closing PR, 3건은 closing
PR이 여러 개였다. 연결된 unique PR 107개의 HTML과 `.diff`도 107/107 성공해 각각 SHA-256,
full head revision, commit count, changed-file count와 test paths를 기록했다. GitHub core API
한도는 이 단계에 쓰지 않았다.

첫 test-path parser가 `docs/specs/`를 test `spec/`으로, `test_cases.md`를 실행 가능한 test로
과잉 분류했다. Claude의 3 multiple-closing candidate + 9 multi-issue PR read-only anomaly
검산과 주 검토자의 전체 test-path 재대조로 이 오탐을 수정했다. 최종 규칙은 정확한
`test|tests|spec|__tests__` directory segment 또는 문서 확장자가 아닌 conventional test
filename만 센다.

| rank 4 next route | rows | 효력 |
|---|---:|---|
| eligible: exact base/pinned license 전진 | 27 | 단일 merged closing PR + test touch + obvious multi-issue 신호 없음 |
| suspected-ineligible exact confirmation | 4 | current-HEAD GPL/AGPL/PolyForm 신호를 candidate revision에서 확인 |
| solution segmentation / multi-issue review | 18 | nonterminal deferred |
| no-test-touch single-scope | 57 | nonterminal deferred |

Tracked 근거는
[`phase2b-linked-solution-prefilter-2026-07-24.json`](../experiments/phase2b-linked-solution-prefilter-2026-07-24.json)이다.
PR 107개의 commit link도 전부 복원했다. 다른 priority PR의 commit set을 포함하는 stacked
superset은 scope-review로 보냈지만, 이후 PR이 쌓였다는 이유만으로 더 작은 self-contained
prefix PR까지 불이익을 주지는 않았다. 이 값싼 overlap filter로 `intellij-plugin-egovframe
#5`와 stacked documentation PR 2건이 추가로 scope-review에 들어갔다.

Eligible advance 27건은 Korean-bearing 9 / explicit multilingual 18, 22 repositories다.
Changed-file count는 기록했지만 사후 threshold를 새로 만들지 않았고, route 안 순서는 frozen
ledger index를 유지했다. `TimePilot #62`는 pinned license가 알려졌어도 test-touch가 없어
보류됐고, `doc_parser #288`만 27건 중 exact base가 이미 알려져 있다. 따라서 rank 5의 현재
work queue는 **31건**, 실제 base reconstruction 미완료는 **30건**이다.

20차 변경의 focused candidate-ledger suite는 **34 tests passed**다. 전체 suite 수치는 문서·
artifact 동기화 뒤 다시 측정해 이 handoff와 상단 resume snapshot을 갱신한다.

## 2026-07-24 21차 handoff — rank 5 exact base와 pinned license 완료

Rank 4가 만든 31건(eligible 27 + suspected-ineligible confirmation 4)을 모두 exact Git
단계로 처리했다. 각 direct closing PR의 전체 commit list를 복원하고, 첫 solution commit의
유일한 parent를 exact pre-solution base로 사용했다. 31/31에서 fetched head가 관측 head와
일치하고, commit sequence ancestry가 연결되며, 첫 commit은 parent가 하나이고, 별도로
해시한 GitHub `.diff`와 base-to-head Git diff의 **complete changed-path set/count**가
일치한다. Git 자체 diff bytes와 GitHub가 렌더링한 diff bytes는 binary/index 표현 차이가
있으므로 동일성을 요구하지 않는다(15/31 byte hash 일치); exact base와 scope 검증에는
31/31 path-set 일치를 사용한다.

Pinned base의 root license/use basis 결과는 다음과 같다.

| exact-base 결과 | rows | rank 5 판정 |
|---|---:|---|
| MIT | 21 | pass |
| Apache-2.0 | 6 | pass |
| GPL-3.0 | 2 | fail |
| AGPL-3.0 | 1 | fail |
| license/use basis 없음 | 1 | fail |

따라서 license pass 27 / fail 4다. Eligible 27건에서는 26 pass / 1 fail, suspected queue
4건에서는 1 pass / 3 fail이었다. 다음 네 행을 exact revision 근거로
`license-or-use-basis-unavailable` terminal 제외했다.

- `ghko-MannaDevelopers--meditation_blossom_frontend-issue-185`: GPL-3.0;
- `ghko-hang-in--tunaRound-issue-131`: AGPL-3.0;
- `ghmix-hsu3046--MarkMind-issue-117`: GPL-3.0;
- `ghmix-landfill--secure-doc-issue-22`: base에 license artifact가 없고 root `README.md`와
  `package.json`에도 license grant/declaration이 없음.

Current-HEAD signal을 terminal로 쓰지 않은 규칙은 실제 반례 두 개로 확인됐다.
`baekenough/oh-my-customcode #1415`는 current HEAD가 PolyForm Noncommercial이지만 exact
candidate base는 MIT라 license를 통과했다. 다만 27-file release PR이므로 선택하지 않고
solution-scope review로 되돌렸다. 반대로 `landfill/secure-doc #22`는 current HEAD가 MIT지만
exact candidate base에는 use basis가 없어 제외됐다. 따라서 current-HEAD 분류는 앞으로도
priority 신호일 뿐이다.

Tracked terminal evidence는
[`phase2b-exact-revision-license-2026-07-24.json`](../experiments/phase2b-exact-revision-license-2026-07-24.json)
(SHA-256 `fabb62de7b5838450d1f7c3c7529543d3238286fa81747bcddd9b2a073db699e`)에,
pre-rank-5 ledger → evidence → post-rank-5 ledger 연결은
[`phase2b-rank5-ledger-application-2026-07-24.json`](../experiments/phase2b-rank5-ledger-application-2026-07-24.json)
(SHA-256 `11ef0cb9a42c4de0dd5fd19144e4134dd843168ba72a21d61e5a759c3d8a5c62`)에
고정했다. 이전 ledger SHA-256은
`b59ff7449f5ebd50c182eeffb72abe9c0231b82dacb915a61c2d61e94c8d9bd2`, 현재 ledger는
`faf4ee88177adc32e97cd331a6700ce55624f56eb0ec2db886126e086639ce2c`다. Agent 결과는
보지 않았고 selected row는 만들지 않았다.

현재 ledger는 screening 1,021 / excluded 102 / selected-for-task-authoring 7이다. Rank 6
입력은 license를 통과하고 scope-review로 돌아가지 않은 26건이다. 이 중
`doc_parser #288`은 exact-tree instruction parity가 이미 pass라 rank 7
evaluator/reproduction만 남고, 나머지 **25건**은 exact-tree instruction inventory가
필요하다. 다음 순서는 25건의 active `AGENTS.md`/`CLAUDE.md`/import-chain inventory,
그 통과 행과 `doc_parser #288`의 boundedness/evaluator/reproduction, 반환된 MIT 행의
solution-scope review다. 설계·eligibility 기준은 바뀌지 않았고 operational screening
순서만 실행했으므로 근거 연구 재해석이나 protocol amendment는 필요하지 않았다.

회귀 검증은 focused candidate-ledger **35 tests**, 전체 suite **288 tests**가 통과했다.

## 2026-07-24 22차 handoff — rank 6 exact-tree instruction parity 완료

Rank 5에서 새로 전진한 25개 exact base를 ignored bare-repository cache에서 다시 열어
`revision^{tree}`를 ledger tree hash와 25/25 대조했다. 전체 tree의 `AGENTS.override.md`,
`AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, `.claude/rules/*.md`를 전수 열거하고, changed
path의 ancestor scope, symlink, 명시적 import/adapter와 path-rule index를 적용했다. Tracked
artifact에는 원문 전체가 아니라 path, Git blob SHA, decoded-content SHA-256, byte count와
effective Claude/Codex chain만 남겼다.

| exact-tree profile | rows | parity |
|---|---:|---|
| 양쪽 CLI가 발견하는 project instruction 없음 | 5 | pass |
| root `CLAUDE.md`가 root `AGENTS.md`를 가리키는 byte-equivalent symlink | 3 | pass |
| `AGENTS.md`가 `CLAUDE.md` SSOT와 같은 path-rule index를 명시적으로 읽게 함 | 1 (`ChunChuGwan #403`) | pass |
| task-active `AGENTS.md`만 존재 | 6 | fail |
| task-active `CLAUDE.md`만 존재 | 8 | fail |
| 공통 root/service 지침 위에 Codex-only 하위 지침이 추가됨 | 2 (`settlement #394`, `mbased #528`) | fail |

따라서 새 batch는 pass 9 / fail 16 / unknown 0이다. Fail 16건은 exact tree에 material
one-sided guidance가 있으므로 사전등록된 `instruction-parity-mismatch`로 terminal 제외했다.
`mbased #528`은 Claude도 root `CLAUDE.md -> AGENTS.md`를 받지만 Codex만 changed
`apps/**`와 `apps/client/**`의 추가 `AGENTS.md`를 받는다. `settlement #394`는 두 agent가
service `CLAUDE.md`와 일곱 rules를 공유하지만 Codex만 authorization 변경에 적용되는 scope,
security, skill-routing 조건을 추가로 받는다. 반면 `ChunChuGwan #403`은 root `AGENTS.md`가
Codex에게 root `CLAUDE.md` SSOT와 동일한 DB/storage/dashboard/testing rule을 읽도록 명시해
통과했다.

Claude CLI에는 문서 stale-value 감사와 복합 parity 세 건의 두 bounded read-only 호출을
맡겼으나 둘 다 장시간 아무 결과를 내지 않아 중단했다. 파일 변경이나 판정 기여는 없었고,
이 사실을 artifact provenance에 기록했다. 판정은 이전 behavioral discovery 측정과 exact
blob 원문을 주 검토자가 대조한 결과다.

Tracked 근거는
[`phase2b-rank6-instruction-parity-2026-07-24.json`](../experiments/phase2b-rank6-instruction-parity-2026-07-24.json)
(SHA-256 `c73e3a9d7886f5686f7446f6bc1c08b6111e182fb4b1e62d1b66c78b28c58279`)과
[`phase2b-rank6-ledger-application-2026-07-24.json`](../experiments/phase2b-rank6-ledger-application-2026-07-24.json)
(SHA-256 `7c8630b36472943136d6a3230aaa5e97e97347d4a32d9c92e40e222b470821a1`)이다.
Pre-rank-6 ledger SHA-256은
`faf4ee88177adc32e97cd331a6700ce55624f56eb0ec2db886126e086639ce2c`, 적용 뒤 ledger는
`228dbbf05ec46a7f94dde40e780bad9b6d64a32944ace5bddb49839f15a1a0f1`다. 당시 rank-6 output
snapshot은 screening 1,005 / excluded 118 / selected-for-task-authoring 7이며 parity 누적 판정은
pass 22 / fail 30 / unknown 1,078이다.

Rank 7은 아래 frozen ledger 순서의 10건만 받는다.

1. `ghko-hissinger--small-village-issue-54`
2. `ghko-yvshdjcsldhdjt--ChunChuGwan-issue-403`
3. `ghmix-jeongsk--daily_stock_analysis-issue-3`
4. `ghmix-JeremyDev87--kratos-issue-64`
5. `ghmix-genonai--doc_parser-issue-288`
6. `ghmix-Sungho-pk42ac--agentguard-issue-687`
7. `ghmix-Sungho-pk42ac--agentguard-issue-591`
8. `ghmix-KoreaNirsa--prompt-booster-issue-3`
9. `ghmix-MTGVim--telltale-issue-11`
10. `ghmix-joshua-jingu-lee--ante-issue-2398`

각 행은 boundedness와 native-language source를 먼저 의미 판정하고, 통과 가능할 때만
objective evaluator/protected-gold/isolation과 agent-free base-negative/solution-positive
reproduction을 수행한다. Agent 결과는 계속 보지 않는다. 설계나 eligibility 기준은 바뀌지
않았으므로 연구 재검토나 protocol amendment는 필요하지 않았다. 회귀 검증은 focused
candidate-ledger **36 tests**, 전체 suite **289 tests**가 통과했다.

## 2026-07-24 23차 handoff — rank 7 의미 필터와 agent-free reproduction 완료

22차 handoff가 고정한 10건만 ledger 순서대로 처리했다. 먼저 source snapshot의 제목+본문
SHA-256을 원장과 10/10 대조하고, runtime을 설치하기 전에 native-source와 boundedness를
판정했다. 그 결과는 다음과 같다.

| route | candidate | 근거 |
|---|---|---|
| terminal `multiple-coupled-issues` | `ChunChuGwan #403` | S3 호출, WebP, migration, batch delete, cache, finalize, streaming, rollout을 독립 수용 기준으로 결합 |
| terminal `translation-only` | `daily_stock_analysis #3` | 기존 중국어 UI 사전을 한국어로 치환하는 localization sweep |
| terminal `translation-only` | `kratos #64` | JSON 동작을 유지한 채 report/Markdown 영문 문구를 한국어로 치환 |
| terminal `translation-only` | `telltale #11` | 핵심 산출물이 기존 사용자 문구의 한국어 번역 |
| reproduction 전진 | `small-village #54`, `doc_parser #288`, `agentguard #687`, `agentguard #591`, `prompt-booster #3`, `ante #2398` | source-derived deterministic invariant/property/test seam과 offline isolation이 존재 |

일곱 개 비자명 행은 Claude CLI의 bounded read-only source review로 교차검토했다. Claude는
명확한 terminal/advance 판정에 동의하고 `small-village #54`, `agentguard #591`,
`ante #2398`을 disagreement-sensitive unknown으로 남겼다. 주 검토자가 exact base와 solution
test seam을 다시 대조해 각각 offline roster/reconcile invariant, 문서의 명시적 output
property contract, base에 이미 존재하는 runtime-readiness prerequisite를 확인한 뒤 전진을
확정했다. Claude는 파일을 수정하지 않았고 candidate agent 결과도 만들거나 보지 않았다.

여섯 survivor는 ignored local worktree와 evaluator 디렉터리에서 exact commit/tree를 원장과
대조한 뒤 같은 protected control로 intended base-negative와 solution-positive를 실행했다.

| candidate | control 결과 | bucket |
|---|---|---:|
| `prompt-booster #3` | base module 부재로 fail, solution source-derived intent 9 assertions pass | small |
| `doc_parser #288` | base direct XLSX module 부재, solution synthetic workbook 5 assertions pass | small |
| `small-village #54` | base context module 부재, solution offline mocked roster/reconcile 7/7 및 broader 20/20 pass | small |
| `ante #2398` | copied byte-identical readiness control base 63/63 fail, solution 63/63 pass | small |
| `agentguard #687` | doctor evidence의 local action path가 base에 없고 solution 10 assertions pass; full suite sequential pass | medium |
| `agentguard #591` | machine-output docs contract가 base에 없고 solution 18 properties pass; full suite sequential pass | medium |

AgentGuard의 처음 concurrent full-suite probe는 `tsx` socket과 duration-test 간섭을 일으켜
증거에서 제외했고, 서로 다른 짧은 `TMPDIR`, writable npm cache, synthetic GitHub ref를 둔
순차 실행만 bucket 근거로 사용했다. 모든 base/solution tracked tree는 control 뒤 clean이며
네 small, 두 medium 모두 `reproducible_within_budget=pass`다. 여섯 행은 12/12 pass로
`selected-for-task-authoring`에 이동했지만 final task/evaluator/manifest는 만들지 않았다.

Tracked evidence와 결합 hash는 다음과 같다.

- `phase2b-rank7-semantic-prefilter-2026-07-24.json`:
  `c197ff0e4e7665710e8d16a89e3f5ff865263d766f9e07b525478aa4f4bad0de`
- `phase2b-rank7-agent-free-reproduction-2026-07-24.json`:
  `71026e607d019671a9b10fc967ba9b9ac7a8d7304fa8542279adce3102066bdd`
- `phase2b-rank7-ledger-application-2026-07-24.json`:
  `a6483444eb1dc40dbfe6f89bf41121c4220908bdd02485b5887c1a0a492d8acc`
- pre-rank-7 ledger:
  `228dbbf05ec46a7f94dde40e780bad9b6d64a32944ace5bddb49839f15a1a0f1`
- 적용 뒤 ledger:
  `09d2e1293fd49d49a6d1b9a3bd2b305c6808262e95de5ce89039b2a8d312b9f9`

현재 수치는 screening 995 / excluded 122 / selected-for-task-authoring 13이다. Rank 7 pending은
0이며 다음 순서는 기존 solution-scope 18건, 그 뒤 `oh-my-customcode #1415` MIT-at-base 반환
행이다. 57개 no-test-touch 행은 보류하고, 이 signal-positive queue 뒤에 SWE-bench 300건을
41개 upstream repository 단위 pinned-license/dataset-terms 필터로 처리한다.

Known limitation은 그대로 남긴다. `small-village #54`의 final validity reviewer는 offline
roster invariant가 source의 hosted three-client E2E 문장을 조용히 축소하지 않는지 확인해야
한다. Managed CPython은 executable hash와 dependency hash lock을 기록했지만 publisher archive
checksum은 보존하지 못했으므로 manifest freeze 전에 재생성·검증해야 한다. 이번 작업은 기존
eligibility를 적용한 operational screening이고 설계 변경이 아니므로 연구 논문 재해석이나
protocol amendment는 필요하지 않았다. 회귀 검증은 focused **37 tests**, 전체 **290 tests**가
통과했다.

## 2026-07-24 24차 handoff — scope-review 19건 종결과 survivor 재현

23차 handoff 뒤의 고정 queue 19건을 저비용 순서대로 모두 처리했다. 먼저 issue source
제목+본문 hash를 ledger와 대조하고 native-source, boundedness, external side effect를
runtime 설치 전에 판정했다. 7건은 source 단계에서 terminal이었다.

| terminal route | candidate |
|---|---|
| `multiple-coupled-issues` | `mbased #499`, `filme #414`, `Soku Convention #3`, `singcode #208` |
| `translation-only` | `BidMate #919`, `BidMate #918`, `oh-my-customcode #1415` |
| 추가 `unsafe-or-external-side-effect` | `BidMate #918`, `oh-my-customcode #1415` |

남은 12건만 public Git lineage를 materialize했다. 모두 exact pre-solution base와
task-relevant path segment를 고정했고 pinned license는 MIT 11 / Apache-2.0 1로 통과했다.
그 뒤 active `AGENTS.md`/`CLAUDE.md` chain을 exact tree에서 판정해 pass 4 / fail 8로
좁혔다. Fail 8은 Claude-only root guidance 7건과 Codex-only root guidance 1건이며
`instruction-parity-mismatch`로 terminal 제외했다. `Wor-chain-dle #130/#173`의 root
`CLAUDE.md -> @AGENTS.md` adapter는 남은 slash-command 설명이 dormant라는 점까지 원문과
read-only Claude CLI 교차검토로 확인해 pass로 유지했다. 후보 agent는 실행하지 않았다.

마지막 네 survivor는 source-derived screening evaluator를 checkout 밖에 두고 exact base와
solution에 byte-identical하게 적용했다.

| candidate | base / solution control | repository health | route |
|---|---|---|---|
| `a2a-nexus #1190` | docs policy 10/10 fail → 10/10 pass | 양쪽 Markdown-link check pass | selected-for-task-authoring |
| `Wor-chain-dle #173` | fixed mode-label 2 tests fail → pass | 양쪽 기존 App 4 tests pass | selected-for-task-authoring |
| `Wor-chain-dle #130` | Patch Notes tab 1 test fail → pass | 양쪽 기존 App 4 tests pass | selected-for-task-authoring |
| `bu-ting-mobile #75` | memo vertical 모듈 부재 fail → 4 tests pass | 양쪽 기존 App test가 동일한 host `RNCWebViewModule` 부재로 collection fail | selected-for-task-authoring |

모바일 후보의 symmetric repository-health failure는 solution 근거로 세지 않았다. 격리 evaluator는
mapper/store/editor, trim/null API 요청, rollback 구조와 카드 preview를 검사했다. 다만 final
evaluator author는 rollback 구조 검사를 mocked API 실패 뒤 이전 값이 실제 복구되는 behavioral
test로 교체해야 한다. 따라서 네 행은 12/12 eligibility pass지만 여전히 task/evaluator authoring
queue일 뿐 final task, manifest, agent 실행 승인이 아니다.

Tracked evidence hash는 다음과 같다.

- source semantic: `9ab7a488ce64d4bdccf6513d605147d8bbf5b8a31711e238644b7de49174f5f3`
- source ledger application: `cdcb3c5407ba5268c399fe3f24385efbb6b3555f723650bf84d6fe239a1073e9`
- solution segmentation: `8930853eca14324a25472b08a4a1f54ab954a0e5f0c9720132b0a8f454831e76`
- exact license: `fb58ac9269c6c28e3aa6ad53a1634d3f64eac0592c406f51414ed7cb2cae7460`
- instruction parity: `1eaedbe8efe316e15649a7f60eb07d1a2900da899d48acc4557099085a643a9b`
- exact/parity ledger application: `058cbf5011c8b5643708845a33c91b49bd43d773d1501dccecf7004005e6aa9f`
- survivor semantic: `d1c5bfb63c33aa43049d2e01ff7256fce5d78a2be7d9c12d42c614ee58c37528`
- survivor reproduction: `63f77f4914f406f07f47bbee400ed473beb8ca3d849ff5ddcb6ef32d96500997`
- survivor ledger application: `fdfd4e8a07744c9c446a92c0db2c83035c9a297eecf3dee5b3e7d4ed99eec458`
- current ledger: `8f71326cc2131cd816c4ef8fbf42eb84a96fdeb0300b357bdec791072306f5d8`

현재 ledger는 screening 976 / excluded 137 / selected-for-task-authoring 17이다. Exact-tree
project instruction 판정 누적은 64건, pass 26 / fail 38이다. 다음 저비용 작업은
SWE-bench 300행을 41개 upstream repository 단위 pinned license와 dataset terms로 먼저
필터하는 것이다. 57개 no-test-touch 행은 test 미접촉만으로 제외하지 않고 보류한다.
이번 작업은 frozen eligibility를 적용한 operational screening이며 설계 변경이나 연구 근거
재해석은 필요하지 않았다. Focused candidate-ledger **40 tests**, 전체 **293 tests**와
`git diff --check`가 통과했다.

## 2026-07-24 25차 handoff — SWE-bench exact dataset terms/base/license 완료

SWE-bench_Multilingual의 pinned revision `2b7aced…`를 다시 fetch해 tree
`1ca2705…`와 README blob `bbc3e2b…`를 확인했다. README SHA-256
`05d5096…`는 MIT, English, test 300행을 선언하며 추가 이용 조건을 포함하지 않는다.
Dataset terms를 upstream code 권리로 소급하지 않고, 41개 저장소 fetch 안에서 서로 다른
300개 base commit/tree를 모두 해석했다.

Exact root license/NOTICE occurrence 373개를 해시·분류했고, Docusaurus의 code/docs 범위는
5개 exact README occurrence/고유 blob 2개로 별도 고정했다. 이어 모든 changed file의
ancestor directory를 재검사해 55개 행에서 task-path license occurrence 61개를 추가했다.
고유 path-scope blob 14개 중 5개는 root inventory에 없던 객체였고, uutils symlink 6개는
root `LICENSE` target blob까지 해석했다. 이 보완은 모두 기존 MIT/Apache-2.0/Unlicense
판정과 일치해 decision을 바꾸지 않았다.

최종 판정은 dataset terms와 exact base 300/300 pass, upstream license 291 pass / 9 fail이다.
Terminal 행은 Terraform BUSL-1.1 5건, Redis RSALv2/SSPLv1 2건, jq의 CC BY 3.0
`docs/` 경로를 바꾸는 2건이다. Dataset MIT는 이 upstream path license를 덮어쓰지 않는다.
291개 pass 행은 `screening`에 남고 candidate agent는 실행하지 않았다.

Tracked evidence hash는 다음과 같다.

- SWE-bench exact license/terms: `9f28bd5e881b8ab0cc17321ef5d65c51d7f2307f2789078cccfb1f64b42a71f9`
- SWE-bench ledger application: `fa768f106c5f8d3c88acb97438be737ce889019dd01d2a70a188952552573982`
- current ledger: `5387689e35319a558aa133b0a9655f4d16469fa4a95c0fa5ba38d39cd59d96c1`
- screening cascade: `e341baa5fc3dec7cc4f2ad292dd8e7537ef15106fdca18d855551ff7c2a295bf`

현재 ledger는 screening 967 / excluded 146 / selected-for-task-authoring 17이다. 다음
저비용 작업은 291개 license-pass exact tree의 task-relevant `AGENTS.md`, `CLAUDE.md`,
symlink/import와 path scope를 수집하는 instruction-parity 단계다. Focused candidate-ledger
**41 tests**, 전체 **294 tests**, JSON/hash chain, `git diff --check`와 공개 경계 scan이
통과했다. 57개 no-test-touch 행은 계속 보류한다.

## 2026-07-24 26차 handoff — SWE-bench exact-tree instruction parity 완료

License를 통과한 SWE-bench 291행을 대상으로, frozen Claude/Codex project-instruction
discovery contract에 따라 서로 다른 exact tree 291개를 전수 검사했다. 중앙 scan은
candidate별 `base_revision^{tree}`를 pinned `base_tree_hash`와 291/291 일치시킨 뒤 leaf
tree-entry 684,580개(min 95 / max 30,223)를 확인했다. 저장소를 97/98/96행의 세 disjoint
read-only shard로 나눈 교차검사도 candidate ID, revision, tree hash, leaf-entry count까지
중앙 결과와 정확히 일치했다.

Exact `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`,
`.claude/rules/**/*.md` entry와 대소문자 변형은 모두 0건이었다. 따라서 symlink/import/
path-rule을 의미 판정할 대상도 없으며, 291행 모두 candidate-tree project instruction
parity를 통과한다. 이 pass는 candidate tree에 한정된다. 서로 다른 Claude/Codex global
instruction 상태를 동등화하거나 isolated empty agent homes으로 격리하는 실행 gate는
여전히 별도 미해결 상태다.

Ledger에는 291행의 `instruction_parity`만 `unknown -> pass`로 적용하고 근거 문장을
추가했다. Decision은 모두 `screening`에 남아 screening 967 / excluded 146 /
selected-for-task-authoring 17이 유지된다. 전체 project-instruction 판정 누적은 355건,
pass 317 / fail 38 / unknown 775다. Candidate agent 결과는 관측하지 않았고, 설계·quota·
terminal rule은 바꾸지 않았다.

Tracked evidence hash는 다음과 같다.

- SWE-bench exact-tree instruction parity: `e2e420657edd5bf32c3235a33abc517543185cd61a2f82dd1b94ece47d6dd3b3`
- SWE-bench parity ledger application: `a9dae068c311fd15917385260f1446be0ad24484e17e56af4f0fb4e4138203df`
- current ledger: `45768bd4df54556dc524d4ee8240fbbe460eb9b1e75d50702b1f70673df9daf2`
- screening cascade: `12ef5681049847c481d9cf1aa2190bb1cfb73894dc890dad98b39f2710b53758`

다음 저비용 작업은 291행의 native-source fidelity와 instance-level task semantics다.
이를 통과한 행에만 evaluator feasibility, isolation, flakiness, resource review 비용을 쓴다.
Focused candidate-ledger **42 tests**, 전체 **295 tests**, Draft7 공통부분 schema, JSON/hash
chain, `git diff --check`와 공개 경계 scan이 통과했다. 57개 no-test-touch 행은 계속 보류한다.

## 2026-07-24 27차 handoff — SWE-bench native-source fidelity 완료

공식 SWE-bench 방법론은 real-world GitHub issue/PR와 English-primary repository 수집을
명시하지만, 이것과 언어 감지만으로는 frozen `native-language-source`의 직접 작성·비번역
요건을 충분히 입증하지 못한다고 보수적으로 판단했다. 따라서 pinned parquet의
`instance_id`에서 resolving PR을 복원하고, 같은 repository의 source issue를 행별로 다시
연결했다. Pinned dataset은 Git tree의 132-byte LFS pointer, LFS OID/size, materialized
parquet payload, official-order 300-row canonical hash를 서로 분리해 재검증했다. 300개 ledger
identity와 statement/solution/test hash mismatch는 0건이었다.

공개 GitHub provenance 조회는 dataset index modulo 3의 98/96/97행 disjoint shard로
병렬화했다. 각 shard는 resolving PR에서 source issue 후보를 얻고 현재 issue의
`title + LF + body + LF`를 재구성하되 raw title/body/HTML은 `/tmp` cache 밖으로 내보내지
않았다. 결과는 98/98, 96/96, 97/97 pass였다. 중앙 재검사는 trimming이나 line-ending
normalization 없이도 291/291 pinned statement SHA-256과 exact match했고, duplicate issue URL,
ambiguous match, unresolved match, pull fetch failure는 모두 0건이었다. 한 Fluentd statement의
작은 일본어 예제는 English instruction 안의 sample이며 translation 판정 근거로 쓰지 않았다.

Ledger에는 291행의 `native_language_source`만 `unknown -> pass`로 적용했다. 동시에 291행
모두에 남아 있던 “native-source와 instruction parity 미검토” 공통 문장을 현재 상태로
결정적으로 교체했다. 다른 screening field, decision, exclusion은 바꾸지 않아 screening
967 / excluded 146 / selected-for-task-authoring 17이 유지된다. Candidate agent 결과는
관측하지 않았고 protocol rule, quota, terminal path도 바꾸지 않았다.

Tracked evidence hash는 다음과 같다.

- SWE-bench native-source fidelity: `c6b4962bce47a5a721a04dcced5db62d03db2d0cffca23cef5cbb4e00cfa6a8e`
- SWE-bench native-source ledger application: `098cd852b2f8b23d7da6391b2eede57c99846818bf0f8d3db21f3b8b48e5b4ed`
- current ledger: `165f65d6569f194321b3b8926a685e9d24579961f2569d935fc34a1390a4a1bd`
- screening cascade: `9c272d370146ff6aa1f7252b3aa4e256b88f1b92ab7729fd2a82d330d9f545ee`

다음 작업은 291행의 `single_bounded_task`와 `objective_evaluator_feasible`을 statement와
protected solution/test hash 경계 안에서 의미 판정하는 것이다. Repository/row shard로
독립 관찰을 병렬화하되 terminal 판정과 ledger mutation은 중앙에서 교차검증한다. 통과
행에만 isolation, hiding, fixture reproduction, flakiness와 resource-budget 비용을 쓴다.
Focused candidate-ledger **43 tests**가 통과했다. 전체 suite와 Draft7 공통부분 schema,
JSON/hash chain, `git diff --check`, 공개 경계 scan은 이 handoff 변경 전체를 대상으로 다시
실행한다.

## 2026-07-24 28차 handoff — SWE-bench boundedness와 evaluator feasibility 검토

27차 handoff의 291행을 곧바로 한 행씩 깊게 실행하지 않고, raw statement·solution·source
test에서 공개 가능한 수치형 shape operand만 추출한 nonterminal triage로 review 순서를
정했다. 네 priority bucket은 28/33/73/157행이다. URL, patch 크기, source-test 존재,
network/ambiguity 단어는 모두 읽기 우선순위일 뿐 pass/fail 근거가 아니며 triage 자체의
`screening_updates`와 terminal exclusion은 비어 있다.

실제 의미 판정은 dataset index modulo 3의 98/96/97행 disjoint shard로 병렬화했다. Frozen
규칙은 파일·LOC·예제 수가 아니라 하나의 top-level outcome과 independently shippable
workstream 경계를 보고 boundedness를 판정하고, 모든 core criterion에 구현 독립적인
deterministic test/invariant/property/integration/held-out seam이 있을 때만 evaluator
feasibility를 통과시키는 것이다. 중앙 검토자는 민감 표시 19행을 source-first로 다시 읽어
18행을 pass로 확정했다. 결과는 boundedness 291 pass / 0 fail / 0 unknown, evaluator
feasibility 290 pass / 0 fail / 1 unknown이다.

유일한 보류는 `swebm-faker-ruby__faker-2705`다. 원문은 생성 password에 digit이 들어가야
한다고 요구하지만, 기본 동작 보장과 이름을 정하지 않은 opt-in parameter를 모두 허용한다.
따라서 bounded task 자체는 pass지만 solution이 택한 API 이름이나 branch를 보호 evaluator가
임의로 강제하면 다른 유효 구현을 오판할 수 있어 evaluator feasibility를 `unknown`으로
유지했다. 이 판단은 설계 규칙을 바꾸지 않으므로 사전등록 amendment나 연구 근거 재해석이
필요하지 않았다.

Ledger partial application은 독립 tri-state field의 기존 precedent를 따른다. 291행의
`single_bounded_task`를 `unknown -> pass`, 해결된 290행의
`objective_evaluator_feasible`만 `unknown -> pass`로 적용하고 Faker evaluator field는
그대로 두었다. 모든 candidate decision과 exclusion list, 967 screening / 146 excluded /
17 selected-for-task-authoring 집계가 불변이며, 역적용하면 pre-semantic ledger SHA-256
`165f65d6569f194321b3b8926a685e9d24579961f2569d935fc34a1390a4a1bd`가 정확히 복원된다.
Task authoring, final evaluator approval, candidate-agent 실행은 여전히 0이며 승인되지 않았다.

Tracked evidence hash는 다음과 같다.

- SWE-bench semantic triage: `4a13dd68aea4d932ee38c242481bbad52485c52472d7be8dc40fd0f28b055578`
- SWE-bench semantic review: `d5efa6bcf1e587993ef62ed663fcee296113669b33bc0a826ee96b146e63ca8a`
- SWE-bench semantic ledger application: `eb12d3c7509ae5bd81e233e20f6ef5cc0276a16f9c59555c6c720d639c3bdaf7`
- current ledger: `d7344dfab4805cdb73fd3c814109be5ff7497eed80747c7b93c00d7b9dc66aad`
- screening cascade: `4c1cc4c4937701f47b23c76973402cd97b5e1e3875ec28e2876ffa3ca3c28907`

Focused candidate-ledger **47 tests**, 전체 **300 tests**가 통과했다. 다음 저비용 작업은
semantic-pass 290행의 isolation, evaluator hiding, fixture health, reproducibility와 resource
budget 검토다. Faker 1행은 별도 semantic adjudication으로 남기며, 57개 no-test-touch
행도 nonterminal 보류를 유지한다. 격리 `jsonschema 4.26.0`의 Draft 2020-12 metaschema와
현재 1,130-row ledger instance, JSON/hash chain, 공개 경계 scan, `git diff --check`도
통과했다. 별도 read-only application audit와 public-boundary audit도 blocking finding 0으로
끝났다. 어느 queue에서도 candidate agent를 실행하지 않는다.

## 5. 다음 구현 작업

### Phase -1 — 추가 오염 차단 (완료)

예상 수정 위치:

```text
src/adaptive_orchestrator/core/domain.py
src/adaptive_orchestrator/infrastructure/logging.py
src/adaptive_orchestrator/infrastructure/history.py
src/adaptive_orchestrator/orchestration/workflow.py
src/adaptive_orchestrator/routing/analysis.py
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
src/adaptive_orchestrator/core/domain.py
src/adaptive_orchestrator/execution/verification.py 또는 새 evaluation.py
src/adaptive_orchestrator/orchestration/workflow.py
src/adaptive_orchestrator/infrastructure/history.py
src/adaptive_orchestrator/interfaces/cli.py
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
src/adaptive_orchestrator/orchestration/workflow.py
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
routing/context.py
routing/policy.py  # 초기에는 context/model 책임도 함께 둘 수 있음
routing/state.py
operations/replay.py
infrastructure/events.py
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
  최초 candidate ledger 뒤 262 tests가 통과했다. 확장 ledger의 264-test 전체 실행은
  2026-07-19에 완주해 통과했고 screening 회귀 테스트를 더해 265 tests가 됐다.
  2026-07-20 기준은 **270 tests**이며 focused ledger tests는 **12개**다.
- 연구 링크는 외부 자료이며 최신 preprint 상태가 바뀔 수 있다.
- 비공개 외부 prior는 공개 근거나 ground truth로 쓰지 않았다. 현재 코드와 공개된
  primary source로 확인한 사실만 구현 진단으로 기록했다.
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
| 2026-07-20 | base tree의 agent instruction 비대칭을 parity 조건으로 취급 | fixture가 두 agent에게 다른 지시를 주면 pilot의 primary estimand인 discordance에 능력 무관 성분이 섞임 |
| 2026-07-20 | CLI instruction discovery는 통념이 아니라 실측으로 판정 | manifest가 pin하는 버전의 실제 동작이 기준이며, 측정 결과 "Claude도 AGENTS.md를 읽는다"는 구제 가설이 거짓으로 확인됨 |
| 2026-07-20 | Codex 절반이 미측정인 동안 parity 기준과 통과 가능 행 수를 확정하지 않음 | Codex가 무엇을 읽는지에 근거가 없어 어떤 기준도 가정 위에 서게 됨. 파일 존재 분포의 균형을 실효 지시의 균형으로 읽지 않는다 |
| 2026-07-20 | `ghmix-` 접두사는 발견 pool의 기록이지 language 분류가 아님 | `anygarden #512`를 사전등록 §4.1 정의(mixed는 identifier만 영어인 경우가 아님)에 따라 native Korean으로 분류 |
| 2026-07-20 | 재현이 끝나도 parity 미증명이면 `reproducible_within_budget`은 `unknown` | ledger가 environment parity를 이 rule에 묶어 둔 기존 기준을 그대로 적용 |
| 2026-07-20 | classifier 기반 license 근거는 소급 정정 대상 | 2026-07-19 규칙 확정 이전 행이 점검되지 않은 채 `pass`로 남아 있었고, 회귀 테스트로 근거에 `base_revision` 포함을 강제 |
| 2026-07-20 | CLI quota를 예약 예산으로 취급 | probe 4회로 Codex가 5일 소진됐고 2a는 Claude quota로 이미 한 행을 잃음 |

## 11. 외부 검토 기록

```text
review execution id: current schema에 없음
failed review: network-blocked
successful review: source-review-completed
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
review: detailed-follow-up-completed
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
failed review: network-blocked (ENOTIMP, $0)
source-aware review: completed
model: claude-opus-4-8
duration: 521.1s
turns: 34
cost: $2.5698165
result: Phase -1 ready, no substantive redesign; doc precision edits only
limitations: Claude web/Bash denied; 최신 원문과 telemetry exact count는 주 검토가 별도 확인

reconciliation review: completed
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
