"""Shared data contracts for tasks, traces, and benchmark results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
import json


Json = dict[str, Any]


PUBLIC_NOTIFICATION_ROLES = {
    "contingent_network_recovery": ("supply_planning", "plant_controller", "customer_operations"),
    "assembly_bom_review": ("product_engineering", "supply_chain_quality"),
    "capital_project": ("fixed_assets", "project_accounting", "plant_controller"),
    "cold_chain_recall": ("distribution_quality", "customer_safety", "regulatory"),
    "construction_document_review": ("construction_management", "plant_engineering"),
    "customer_credit": ("credit_control", "customer_service"),
    "demand_supply_rebalance": ("demand_planning", "supply_planning", "procurement"),
    "drawing_review": ("design_engineering", "manufacturing_engineering"),
    "engineering_change": ("engineering", "production_planning"),
    "engineering_production_release": (
        "design_authority",
        "configuration_management",
        "production_planning",
        "shop_quality",
    ),
    "inventory_mismatch": ("inventory_control", "production_planning"),
    "integrated_operating_review": (
        "quality_leadership",
        "supply_planning",
        "production_control",
        "distribution_planning",
        "transportation",
        "customer_operations",
        "plant_controller",
        "enterprise_risk",
    ),
    "invoice_exception": ("accounts_payable", "procurement"),
    "machine_failure": ("maintenance", "production_planning"),
    "manufacturing_document_drafting": ("manufacturing_engineering", "shop_quality"),
    "network_allocation": ("distribution_planning", "customer_service"),
    "order_to_cash_disruption": (
        "credit_control",
        "customer_service",
        "warehouse_operations",
        "transportation",
        "sales_operations",
    ),
    "payroll_anomaly": ("payroll", "hr_operations"),
    "period_close": ("controller", "financial_close"),
    "plant_fulfillment_recovery": (
        "shop_quality",
        "maintenance",
        "production_planning",
        "warehouse_operations",
        "transportation",
        "customer_service",
        "plant_controller",
        "financial_close",
    ),
    "pid_review": ("process_engineering", "process_safety"),
    "process_capability_review": ("supplier_quality", "strategic_sourcing"),
    "quality_drift": ("quality", "production"),
    "revision_review": ("configuration_management", "design_authority"),
    "recall_financial_response": (
        "distribution_quality",
        "customer_safety",
        "regulatory",
        "controller",
        "financial_close",
    ),
    "rush_order": ("customer_service", "production_planning"),
    "standards_specification_review": ("code_compliance", "quality_engineering"),
    "supplier_delay": ("procurement", "production_planning"),
    "supplier_quality_recovery": (
        "supplier_quality",
        "procurement",
        "production_planning",
        "customer_service",
    ),
    "trade_compliance": ("trade_compliance", "transportation"),
    "transportation_disruption": ("transportation", "customer_service"),
    "vendor_master_change": ("vendor_master", "treasury", "fraud_risk"),
    "warehouse_wave": ("warehouse_operations", "transportation"),
}


FOCUSED_WORKFLOW_STAGES: tuple[Json, ...] = (
    {
        "id": "investigate",
        "objective": "Read the incident and reconcile every named authoritative system",
        "depends_on": (),
    },
    {
        "id": "resolve_dynamic_evidence",
        "objective": "Wait for and re-read pending or changing evidence when required",
        "depends_on": ("investigate",),
    },
    {
        "id": "contain_and_plan",
        "objective": "Create reversible containment and exact required plans or records",
        "depends_on": ("resolve_dynamic_evidence",),
    },
    {
        "id": "authorize_and_execute",
        "objective": "Complete required protected changes without releasing unsafe scope",
        "depends_on": ("contain_and_plan",),
    },
    {
        "id": "communicate_and_finish",
        "objective": "Notify every contracted role and finish with concrete evidence IDs",
        "depends_on": ("authorize_and_execute",),
    },
)


@dataclass(frozen=True)
class IncidentTask:
    """Agent-visible definition of one benchmark episode."""

    id: str
    version: str
    family: str
    title: str
    prompt: str
    seed: int
    difficulty: str
    systems: tuple[str, ...]
    max_tool_calls: int = 30
    horizon_minutes: int = 60
    tags: tuple[str, ...] = ()
    controlled_plan_actions: tuple[str, ...] = ()
    workflow_stages: tuple[Json, ...] = ()

    @property
    def public_workflow_stages(self) -> tuple[Json, ...]:
        """Return the explicit DAG or the common focused-workflow lifecycle."""

        return self.workflow_stages or FOCUSED_WORKFLOW_STAGES

    @classmethod
    def from_dict(cls, value: Json) -> "IncidentTask":
        workflow_stages = tuple(
            {
                "id": str(stage["id"]),
                "objective": str(stage["objective"]),
                "depends_on": tuple(stage.get("depends_on", ())),
            }
            for stage in value.get("workflow_stages", ())
        )
        seen_stage_ids: set[str] = set()
        for stage in workflow_stages:
            stage_id = stage["id"]
            if not stage_id or stage_id in seen_stage_ids:
                raise ValueError(f"workflow stage IDs must be nonempty and unique: {stage_id!r}")
            unknown = set(stage["depends_on"]) - seen_stage_ids
            if unknown:
                raise ValueError(
                    f"workflow stage {stage_id!r} depends on unknown or later stages: "
                    f"{sorted(unknown)}"
                )
            if not stage["objective"].strip():
                raise ValueError(f"workflow stage {stage_id!r} must have an objective")
            seen_stage_ids.add(stage_id)
        return cls(
            id=value["id"],
            version=value.get("version", "0.6.0"),
            family=value["family"],
            title=value["title"],
            prompt=value["prompt"],
            seed=int(value["seed"]),
            difficulty=value.get("difficulty", "medium"),
            systems=tuple(value.get("systems", ())),
            max_tool_calls=int(value.get("max_tool_calls", 30)),
            horizon_minutes=int(value.get("horizon_minutes", 60)),
            tags=tuple(value.get("tags", ())),
            controlled_plan_actions=tuple(value.get("controlled_plan_actions", ())),
            workflow_stages=workflow_stages,
        )

    def public_dict(self) -> Json:
        value = asdict(self)
        value.pop("seed", None)
        value["systems"] = list(self.systems)
        value["tags"] = list(self.tags)
        value["controlled_plan_actions"] = list(self.controlled_plan_actions)
        value["workflow_stages"] = [
            {
                "id": stage["id"],
                "objective": stage["objective"],
                "depends_on": list(stage["depends_on"]),
            }
            for stage in self.public_workflow_stages
        ]
        value["required_notification_roles"] = list(
            PUBLIC_NOTIFICATION_ROLES.get(self.family, ())
        )
        return value


@dataclass
class ToolCallRecord:
    index: int
    minute: int
    tool: str
    arguments: Json
    result: Json
    state_hash: str


@dataclass
class ScheduledEvent:
    at_minute: int
    kind: str
    payload: Json
    id: str


@dataclass
class CriterionResult:
    id: str
    dimension: str
    weight: float
    passed: bool
    detail: str


@dataclass
class EpisodeScore:
    task_id: str
    score: float
    strict_success: bool
    critical_failure: bool
    estimated_cost: float
    unmitigated_cost: float
    best_known_cost: float
    dimensions: dict[str, dict[str, float]]
    criteria: list[CriterionResult]
    violations: list[Json]
    tool_calls: int
    elapsed_minutes: int

    def to_dict(self) -> Json:
        return asdict(self)


@dataclass
class EpisodeResult:
    task: IncidentTask
    agent: str
    score: EpisodeScore
    final_answer: Json
    trace: list[ToolCallRecord]
    initial_state_hash: str
    final_state_hash: str
    applied_events: list[str] = field(default_factory=list)

    def to_dict(self) -> Json:
        return {
            "task": self.task.public_dict(),
            "agent": self.agent,
            "score": self.score.to_dict(),
            "final_answer": self.final_answer,
            "trace": [asdict(item) for item in self.trace],
            "initial_state_hash": self.initial_state_hash,
            "final_state_hash": self.final_state_hash,
            "applied_events": self.applied_events,
        }


class ToolClientProtocol(Protocol):
    def call(self, name: str, **arguments: Any) -> Json: ...

    @property
    def tools(self) -> list[Json]: ...


class Agent(Protocol):
    name: str

    def run(self, task: IncidentTask, tools: ToolClientProtocol) -> Json: ...


def load_tasks(path: str | Path) -> list[IncidentTask]:
    """Load a task JSON file or every JSON task under a directory."""

    source = Path(path)
    paths = sorted(source.glob("*.json")) if source.is_dir() else [source]
    tasks: list[IncidentTask] = []
    for task_path in paths:
        with task_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload if isinstance(payload, list) else [payload]
        tasks.extend(IncidentTask.from_dict(record) for record in records)
    return tasks
