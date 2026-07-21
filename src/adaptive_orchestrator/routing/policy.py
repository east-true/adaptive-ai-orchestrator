from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from adaptive_orchestrator.core.domain import Capability, Task
from adaptive_orchestrator.execution.agents import Agent
from adaptive_orchestrator.infrastructure.history import AgentMetrics, ExecutionHistory
from adaptive_orchestrator.orchestration.planning import ExecutionPlan
from adaptive_orchestrator.routing.analysis import AdaptiveRouter, TaskAnalysis, TaskAnalyzer
from adaptive_orchestrator.routing.context import RoutingContext, RoutingContextBuilder
from adaptive_orchestrator.routing.state import RoutingState


class CorrectedStaticRouter:
    """Corrected L0: explicit baseline, required-capability eligibility, no skill claim."""

    policy_version = "corrected-static-l0-v1"

    def __init__(
        self,
        analyzer: TaskAnalyzer,
        baseline_agent_id: str,
        *,
        objective_evaluator_available: bool = False,
        constraint_evaluator_count: int = 0,
        environment_epoch: str = "default-v1",
    ) -> None:
        if not baseline_agent_id.strip():
            raise ValueError("Corrected static routing requires a configured baseline agent.")
        self._analyzer = analyzer
        self._baseline_agent_id = baseline_agent_id
        self._objective_evaluator_available = objective_evaluator_available
        self._constraint_evaluator_count = constraint_evaluator_count
        self._environment_epoch = environment_epoch
        self._context_builder = RoutingContextBuilder()

    def policy_config(self) -> dict[str, object]:
        return {
            "selector": "corrected-static-l0",
            "baseline_agent_id": self._baseline_agent_id,
            "eligibility": "required-capabilities-only",
            "inferred_capabilities": "context-only",
            "vendor_skill_prior": None,
            "environment_epoch": self._environment_epoch,
        }

    def select(self, task: Task, agents: Iterable[Agent], requested_agent_id: str = "auto") -> ExecutionPlan:
        analysis = self._analyzer.analyze(task)
        available = tuple(agents)
        known = {agent.agent_id for agent in available}
        eligible = tuple(agent for agent in available if agent.supports(task.required_capabilities))
        eligible_ids = {agent.agent_id for agent in eligible}
        selected_id = requested_agent_id if requested_agent_id != "auto" else self._baseline_agent_id
        if selected_id not in known:
            label = "Requested" if requested_agent_id != "auto" else "Configured baseline"
            raise ValueError(f"{label} agent is not registered: {selected_id}")
        if selected_id not in eligible_ids:
            raise ValueError(f"Agent cannot satisfy explicitly required capabilities: {selected_id}")

        context = self._build_context(task, analysis)
        candidate_scores = {
            agent.agent_id: {
                "score": None,
                "measured_samples": 0,
                "static_prior": False,
                "selection_basis": "configured_baseline" if agent.agent_id == selected_id else "eligible_not_selected",
            }
            for agent in sorted(eligible, key=lambda item: item.agent_id)
        }
        decision = {
            "requested_agent": requested_agent_id,
            "selected_agent": selected_id,
            "candidate_scores": candidate_scores,
            "routing_context": context.as_dict(),
            "rationale": "Selected the explicit configured baseline; no vendor skill difference was inferred before paired evidence.",
        }
        return ExecutionPlan(task, selected_id, decision["rationale"], analysis.as_dict(), decision)

    def _build_context(self, task: Task, analysis: TaskAnalysis) -> RoutingContext:
        return self._context_builder.build(
            task,
            inferred_capabilities=analysis.inferred_capabilities,
            difficulty=analysis.difficulty,
            risk=analysis.risk,
            uncertainty=analysis.uncertainty,
            objective_evaluator_available=self._objective_evaluator_available,
            constraint_evaluator_count=self._constraint_evaluator_count,
            environment_epoch=self._environment_epoch,
        )


