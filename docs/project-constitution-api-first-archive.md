# Project Constitution — API/Provider First Archive

> 상태: 아카이브. 이 문서는 초기 방향을 보존한다. 현재 기준은 [CLI Agent First Constitution](project-constitution.md)이다.

# Adaptive AI Software Engineering Orchestrator

## 프로젝트 배경과 목표

이 프로젝트는 단순한 AI API Wrapper가 아니라, 소프트웨어 개발 과정에 필요한 지능을 분석하고 적절한 AI 모델·도구·검증 방식을 선택하는 지능형 제어 계층을 목표로 한다.

최종 비전은 Adaptive AI Software Engineering Control Plane 또는 AI Software Engineering Operating System이다.

## 기존 접근 방식의 한계

Single Powerful Model 방식은 모든 작업에 높은 비용이 들고, 특정 능력이 부족할 수 있으며 장기 프로젝트 관리에 적합하지 않다.

Manager, Architect, Developer, Tester처럼 역할을 분리한 Multi-Agent 방식은 문제 분해에는 도움이 되지만 Agent·Token·Context·통신 비용을 늘린다. Role Prompting만으로 전문성이 생기지 않으며, Agent 수 증가가 성능 향상을 보장하지 않는다.

## 핵심 설계 원칙

### Capability 중심

모델 역할을 고정하지 않는다.

```text
Task -> Required Capability Analysis -> Available Intelligence Resource -> Execution
```

Capability 예:

- Repository Understanding
- Code Generation
- Debugging
- Architecture Reasoning
- Research
- Security Review
- Testing
- Optimization
- Planning

### Agent 정의

```text
Agent = Model + Capability + Tools + Memory + Context + Permission + Evaluation
```

### Single Agent First

```text
Single Agent First -> Difficulty / Risk Evaluation -> Escalation -> Multi-Agent Collaboration
```

목표는 가장 강한 모델을 사용하는 것이 아니라, 문제 해결에 필요한 최소 충분 지능을 사용하는 것이다.

## 초기 Kernel 방향

당시 v0.1 목표는 Provider Layer를 통해 Claude, Codex, Gemini, Local Agent를 동일 구조로 연결하는 것이었다.

```text
Task -> Understanding -> Capability Requirement -> Intelligence Allocation -> Execution -> Evaluation -> Learning
```

필요 요소:

- Agent Interface
- Provider Layer
- 구조화된 Task Object
- Tool Runtime
- Execution Logging

## 이후 Roadmap

1. Execution Engine: Planner, Executor, Verifier
2. Engineering Knowledge Memory: Architecture Decision, Design Reasoning, Trade-off, Failure History, Project Constraint, Code Evolution
3. Adaptive Router: Rule-based routing에서 capability/cost/quality matching으로 발전
4. Multi-Agent Orchestration

## 방향 변경 기록

현재 초기 실행 대상은 API가 아닌 로그인된 Claude Code와 Codex CLI이다. 따라서 Provider Layer는 구현 우선순위에서 제외되었고, CLI Agent Adapter와 Process Execution Layer가 Kernel v0.1의 기준 경계가 되었다.
