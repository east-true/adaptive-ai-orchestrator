# Intra-Vendor Model Tier Routing — 설계 탐색 (미구현)

> 상태: 탐색만 함, 구현 결정 아님
> 기준일: 2026-07-20
> 관련 문서: [architecture](architecture.md), [Evidence-First Stratified Temporal Routing](adaptive-routing-v2.md),
> [Claude 독립 검토](routing-claude-review.md), [project-constitution](project-constitution.md) Phase 4

## 0. 배경

"작업 난이도에 따라 같은 벤더 안에서(opus ↔ sonnet처럼) 모델 티어를 자동으로 오가는
기능이 있는가"라는 질문에서 출발한다. 현재 답은 없음이다:

- `AdaptiveRouter`가 자동으로 고르는 건 **벤더 간**(Claude Code vs Codex) 선택뿐이다.
- `ProjectConfig.claude_model`은 슬롯이 하나뿐이라(`configuration.py`), 같은 벤더 안에
  여러 모델을 후보로 등록하는 것 자체가 지금 데이터 구조로 표현되지 않는다.
- 문서와 코드에 나오는 `tier`는 전부 증거 집계용 통계 백오프 개념
  (`adaptive-routing-v2.md`의 exact-tier → base-vendor → environment shrinkage)이지,
  런타임에 "이 작업엔 이 tier"를 고르는 선택 로직이 아니다.

이 문서는 그 기능을 실제로 넣는다면 무엇이 걸리는지 미리 정리해 둔 탐색 기록이다.
지금 구현하기로 결정한 것은 아니다.

## 1. 목표 / 비목표

**목표:** 같은 벤더 안에서 여러 모델 variant(예: `haiku`/`sonnet`/`opus`,
Codex의 `reasoning_effort` low/high)를 auto 모드의 후보로 등록하고, task 신호와
과거 실행 이력으로 자동 선택한다.

**비목표:**

- Phase 5(Multi-Agent Orchestration)와 다르다 — 여전히 한 번에 한 에이전트만
  실행하는 single-agent-first 범위 안이며, project-constitution.md Phase 4
  (Adaptive Router)의 확장으로 본다.
- API/SDK 직접 호출을 추가하는 것이 아니다 — 여전히 기존 CLI adapter 경로를 쓴다.

## 2. 지금 하지 않는 이유

**a) Cold-start/증거 부족 문제가 후보 수만큼 심해진다.** 벤더 간 라우팅조차
`adaptive-routing-progress.md` 기준으로 표본이 적어 아직 정책 우열을 말할 수
없는 상태다. variant를 늘리면 각 (모델, reasoning effort) 조합마다 별도 이력이
쌓여야 하고, 이는 `adaptive-routing-v2.md`가 아직 완성 중인
exact-tier → base-vendor → environment backoff 계층에 그대로 의존한다. 그 인프라
없이 tier 후보만 늘리면 표본 부족이 오히려 더 악화된다.

**b) difficulty 휴리스틱을 tier 선택 신호로 쓰는 건 이미 한 번 데인 패턴이다.**
`architecture.md`에 기록된 실제 사례: 텍스트 길이·키워드 카테고리 수만으로
difficulty가 최대치(5)까지 튀고, "credential"이라는 단어 하나로 risk가 튀었던
버그가 있었다. 같은 부정확한 difficulty 신호를 "그러니 opus를 자동으로 써라"는
결정에 연결하면, 실패 유형이 하나 더 생긴다 — 오분류 시 쉬운 작업에 비싼 모델을
낭비하거나, 반대로 어려운 작업에 싼 모델을 배정하는 리스크가 생긴다.

**c) 미검증 prior 고정 금지 원칙과 충돌한다.** Phase -1이 `legacy-biased` 정책의
확산을 막기 위해 `routing_evidence_eligible` 플래그로 오염을 격리했다. 검증되지
않은 "opus가 sonnet보다 낫다" 같은 prior를 tier 축에 못박고 시작하면, 벤더 간
라우팅에서 이미 지적된 것과 같은 종류의 실수를 반복하게 된다.

## 3. 만약 한다면 — 설계 스케치

### 3.1 설정 스키마 확장 (예시, 미확정)

현재:

```json
"models": {"claude": null, "codex": null, "codex_reasoning_effort": null}
```

확장안:

```json
"models": {
  "claude": ["haiku", "sonnet", "opus"],
  "codex": [
    {"model": "gpt-5.5", "reasoning_effort": "low"},
    {"model": "gpt-5.5", "reasoning_effort": "high"}
  ]
}
```

`--agent claude-code:opus`처럼 정확한 variant를 명시적으로 pin하는 기존 경로는
그대로 유지한다. 리스트 확장은 `--agent auto`일 때만 후보 확장에 쓰인다.

### 3.2 후보 생성

`_configured_agents()`(`cli.py`)가 벤더당 정확히 1개 인스턴스를 반환하는 대신,
설정된 variant마다 하나씩 `ClaudeCodeAgent`/`CodexAgent` 인스턴스를 만들어
리스트로 반환하도록 바꾼다. `AdaptiveRouter.select`는 이미 임의 개수의 capable
후보를 스코어링하도록 돼 있어 그 자체는 큰 변경이 아니다 — 후보 생성 지점만
확장하면 된다.

### 3.3 스코어링 신호

- 기존 capability affinity + 표본 수 가중 이력을 그대로 재사용한다.
- `cost_limit_usd`가 설정된 경우의 비용 페널티도 그대로 적용 가능하다(Claude만
  비용이 관측되는 기존 비대칭은 tier 축에도 남는다).
- difficulty를 tier 선택에 직접 연결하는 규칙은 넣지 않는다(2-b 이유). 대신
  이력 기반 성적이 쌓이면 어려운 task 유형에서 상위 tier가 자연히 더 높은
  점수를 받도록 유도한다 — 정적 prior가 아니라 관측 증거로 수렴시킨다는
  현재 라우터 철학과 동일하다.

### 3.4 이력 버킷

exact variant ID(`claude-code:opus` 등) 단위로 이력을 쌓되, backoff 계층이
완성되기 전까지는 표본 부족 시 base vendor 수준 이력으로 fallback한다. 즉 이
기능은 독립적으로 먼저 구현할 게 아니라 `adaptive-routing-v2.md`의 backoff
인프라가 선행돼야 의미가 있다.

## 4. 결론

지금은 구현하지 않는다. 선행조건(backoff 인프라, 표본 확보)이 갖춰지기 전에
tier 후보만 늘리면 legacy adaptive router가 이미 겪은 것과 같은 종류의 미검증
prior 문제를 tier 축에서 반복하게 된다. Phase 4 확장 후보로 기록만 해 둔다.