@dataclass(frozen=True, slots=True)
class _QualityEvidence:
    successes: int = 0
    failures: int = 0
    backoff_level: str = "none"

    @property
    def samples(self) -> int:
        return self.successes + self.failures

    @property
    def posterior_mean(self) -> float:
        return (1 + self.successes) / (2 + self.samples)


class ShadowBaselineEvaluator:
    """Execution-free baselines using only typed objective quality from allowed cohorts."""

    evidence_cohorts = frozenset({"paired", "prospective"})

    def __init__(
        self,
        history: ExecutionHistory,
        configured_baseline: str | None,
        seed: int,
        environment_epoch: str,
        routing_state: RoutingState | None = None,
    ) -> None:
        self._history = history
        self._configured_baseline = configured_baseline
        self._seed = seed
        self._environment_epoch = environment_epoch
        self._routing_state = routing_state

    def evaluate(self, context: RoutingContext, eligible: tuple[Agent, ...]) -> dict[str, object]:
        eligible_by_id = {agent.agent_id: agent for agent in eligible}
        decisions: dict[str, object] = {}
        for base_id in ("claude-code", "codex"):
            candidate = next((agent.agent_id for agent in eligible if agent.base_id == base_id), None)
            decisions[f"always-{base_id}"] = _shadow_choice(candidate, "eligible base agent" if candidate else "no eligible base agent")

        static_candidate = self._configured_baseline if self._configured_baseline in eligible_by_id else None
        decisions["corrected-static"] = _shadow_choice(
            static_candidate,
            "configured baseline" if static_candidate else "configured baseline unavailable or ineligible",
        )

        global_evidence = {
            agent.agent_id: self._evidence_for(agent, context=None)
            for agent in eligible
        }
        decisions["best-single"] = self._best_evidence_choice(global_evidence)

        stratified_evidence = {
            agent.agent_id: self._evidence_for(agent, context=context)
            for agent in eligible
        }
        decisions["stratified-beta-greedy"] = self._best_evidence_choice(stratified_evidence)

        if context.risk <= 1 and context.objective_evaluator_available and eligible:
            stable_material = json.dumps({
                "seed": self._seed,
                "context": context.as_dict(),
                "eligible": sorted(eligible_by_id),
            }, sort_keys=True, separators=(",", ":"))
            draw_id = hashlib.sha256(stable_material.encode("utf-8")).hexdigest()
            chooser = random.Random(int(draw_id[:16], 16))
            selected = chooser.choice(sorted(eligible_by_id))
            decisions["random-safe"] = {
                "available": True,
                "selected_agent": selected,
                "candidate_probabilities": {agent_id: 1 / len(eligible_by_id) for agent_id in sorted(eligible_by_id)},
                "random_draw_id": draw_id,
                "shadow_only": True,
            }
        else:
            decisions["random-safe"] = {
                "available": False,
                "reason": "requires low risk, objective evaluator, and eligible candidates",
                "shadow_only": True,
            }
        return decisions

    def _evidence_for(self, agent: Agent, context: RoutingContext | None) -> _QualityEvidence:
        levels = []
        if context is not None:
            levels.extend((
                (agent.agent_id, False, True, "exact-agent-task-language"),
                (agent.agent_id, False, False, "exact-agent-task"),
                (agent.agent_id, False, None, "exact-agent-global"),
                (agent.base_id, True, True, "base-agent-task-language"),
                (agent.base_id, True, False, "base-agent-task"),
                (agent.base_id, True, None, "base-agent-global"),
            ))
        else:
            levels.extend((
                (agent.agent_id, False, None, "exact-agent-environment"),
                (agent.base_id, True, None, "base-agent-environment"),
            ))
        for agent_id, match_base, stratum_level, label in levels:
            evidence = self._collect(agent_id, context, match_base=match_base, stratum_level=stratum_level)
            if evidence.samples:
                return _QualityEvidence(evidence.successes, evidence.failures, label)
        return _QualityEvidence()

    def _collect(
        self,
        agent_id: str,
        context: RoutingContext | None,
        match_base: bool = False,
        stratum_level: bool | None = None,
    ) -> _QualityEvidence:
        successes = 0
        failures = 0
        for item in self._evidence_records():
            observed_id = item.get("agent_base_id", item.get("agent_id")) if match_base else item.get("agent_id")
            if observed_id != agent_id or item.get("cohort") not in self.evidence_cohorts:
                continue
            if item.get("environment_epoch") != self._environment_epoch:
                continue
            if context is not None and stratum_level is not None:
                recorded_context = item.get("routing_context") or {}
                if recorded_context.get("task_category") != context.task_category:
                    continue
                if stratum_level and recorded_context.get("instruction_language") != context.instruction_language:
                    continue
            quality = [
                result
                for result in item.get("evaluations") or ()
                if isinstance(result, dict)
                and result.get("role") == "quality"
                and result.get("observed") is True
                and isinstance(result.get("score"), (int, float))
                and not isinstance(result.get("score"), bool)
                and float(result["score"]) in {0.0, 1.0}
                and result.get("artifact_integrity_verified") is not False
            ]
            # Until a versioned aggregation rule exists, only unambiguous
            # single-evaluator binary outcomes may update a baseline.
            if len(quality) != 1:
                continue
            if float(quality[0]["score"]) == 1.0:
                successes += 1
            else:
                failures += 1
        return _QualityEvidence(successes, failures)

    def _evidence_records(self) -> tuple[dict[str, object], ...]:
        if self._routing_state is None:
            return self._history.records()
        records: list[dict[str, object]] = []
        for execution in self._routing_state.executions.values():
            for attempt in execution.attempts.values():
                if attempt.status != "finalized":
                    continue
                selection = attempt.selection
                context = selection.get("context_features") or {}
                records.append({
                    "agent_id": selection.get("selected_agent"),
                    "agent_base_id": selection.get("selected_agent_base_id"),
                    "cohort": selection.get("cohort"),
                    "environment_epoch": context.get("environment_epoch") if isinstance(context, dict) else None,
                    "routing_context": context,
                    "evaluations": list(attempt.evaluations),
                })
        return tuple(records)

    @staticmethod
    def _best_evidence_choice(evidence: Mapping[str, _QualityEvidence]) -> dict[str, object]:
        observed = [(item.posterior_mean, agent_id, item) for agent_id, item in evidence.items() if item.samples]
        if not observed:
            return {"available": False, "reason": "no eligible typed quality evidence in paired/prospective cohorts", "shadow_only": True}
        observed.sort(key=lambda item: (-item[0], item[1]))
        mean, selected, selected_evidence = observed[0]
        return {
            "available": True,
            "selected_agent": selected,
            "posterior_mean": mean,
            "samples": selected_evidence.samples,
            "backoff_level": selected_evidence.backoff_level,
            "candidate_evidence": {
                agent_id: {
                    "samples": item.samples,
                    "successes": item.successes,
                    "failures": item.failures,
                    "posterior_mean": item.posterior_mean,
                    "backoff_level": item.backoff_level,
                }
                for agent_id, item in sorted(evidence.items())
            },
            "shadow_only": True,
        }


