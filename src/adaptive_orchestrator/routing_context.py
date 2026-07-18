from __future__ import annotations

from dataclasses import asdict, dataclass

from .domain import Capability, Task

ROUTING_CONTEXT_SCHEMA = "routing-context-v1"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    schema_version: str
    required_capabilities: tuple[str, ...]
    inferred_capabilities: tuple[str, ...]
    task_category: str
    difficulty: int
    risk: int
    uncertainty: int
    instruction_language: str
    objective_evaluator_available: bool
    constraint_evaluator_count: int
    environment_epoch: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class RoutingContextBuilder:
    """Pure versioned projection of pre-selection task/evaluator context."""

    schema_version = ROUTING_CONTEXT_SCHEMA

    def build(
        self,
        task: Task,
        *,
        inferred_capabilities: tuple[Capability, ...],
        difficulty: int,
        risk: int,
        uncertainty: int,
        objective_evaluator_available: bool,
        constraint_evaluator_count: int,
        environment_epoch: str,
    ) -> RoutingContext:
        required = tuple(sorted((item.value for item in task.required_capabilities)))
        inferred = tuple(sorted((item.value for item in inferred_capabilities)))
        categories = tuple(sorted(set(required) | set(inferred)))
        return RoutingContext(
            schema_version=self.schema_version,
            required_capabilities=required,
            inferred_capabilities=inferred,
            task_category="+".join(categories) if categories else "general",
            difficulty=difficulty,
            risk=risk,
            uncertainty=uncertainty,
            instruction_language=_instruction_language(task),
            objective_evaluator_available=objective_evaluator_available,
            constraint_evaluator_count=constraint_evaluator_count,
            environment_epoch=environment_epoch,
        )


def _instruction_language(task: Task) -> str:
    text = " ".join((task.description, task.objective, *task.constraints))
    has_korean = any("\uac00" <= character <= "\ud7a3" for character in text)
    has_latin = any(character.isascii() and character.isalpha() for character in text)
    if has_korean and has_latin:
        return "mixed"
    if has_korean:
        return "ko"
    if has_latin:
        return "en"
    return "unknown"
