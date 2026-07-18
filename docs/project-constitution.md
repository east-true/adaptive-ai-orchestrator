# Project Constitution
# Adaptive AI Software Engineering Orchestrator
# CLI Agent First Architecture

## 1. 프로젝트 목표

우리는 단순한 LLM API Wrapper나 Multi-Agent Framework를 만드는 것이 아니다.

최종 목표는:

Adaptive AI Software Engineering Orchestrator

이다.

이 시스템은 여러 AI Coding Agent를 관리하고,
소프트웨어 개발 작업을 분석하여,
적절한 AI Agent, 실행 방식, 검증 과정, 비용 효율을 결정하는 운영 계층이다.

## 2. 현재 개발 방향

현재 단계에서는 LLM SDK나 API 기반 접근을 사용하지 않는다.

우리가 먼저 사용하는 대상:

- Claude Code
- Codex CLI

이다.

이들은 이미 다음 기능을 제공한다.

- 사용자 인증
- Subscription 계정 로그인
- 모델 호출
- 코드 수정
- Terminal 사용
- File System 접근
- Git Workflow

따라서 초기 목표는:

```text
Orchestrator
    |
    |
Claude Code / Codex CLI
```

를 제어하는 구조를 만드는 것이다.

초기 구조:

```text
Linux Machine
|
Orchestrator
|
+----------------+
|                |
Claude Code      Codex CLI
Subscription     Subscription
|
Project Repository
```

## 3. 프로젝트 발전 이유

현재 AI 개발 방식의 문제:

하나의 AI 모델만 사용하는 경우:

- 모든 작업에 높은 비용 발생
- 특정 영역의 약점 존재
- 복잡한 프로젝트 관리 부족

여러 Agent를 무조건 사용하는 경우:

- Token 증가
- Context 증가
- Communication 비용 증가
- 복잡성 증가

따라서 목표는 “많은 Agent를 만드는 것”이 아니다.

목표는 “현재 문제에 필요한 지능을 선택하고 조합하는 시스템”이다.

## 4. 핵심 설계 철학

### 4.1 Agent는 단순한 역할이 아니다

다음과 같이 고정하지 않는다.

```text
Claude = Architect
Codex = Developer
```

대신:

```text
Task
↓
Required Capability
↓
Available Agent
↓
Execution
```

구조로 판단한다.

Agent는 다음 요소의 조합이다.

```text
Agent =
Model/CLI Tool
+
Capability
+
Tools
+
Context
+
Memory
+
Permission
+
Evaluation
```

## 5. Multi-Agent 전략

Multi-Agent를 기본값으로 사용하지 않는다.

기본 전략:

```text
Single Agent First
↓
Task Difficulty Analysis
↓
Need Additional Intelligence?
↓
Multi-Agent Collaboration
```

작은 작업은 하나의 Agent를 사용하고, 복잡한 작업만 여러 Agent를 사용한다.

목표는 최고 성능이 아니라 최소 충분 지능으로 문제를 해결하는 것이다.

## 6. 출발 단계와 현재 구현

이 constitution을 처음 작성했을 때는 최종 Orchestrator가 아니라 CLI 기반
Orchestrator Kernel v0.1을 만드는 단계였다.

당시 출발 상태:

- Router 없음
- Multi-Agent 없음
- API Integration 없음
- Memory 없음

현재 구현에는 deterministic `AdaptiveRouter`, conditional one-agent escalation,
`EngineeringMemoryStore`가 있다. 다만 objective-quality evidence가 충분한 adaptive
policy와 독립적인 multi-agent collaboration/voting, API integration은 아직 없다.
초기 목록은 역사적 baseline이며 현재 기능 목록으로 해석하지 않는다.

## 7. 왜 Kernel부터 만드는가

잘못된 접근:

```text
User
↓
Router
↓
Claude API
↓
Codex API
```

이것은 단순 API Router이다.

우리가 원하는 구조:

```text
Task
↓
Understanding
↓
Capability Analysis
↓
Agent Selection
↓
Execution
↓
Verification
↓
Learning
```

따라서 먼저 실행 기반을 만든다.

## 8. Phase 1 구현 목표

목표는 Claude Code와 Codex CLI를 제어하는 최소 Orchestrator이다.

### 8.1 Agent Interface

모든 Agent는 동일한 인터페이스를 가진다.

```python
class Agent:
    def execute(task):
        pass
```

향후 ClaudeCodeAgent, CodexAgent, GeminiAgent, LocalAgent를 추가할 수 있어야 한다.

### 8.2 CLI Agent Adapter

초기 Agent는 API가 아니라 CLI 실행 기반이다.

