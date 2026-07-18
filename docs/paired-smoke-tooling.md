# Phase 2a Paired-Smoke Tooling

> 상태: v1 실제 8 execution 완료, v2 contract rehearsal/agent-free dry-run 완료
> manifest schema: 역사적 `paired-smoke-manifest-v1`, 차기 `paired-smoke-manifest-v2`
> assignment rule: `seeded-balanced-sha256-v1`

이 도구는 Claude Code와 Codex를 실행하기 전에 실험 계약과 격리 경계를 검증한다.
`paired dry-run`이라는 이름의 의미는 **agent 실행이 0건**이라는 뜻이다. 대신 exact
base commit만 shallow fetch한 독립 Git checkout 8개를 만들고 base/fixture/evaluator
pin을 확인하므로 filesystem은 변경된다.

## CLI

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired plan \
  experiments/phase2a-smoke-v1.json \
  --workspace-root /protected/paired-workspaces

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired validate \
  experiments/phase2a-smoke-v1.json --source-repository .

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired dry-run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/paired-workspaces

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired analyze \
  experiments/phase2a-smoke-v1.json \
  --control-state-dir /protected/paired-control

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/fresh-paired-run \
  --control-state-dir /protected/fresh-paired-control \
  --confirm-agent-execution
```

`plan`은 manifest만 읽어 seeded assignment와 예정 path 8개를 결정한다. workspace root를
조회하거나 만들지 않으며, 공개 JSON contract는 top-level `workspaces`에 각 path와
task/pair/execution/attempt/agent identity를 싣는다. 같은 입력의 JSON data는 동일하고
후속 `dry-run`이 만드는 path와 일치해야 한다. v2 manifest이면 assertion/task wording과
modified-file allowlist의 preflight coverage도 함께 반환한다.

`validate`는 source repository가 clean하고 manifest의 exact base commit을 보유하는지,
그 commit의 base tree와 task fixture hash가 일치하는지, 외부 read-only evaluator의
artifact hash와 command-derived version이 일치하는지 확인한다. source의 현재 HEAD가
base보다 뒤여도 fixture 검증은 임시 exact-base checkout에서 수행한다.

`dry-run`은 validation 뒤 task별 Claude/Codex checkout을 별도로 만든다. 모든 checkout은
같은 detached commit/tree여야 하고 생성 직후 clean해야 한다. shared Git common dir,
alternates, visible refs가 없어야 하므로 agent가 Git metadata를 통해 다른 실행이나
manifest 이후 commit을 찾을 수 없다. target path가 이미
있으면 덮어쓰지 않고 실패한다. 일부 생성 뒤 오류가 발생하면 이번 호출에서 만든
checkout만 rollback한다. 성공한 dry-run checkout은 감사 대상으로 남으며 `run`은
별도의 fresh workspace root를 사용한다.

`analyze`는 manifest에서 결정적으로 파생한 execution/attempt ID와 protected lifecycle
event를 조인한다. 일반 execution JSONL이나 legacy cohort는 읽지 않는다. overall과 모든
stratum의 evaluator coverage는 관측된 binary pair를 전체 사전 등록 pair로 나누며,
one-sided/incomplete pair를 분모에서 제거하지 않는다. secondary report는 reliability,
attempt/pair evaluator coverage, agent/evaluator/runner wall time, agent별 비용·token
missingness, 수정 파일 관측 여부를 함께 낸다.

`run`은 `--confirm-agent-execution` 없이는 workspace도 만들지 않고 실패한다. 실행 전
manifest의 CLI version pin을 설치된 Claude/Codex CLI와 대조하고, 비어 있는 전용
control-state directory와 fresh workspace root를 요구한다. 각 agent time limit과 전체
wall-time budget을 적용하며 보호 evaluator command는 agent checkout 밖의 absolute
artifact path로 정규화한다. 같은 control log 위에 재실행하거나 dry-run checkout을
reset/reuse하지 않는다. agent infrastructure failure나 evaluator error/timeout은 해당
attempt를 finalized/missing-quality로 남긴 뒤 다음 subprocess 전에 즉시 중단한다.
새 runner가 남기는 finalized event에는 resource observation과 수정 파일 목록도 포함한다.
이 필드 도입 전의 lifecycle log를 분석할 때는 terminal/evaluation duration만 복원하고
비용·token·runner elapsed·수정 파일은 추정하지 않은 결측으로 보고한다.
v2 allowlist와 여덟 attempt의 수정 파일 관측이 모두 있을 때만 전체 unexpected-file
count를 확정한다. 일부 관측이 없으면 관측분 count와 결측 수를 분리하고 전체 값은
null로 둔다.

## Manifest contract

Manifest는 결과를 보기 전에 version control에 커밋한다. Phase 2a validator는 다음을
강제한다.

- 정확히 4개 low-risk task와 Claude Code/Codex 두 agent;
- exact model/reasoning tier/CLI/permission/time-limit/environment epoch;
- exact base revision/tree와 repository-relative fixture path/hash;
- task마다 고유한 objective-quality evaluator ID;
- `binary-single-v1` aggregation과 외부 read-only artifact/version/hash;
- primary/secondary metric, reporting strata, 최소 보고 cell, margin/confidence/interval;
- 최대 8 execution과 resource budget, stopping/pause/exclusion rule;
- 고정 seed와 `seeded-balanced-sha256-v1` order assignment.

첫 smoke의 v1 manifest는 사후 변경하지 않고 계속 재생할 수 있다. 차기 v2 manifest는
각 task에 normalized repository-relative exact path인 `modified_file_allowlist`를 요구하고,
각 evaluator에 다음을 요구한다.

- `assertion_contracts`: assertion ID, evaluator requirement, task contract field, 그 field에
  실제로 포함된 contract text의 비어 있지 않은 목록;
- `assertion_inventory_complete=true`: 목록이 보호 evaluator의 모든 assertion을
  포함한다는 사전 등록 reviewer의 명시적 attestation.

validator는 contract text가 지정한 description/objective/constraints에 실제로 존재하고
ID가 중복되지 않는지는 기계적으로 검증한다. evaluator 코드를 추론해 assertion 목록의
완전성을 증명하지는 않는다. 그 부분은 artifact hash와 함께 검토·attest하는 사람의
책임이며 report의 `review_scope`에도 이 한계를 남긴다. glob은 해석 차이를 만들 수 있어
allowlist에 허용하지 않는다.
v2도 정확히 4개 task를 다루는 Phase 2a smoke schema다. 60-task pilot은 이 audit 원칙을
이어받되 task-count/statistical contract를 일반화한 별도 schema가 필요하다.

Agent order는 seed와 task ID의 SHA-256 rank로 정하고 첫 agent를 교대로 배정한다. 따라서
4-task smoke에서 각 agent가 정확히 두 번 먼저 실행된다. `pair_id`, `execution_id`, agent별
`attempt_id`는 experiment/task/agent identity의 UUIDv5라서 manifest가 같으면 항상 같다.

## Pair projection semantics

각 lifecycle attempt는 `cohort=paired`, `selection_mode=paired_eval`, manifest environment
epoch, 선택 agent 확률 1과 상대 agent 확률 0을 가져야 한다. 두 agent 모두 실행되는
paired benchmark이므로 이 0/1 값은 agent 선택 무작위화가 아니라 각 attempt의 실제
결정을 뜻한다. 무작위화 대상은 agent 실행 순서다. 분석기는 selection sequence와
`pair_id`/order-position metadata가 manifest assignment와 같은지도 확인한다.

Pair 상태는 다음처럼 보존한다.

- `complete`: 양쪽 terminal/finalized가 있고 one-sided execution/quality missing이 없음;
- `one-sided failure`: 한쪽만 completed 또는 한쪽만 objective quality가 관측됨;
- `incomplete`: attempt나 terminal/finalized event가 없음.

Evaluator가 실행되지 않은 failure/timeout은 quality failure 0으로 대체하지 않는다.
대신 pair를 결과에 남기고 quality missing과 reliability failure로 보고한다. 양쪽의 pinned
binary quality가 모두 관측된 pair만 2×2 quality table과 paired risk difference에 들어간다.

Phase 2a report는 pooled/quota diagnostic을 target-workload policy value라고 부르지 않고,
희소 stratum을 `insufficient_data`로 표시한다. CI와 확증 threshold가 아직 없으므로
`promotion_allowed=false`이며 agent 순위를 내리지 않는다.

## 아직 하지 않는 것

- 성공한 checkout의 자동 삭제 또는 재사용 reset;
- exact McNemar/CI와 confirmatory policy promotion;
- 60-task pilot, prospective exploration, IPS/DR.

첫 smoke의 4개 task와 보호 evaluator는 사전 등록되어 validation, agent-free dry run,
실제 8 execution을 통과했다. 8개 objective observation은 모두 무결했지만 task에 없는
JSON key를 요구한 evaluator-contract 불일치 한 건이 발견되어 결과를 agent 순위로
해석하지 않는다. 상세 결과와 후속 gate는
`experiments/results/phase2a-smoke-v1.md`에 있다.

`experiments/phase2a-smoke-v2.json`은 같은 exact base와 보호 evaluator를 사용하는
4-task contract rehearsal이다. 평가기 assertion 23개를 task wording에 명시적으로
매핑하고 v1 양쪽 workspace에서 관측한 task별 수정 파일 합집합을 exact allowlist로
고정했다. negative control, non-mutating plan, clean-source validation, 독립 checkout 8개의
agent-free dry-run과 plan/dry-run path 일치를 통과했다. v2 agent 실행은 아직 승인되거나
시작되지 않았다.

현재 첫 manifest와 canonical evaluator source는 `experiments/`에 있다. evaluated base는
manifest commit보다 이전 commit이며 dry run은 source repository의 현재 branch/ref를
checkout에 전달하지 않고 manifest의 exact base object만 가져온다.
