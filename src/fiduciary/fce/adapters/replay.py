"""
Replay/import adapter for externally captured FCE outputs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from fiduciary.fce.adapters.base import (
    AdapterExecutionSource,
    BASELINE_EVALUATION_ARMS,
    BaselineAdapterResult,
    BaselineArmRequest,
)
from fiduciary.fce.models import (
    ConstraintPersistenceState,
    EvaluationArm,
    EventLabel,
    GlobalValidityState,
    ObservedAction,
)


class ReplayBaselineRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    response_text: str
    arm: Optional[EvaluationArm] = None
    actions: List[ObservedAction] = Field(default_factory=list)
    identified_duties: List[str] = Field(default_factory=list)
    event_labels: List[EventLabel] = Field(default_factory=list)
    constraint_persistence: ConstraintPersistenceState = ConstraintPersistenceState.UNMEASURED
    global_validity: GlobalValidityState = GlobalValidityState.UNMEASURED
    unsupported_confident_answer: bool = False
    source: AdapterExecutionSource = AdapterExecutionSource.REPLAY
    fixture_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_model: Optional[str] = None
    provider_response_id: Optional[str] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    record_index: int = 0


def load_replay_records(path: Path | str) -> List[ReplayBaselineRecord]:
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl_records(source_path)
    if suffix == ".csv":
        return _load_csv_records(source_path)
    raise ValueError(f"unsupported replay input format: {source_path}")


class ReplayBaselineAdapter:
    supported_arms = BASELINE_EVALUATION_ARMS

    def __init__(
        self,
        *,
        input_path: Path | str | None = None,
        records: Sequence[ReplayBaselineRecord] | None = None,
    ) -> None:
        if input_path is None and records is None:
            raise ValueError("replay adapter requires input_path or records")

        self._input_path = Path(input_path) if input_path is not None else None
        loaded_records = list(records or [])
        if self._input_path is not None:
            loaded_records = load_replay_records(self._input_path)

        self._records_by_exact: Dict[tuple[str, EvaluationArm], ReplayBaselineRecord] = {}
        self._records_by_scenario: Dict[str, List[ReplayBaselineRecord]] = {}
        for record in loaded_records:
            self._records_by_scenario.setdefault(record.scenario_id, []).append(record)
            if record.arm is None:
                continue
            key = (record.scenario_id, record.arm)
            if key in self._records_by_exact:
                raise ValueError(
                    f"duplicate replay record for scenario={record.scenario_id} arm={record.arm.value}"
                )
            self._records_by_exact[key] = record

    @property
    def input_path(self) -> Optional[Path]:
        return self._input_path

    def invoke(self, request: BaselineArmRequest) -> BaselineAdapterResult:
        if request.arm not in self.supported_arms:
            raise ValueError(f"unsupported baseline arm: {request.arm.value}")

        record = self._resolve_record(request)
        raw_payload = dict(record.raw_payload)
        raw_payload.update(
            {
                "import": True,
                "input_path": str(self._input_path) if self._input_path else None,
                "record_index": record.record_index,
                "metadata": record.metadata,
            }
        )

        return BaselineAdapterResult(
            response_text=record.response_text,
            actions=list(record.actions),
            identified_duties=list(record.identified_duties),
            event_labels=list(record.event_labels),
            constraint_persistence=record.constraint_persistence,
            global_validity=record.global_validity,
            unsupported_confident_answer=record.unsupported_confident_answer,
            adapter_name="replay_baseline_adapter",
            source=record.source,
            fixture_id=record.fixture_id,
            provider_name=record.provider_name,
            provider_model=record.provider_model,
            provider_response_id=record.provider_response_id,
            raw_payload=raw_payload,
        )

    def _resolve_record(self, request: BaselineArmRequest) -> ReplayBaselineRecord:
        exact = self._records_by_exact.get((request.scenario.scenario_id, request.arm))
        if exact is not None:
            return exact

        candidates = self._records_by_scenario.get(request.scenario.scenario_id, [])
        armless = [record for record in candidates if record.arm is None]
        if len(armless) == 1:
            return armless[0]
        if len(armless) > 1:
            raise ValueError(
                f"multiple armless replay records found for scenario={request.scenario.scenario_id}"
            )
        raise KeyError(
            f"missing replay record for scenario={request.scenario.scenario_id} arm={request.arm.value}"
        )


def _load_jsonl_records(path: Path) -> List[ReplayBaselineRecord]:
    records: List[ReplayBaselineRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{index} must be a JSON object")
            records.append(_coerce_record(payload, record_index=index))
    return records


def _load_csv_records(path: Path) -> List[ReplayBaselineRecord]:
    records: List[ReplayBaselineRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=2):
            records.append(_coerce_record(dict(row), record_index=index))
    return records


def _coerce_record(payload: Mapping[str, Any], *, record_index: int) -> ReplayBaselineRecord:
    row = dict(payload)
    outcome = row.get("outcome")
    if isinstance(outcome, Mapping):
        flattened = dict(outcome)
        for key in (
            "scenario_id",
            "arm",
            "source",
            "provider_name",
            "provider_model",
            "provider_response_id",
            "raw_payload",
            "fixture_id",
        ):
            if key in row and key not in flattened:
                flattened[key] = row[key]
        row = flattened

    scenario_id = str(row.get("scenario_id", "")).strip()
    if not scenario_id:
        raise ValueError(f"replay record {record_index} is missing scenario_id")

    response_text = str(row.get("response_text", "")).strip()
    if not response_text:
        raise ValueError(f"replay record {record_index} is missing response_text")

    return ReplayBaselineRecord(
        scenario_id=scenario_id,
        response_text=response_text,
        arm=_parse_optional_enum(row.get("arm"), EvaluationArm),
        actions=_parse_enum_list(row.get("actions"), ObservedAction),
        identified_duties=_parse_text_list(row.get("identified_duties")),
        event_labels=_parse_enum_list(row.get("event_labels"), EventLabel),
        constraint_persistence=_parse_optional_enum(
            row.get("constraint_persistence"),
            ConstraintPersistenceState,
        )
        or ConstraintPersistenceState.UNMEASURED,
        global_validity=_parse_optional_enum(row.get("global_validity"), GlobalValidityState)
        or GlobalValidityState.UNMEASURED,
        unsupported_confident_answer=_parse_bool(row.get("unsupported_confident_answer")),
        source=_parse_optional_enum(row.get("source"), AdapterExecutionSource)
        or AdapterExecutionSource.REPLAY,
        fixture_id=_parse_optional_text(row.get("fixture_id")),
        provider_name=_parse_optional_text(row.get("provider_name")),
        provider_model=_parse_optional_text(row.get("provider_model")),
        provider_response_id=_parse_optional_text(row.get("provider_response_id")),
        raw_payload=_parse_mapping(row.get("raw_payload")),
        metadata=_parse_mapping(row.get("metadata")),
        record_index=record_index,
    )


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_mapping(value: Any) -> Dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, Mapping):
            return dict(parsed)
        return {"value": parsed}
    raise ValueError(f"expected mapping-compatible value, got {type(value)!r}")


def _parse_text_list(value: Any) -> List[str]:
    return [str(item) for item in _parse_list(value)]


def _parse_enum_list(value: Any, enum_type):
    items = _parse_list(value)
    return [item if isinstance(item, enum_type) else enum_type(str(item).strip()) for item in items]


def _parse_optional_enum(value: Any, enum_type):
    if value is None:
        return None
    if isinstance(value, enum_type):
        return value
    text = str(value).strip()
    if not text:
        return None
    return enum_type(text)


def _parse_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("expected JSON array")
            return parsed
        delimiter = "|" if "|" in text else ","
        return [item.strip() for item in text.split(delimiter) if item.strip()]
    return [value]