class RoutingPolicyRouter:
    """Configurable active policy plus execution-free shadow baselines."""

    def __init__(
        self,
        policy: str,
        analyzer: TaskAnalyzer,
        history: ExecutionHistory,
        *,
        baseline_agent_id: str | None,
        shadow: bool,
        seed: int,
        environment_epoch: str,
        objective_evaluator_available: bool,
        constraint_evaluator_count: int,
        routing_state: RoutingState | None = None,
        routing_state_provider: Callable[[], RoutingState] | None = None,
    ) -> None:
        if policy not in {"legacy", "static"}:
            raise ValueError(f"Unsupported routing policy: {policy}")
        if policy == "static" and not baseline_agent_id:
            raise ValueError("--routing-policy static requires --routing-baseline-agent.")
        self._policy = policy
        self._analyzer = analyzer
        self._history = history
        self._baseline_agent_id = baseline_agent_id
        self._shadow = shadow
        self._seed = seed
        self._environment_epoch = environment_epoch
        self._objective_evaluator_available = objective_evaluator_available
        self._constraint_evaluator_count = constraint_evaluator_count
        self._routing_state = routing_state
        self._routing_state_provider = routing_state_provider
        self._context_builder = RoutingContextBuilder()
        self._active = (
            AdaptiveRouter(analyzer, history)
            if policy == "legacy"
            else CorrectedStaticRouter(
                analyzer,
                baseline_agent_id or "",
                objective_evaluator_available=objective_evaluator_available,
                constraint_evaluator_count=constraint_evaluator_count,
                environment_epoch=environment_epoch,
            )
        )

    @property
    def policy_version(self) -> str:
        return str(self._active.policy_version)

    def policy_config(self) -> dict[str, object]:
        return {
            "active_policy": self._policy,
            "active_config": self._active.policy_config(),
            "baseline_agent_id": self._baseline_agent_id,
            "shadow": self._shadow,
            "seed": self._seed,
            "environment_epoch": self._environment_epoch,
        }

    def select(self, task: Task, agents: Iterable[Agent], requested_agent_id: str = "auto") -> ExecutionPlan:
        available = tuple(agents)
        plan = self._active.select(task, available, requested_agent_id)
        analysis = self._analyzer.analyze(task)
        context = self._context_builder.build(
            task,
            inferred_capabilities=analysis.inferred_capabilities,
            difficulty=analysis.difficulty,
            risk=analysis.risk,
            uncertainty=analysis.uncertainty,
            objective_evaluator_available=self._objective_evaluator_available,
            constraint_evaluator_count=self._constraint_evaluator_count,
            environment_epoch=self._environment_epoch,
        )
        decision = dict(plan.decision or {})
        decision["routing_context"] = context.as_dict()
        eligible = tuple(agent for agent in available if agent.supports(task.required_capabilities))
        if self._shadow:
            routing_state = self._routing_state_provider() if self._routing_state_provider is not None else self._routing_state
            shadows = ShadowBaselineEvaluator(
                self._history,
                self._baseline_agent_id,
                self._seed,
                self._environment_epoch,
                routing_state,
            ).evaluate(context, eligible)
            shadows["legacy-adaptive"] = self._legacy_shadow(task, available, use_history=True)
            shadows["legacy-static-profile"] = self._legacy_shadow(task, available, use_history=False)
            decision["shadow_decisions"] = shadows
        else:
            decision["shadow_decisions"] = {}
        return ExecutionPlan(plan.task, plan.agent_id, plan.rationale, plan.analysis, decision)

    def _legacy_shadow(self, task: Task, agents: tuple[Agent, ...], *, use_history: bool) -> dict[str, object]:
        history = self._history if use_history else _EmptyHistory()
        try:
            plan = AdaptiveRouter(self._analyzer, history).select(task, agents, "auto")
        except ValueError as exc:
            return {"available": False, "reason": str(exc), "shadow_only": True, "evidence_trusted": False}
        return {
            "available": True,
            "selected_agent": plan.agent_id,
            "candidate_scores": (plan.decision or {}).get("candidate_scores") or {},
            "shadow_only": True,
            "evidence_trusted": False,
            "reason": "legacy biased comparator; not objective-quality evidence",
        }


def _shadow_choice(candidate: str | None, reason: str) -> dict[str, object]:
    if candidate is None:
        return {"available": False, "reason": reason, "shadow_only": True}
    return {"available": True, "selected_agent": candidate, "reason": reason, "shadow_only": True}


class _EmptyHistory:
    @staticmethod
    def routing_metrics_for(agent_id: str) -> AgentMetrics:
        return AgentMetrics()