```text
Orchestrator -> ClaudeCodeAgent -> claude CLI 실행
Orchestrator -> CodexAgent -> codex CLI 실행
```

### 8.3 Process Execution Layer

담당:

- CLI 실행
- 입력 전달
- 출력 수집
- Error 처리
- Timeout 관리
- 실행 상태 관리

```text
Task -> Executor -> Agent -> CLI Process -> Result
```

### 8.4 Task Object

모든 작업은 구조화한다.

Task 필드:

- description
- objective
- context
- constraints
- required_capability
- priority
- time_limit
- cost_limit

예:

```text
Task: 로그인 오류 수정
Required Capability:
- Repository Understanding
- Debugging
- Testing
```

### 8.5 Logging System

모든 실행 기록을 저장한다.

저장 항목:

- Task
- Agent
- Prompt
- Execution Time
- Result
- Error
- Modified Files
- Git Diff

이 데이터는 이후 Agent Selection, Optimization, Evaluation에 사용한다.

## 9. Repository 구조 예시

```text
orchestrator/
    core/
        orchestrator.py
        task.py
        agent.py
    agents/
        base_agent.py
        claude_code_agent.py
        codex_agent.py
    executor/
        process_runner.py
    memory/
        execution_history.py
    logs/
    cli.py
```

## 10. 이후 Roadmap

> 구현 상태(2026-07-17): Phase 1의 최소 Kernel, Phase 2의 structured plan/verification,
> Phase 3의 explicit engineering memory는 구현됐다. Phase 4의 heuristic adaptive
> router는 일부 구현됐지만 신뢰 가능한 objective-quality evidence와 학습 정책은
> 아직 없으며, Phase 5와 Phase 6은 미래 범위다. 현재 구현의 정확한 상태는
> [README](../README.md), [architecture](architecture.md),
> [adaptive-routing progress](adaptive-routing-progress.md)를 기준으로 한다.

### Phase 2: Task Planning Engine

```text
Planner -> Executor -> Verifier
```

### Phase 3: Memory System

단순 Chat History가 아닌 Engineering Knowledge Memory를 만든다.

저장:

- Architecture Decision
- Design Reasoning
- Failure History
- Trade-off
- Project Context
- Code Evolution

### Phase 4: Adaptive Router

```text
Task Analysis -> Capability Requirement -> Agent Capability Matching -> Execution
```

### Phase 5: Multi-Agent Orchestration

```text
Orchestrator
|
+ Claude Code
+ Codex CLI
+ Other AI Agent
+ Local Model
```

### Phase 6: API / SDK Integration

필요하면 Anthropic API, OpenAI API, Gemini API, Local LLM을 추가한다.

중요: API Integration은 처음부터 만드는 것이 아니라 CLI Agent Orchestration 이후 추가한다.

## 11. 개발 원칙

항상 다음 순서로 진행한다.

```text
Architecture Decision
↓
Implementation
↓
Test
↓
Review
↓
Improvement
```

코드를 작성하기 전에 반드시 다음을 설명한다.

1. 해결하려는 문제
2. 가능한 설계 방법
3. 선택한 방법
4. 장단점
5. 미래 확장성

## 12. 절대 하지 말 것

1. 처음부터 거대한 Multi-Agent Framework 만들지 않는다.
2. Claude와 Codex 역할을 고정하지 않는다.
3. 단순 CLI Wrapper에서 끝내지 않는다.
4. 특정 AI 서비스에 종속되지 않는다.
5. 장기 확장성을 희생하지 않는다.

## 13. 첫 번째 작업 요청

현재 목표는 CLI 기반 Adaptive AI Software Engineering Orchestrator Kernel v0.1이다.

수행:

1. 기술 스택 선택
2. 선택 이유 설명
3. Repository 구조 설계
4. Agent Interface 구현
5. Claude Code Adapter 구현
6. Codex CLI Adapter 구현
7. Process Execution Layer 구현
8. Task Schema 구현
9. Logging 구현
10. 최소 동작 Prototype 작성
11. 테스트 작성

구현 후 반드시 설명:

- 왜 이 구조를 선택했는가
- 현재 한계는 무엇인가
- 다음 발전 방향은 무엇인가

## 최종 비전

이 프로젝트는 “Claude Code와 Codex를 실행하는 프로그램”이 아니다.

최종 목표는 AI Software Engineering Intelligence Operating System이다.

즉, AI를 사용하는 것이 아니라 AI를 선택하고, 조율하고, 검증하고, 개선하는 시스템을 만든다.

모든 구현 결정은 이 장기 목표와 일치해야 한다.
