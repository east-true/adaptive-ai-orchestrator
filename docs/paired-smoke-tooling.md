# Phase 2a Paired-Smoke Tooling

> 상태: dry-run tooling 구현 완료, 실제 4-task manifest와 8 execution은 미실행
> manifest schema: `paired-smoke-manifest-v1`
> assignment rule: `seeded-balanced-sha256-v1`

이 도구는 Claude Code와 Codex를 실행하기 전에 실험 계약과 격리 경계를 검증한다.
`paired dry-run`이라는 이름의 의미는 **agent 실행이 0건**이라는 뜻이다. 대신 실제
detached Git worktree 8개를 만들고 base/fixture/evaluator pin을 확인하므로 filesystem과
Git worktree metadata는 변경된다.

## CLI

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired validate \
  experiments/phase2a-smoke-v1.json --source-repository .

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired dry-run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/paired-workspaces

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired analyze \
  experiments/phase2a-smoke-v1.json \
  --control-state-dir /protected/paired-control
```

`validate`는 source repository가 manifest의 exact base commit에 있고 clean한지,
base tree와 task fixture hash가 일치하는지, 외부 read-only evaluator의 artifact hash와
command-derived version이 일치하는지 확인한다.

`dry-run`은 validation 뒤 task별 Claude/Codex worktree를 별도로 만든다. 모든 worktree는
같은 detached commit/tree여야 하고 생성 직후 clean해야 한다. target path가 이미
있으면 덮어쓰지 않고 실패한다. 일부 생성 뒤 오류가 발생하면 이번 호출에서 만든
worktree만 rollback한다. 성공한 worktree는 실제 smoke를 위해 보존한다.

`analyze`는 manifest에서 결정적으로 파생한 execution/attempt ID와 protected lifecycle
event를 조인한다. 일반 execution JSONL이나 legacy cohort는 읽지 않는다.

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

- 실제 Claude/Codex 8 execution과 evaluator 실행;
- 성공한 worktree의 자동 삭제 또는 재사용 reset;
- exact McNemar/CI와 confirmatory policy promotion;
- 60-task pilot, prospective exploration, IPS/DR.

실제 smoke는 4개 task와 보호 evaluator를 사전 등록하고 dry run report를 검토한 뒤 별도
실행 범위로 시작한다.
