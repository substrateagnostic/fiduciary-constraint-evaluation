"""
Adapter contracts, transport helpers, and normalization helpers for FCE evaluation arms.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, TypeVar, runtime_checkable
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import BaseModel, ConfigDict, Field

from fiduciary.fce.models import (
    CoherentWitness,
    ConstraintPersistenceState,
    EvaluationArm,
    EventLabel,
    FCEBenchmarkRun,
    FCEObservedOutcome,
    FCEScenario,
    GlobalValidityState,
    MiddlewareWitnessRecord,
    ObservedAction,
    ProofValidationVerdict,
    RequiredDisposition,
    WitnessMode,
)


class AdapterExecutionSource(str, Enum):
    FIXTURE = "fixture"
    REPLAY = "replay"
    LIVE = "live"
    RUNTIME = "runtime"


BASELINE_EVALUATION_ARMS: tuple[EvaluationArm, ...] = (
    EvaluationArm.RAW_MODEL,
    EvaluationArm.PROMPTED_MODEL,
    EvaluationArm.RULES_AVAILABLE_MODEL,
)

RUNNER_EVALUATION_ARMS: tuple[EvaluationArm, ...] = (
    *BASELINE_EVALUATION_ARMS,
    EvaluationArm.PRISMWEFT_RUNTIME,
)


def supports_runner_arm(arm: EvaluationArm) -> bool:
    """Return whether the package has an executable runner path for this arm."""
    return arm in RUNNER_EVALUATION_ARMS


def supported_runner_arm_values() -> tuple[str, ...]:
    return tuple(arm.value for arm in RUNNER_EVALUATION_ARMS)


T = TypeVar("T")


def dedupe_preserve_order(values: Sequence[T]) -> List[T]:
    result: List[T] = []
    seen: set[T] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def primary_action_for_disposition(disposition: RequiredDisposition) -> ObservedAction:
    mapping = {
        RequiredDisposition.CORRECT_CONTINUE: ObservedAction.CONTINUE,
        RequiredDisposition.CLARIFY_REQUIRED: ObservedAction.CLARIFY,
        RequiredDisposition.REFUSE_REQUIRED: ObservedAction.REFUSE,
        RequiredDisposition.ESCALATE_REQUIRED: ObservedAction.ESCALATE,
    }
    return mapping[disposition]


class BaselineArmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: FCEScenario
    arm: EvaluationArm
    arm_scaffold: str = ""


class RuntimeArmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: FCEScenario
    arm: EvaluationArm = EvaluationArm.PRISMWEFT_RUNTIME


class BaselineAdapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_text: str
    actions: List[ObservedAction] = Field(default_factory=list)
    identified_duties: List[str] = Field(default_factory=list)
    event_labels: List[EventLabel] = Field(default_factory=list)
    constraint_persistence: ConstraintPersistenceState = ConstraintPersistenceState.UNMEASURED
    global_validity: GlobalValidityState = GlobalValidityState.UNMEASURED
    unsupported_confident_answer: bool = False
    adapter_name: str
    source: AdapterExecutionSource = AdapterExecutionSource.FIXTURE
    fixture_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_model: Optional[str] = None
    provider_response_id: Optional[str] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class RuntimeAdapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_text: str = ""
    actions: List[ObservedAction] = Field(default_factory=list)
    identified_duties: List[str] = Field(default_factory=list)
    event_labels: List[EventLabel] = Field(default_factory=list)
    constraint_persistence: ConstraintPersistenceState = ConstraintPersistenceState.UNMEASURED
    global_validity: GlobalValidityState = GlobalValidityState.UNMEASURED
    unsupported_confident_answer: bool = False
    witness: Optional[MiddlewareWitnessRecord] = None
    proof_witness: Optional[CoherentWitness] = None
    proof_verdict: Optional[ProofValidationVerdict] = None
    adapter_name: str
    source: AdapterExecutionSource = AdapterExecutionSource.RUNTIME
    fixture_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_model: Optional[str] = None
    provider_response_id: Optional[str] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class FCENormalizedObservedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    arm: EvaluationArm
    source: AdapterExecutionSource
    adapter_name: str
    fixture_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_model: Optional[str] = None
    provider_response_id: Optional[str] = None
    witness_mode: WitnessMode = WitnessMode.NONE
    proof_supported: bool = False
    semantic_annotations_present: bool = False
    outcome: FCEObservedOutcome
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class FCEExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    arm: EvaluationArm
    normalized_outcome: FCENormalizedObservedOutcome
    benchmark_run: FCEBenchmarkRun


@runtime_checkable
class BaselineArmAdapter(Protocol):
    supported_arms: Sequence[EvaluationArm]

    def invoke(self, request: BaselineArmRequest) -> BaselineAdapterResult:
        ...


@runtime_checkable
class RuntimeArmAdapter(Protocol):
    supported_arms: Sequence[EvaluationArm]

    def invoke(self, request: RuntimeArmRequest) -> RuntimeAdapterResult:
        ...


class HTTPJSONResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: Dict[str, Any]
    headers: Dict[str, str] = Field(default_factory=dict)
    status_code: int = 200


@runtime_checkable
class HTTPJSONTransport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Dict[str, Any],
        timeout_seconds: float,
    ) -> HTTPJSONResponse:
        ...


class LiveProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str
    provider_model: str
    api_key_env_var: str
    api_url: str
    timeout_seconds: float = 60.0
    max_output_tokens: int = 512
    temperature: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


def default_http_json_transport(
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Dict[str, Any],
    timeout_seconds: float,
) -> HTTPJSONResponse:
    request_body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=request_body,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            response_headers = {key: value for key, value in response.headers.items()}
            status_code = getattr(response, "status", 200)
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{url} returned HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"{url} request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} returned non-JSON response") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"{url} returned a JSON payload that is not an object")

    return HTTPJSONResponse(
        payload=parsed,
        headers=response_headers,
        status_code=status_code,
    )


def build_live_conversation(
    request: BaselineArmRequest,
) -> tuple[Optional[str], List[Dict[str, str]]]:
    system_parts: List[str] = []
    messages: List[Dict[str, str]] = []

    for turn in request.scenario.conversation:
        if turn.role.value == "system":
            if turn.content.strip():
                system_parts.append(turn.content.strip())
            continue
        messages.append({"role": turn.role.value, "content": turn.content})

    if request.arm_scaffold.strip():
        system_parts.append(request.arm_scaffold.strip())

    system_prompt = "\n\n".join(system_parts).strip() or None
    return system_prompt, messages


class LiveBaselineAdapter(ABC):
    supported_arms = BASELINE_EVALUATION_ARMS
    adapter_name = "live_baseline_adapter"

    def __init__(
        self,
        *,
        config: LiveProviderConfig,
        transport: HTTPJSONTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or default_http_json_transport

    @property
    def config(self) -> LiveProviderConfig:
        return self._config

    def invoke(self, request: BaselineArmRequest) -> BaselineAdapterResult:
        if request.arm not in self.supported_arms:
            raise ValueError(f"unsupported baseline arm: {request.arm.value}")

        api_key = os.getenv(self._config.api_key_env_var, "").strip()
        if not api_key:
            raise RuntimeError(
                f"missing provider credential: set {self._config.api_key_env_var}"
            )

        system_prompt, messages = build_live_conversation(request)
        request_payload = self.build_payload(
            request=request,
            system_prompt=system_prompt,
            messages=messages,
        )
        response = self._transport(
            url=self._config.api_url,
            headers=self.build_headers(api_key),
            payload=request_payload,
            timeout_seconds=self._config.timeout_seconds,
        )

        return BaselineAdapterResult(
            response_text=self.extract_response_text(response.payload),
            adapter_name=self.adapter_name,
            source=AdapterExecutionSource.LIVE,
            provider_name=self._config.provider_name,
            provider_model=self._config.provider_model,
            provider_response_id=self.extract_provider_response_id(response.payload, response.headers),
            raw_payload={
                "provider": self._config.provider_name,
                "model": self._config.provider_model,
                "config": self._config.model_dump(mode="json"),
                "request": request_payload,
                "response": response.payload,
                "response_headers": response.headers,
                "scenario_id": request.scenario.scenario_id,
                "arm": request.arm.value,
            },
        )

    @abstractmethod
    def build_headers(self, api_key: str) -> Dict[str, str]:
        """Build transport headers for the provider."""

    @abstractmethod
    def build_payload(
        self,
        *,
        request: BaselineArmRequest,
        system_prompt: Optional[str],
        messages: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        """Build the provider request body."""

    @abstractmethod
    def extract_response_text(self, payload: Mapping[str, Any]) -> str:
        """Extract plain assistant text from the provider response payload."""

    def extract_provider_response_id(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Optional[str]:
        if payload.get("id"):
            return str(payload["id"])
        for key in ("x-request-id", "request-id"):
            if headers.get(key):
                return headers[key]
        return None


def normalize_baseline_result(
    request: BaselineArmRequest,
    result: BaselineAdapterResult,
) -> FCENormalizedObservedOutcome:
    outcome = FCEObservedOutcome(
        response_text=result.response_text.strip(),
        actions=dedupe_preserve_order(result.actions),
        identified_duties=dedupe_preserve_order(result.identified_duties),
        event_labels=dedupe_preserve_order(result.event_labels),
        constraint_persistence=result.constraint_persistence,
        global_validity=result.global_validity,
        unsupported_confident_answer=result.unsupported_confident_answer,
    )
    return FCENormalizedObservedOutcome(
        scenario_id=request.scenario.scenario_id,
        arm=request.arm,
        source=result.source,
        adapter_name=result.adapter_name,
        fixture_id=result.fixture_id,
        provider_name=result.provider_name,
        provider_model=result.provider_model,
        provider_response_id=result.provider_response_id,
        witness_mode=WitnessMode.NONE,
        proof_supported=False,
        semantic_annotations_present=False,
        outcome=outcome,
        raw_payload=result.raw_payload,
    )


def normalize_runtime_result(
    request: RuntimeArmRequest,
    result: RuntimeAdapterResult,
) -> FCENormalizedObservedOutcome:
    scenario = request.scenario
    witness = result.witness
    response_text = result.response_text.strip()
    if not response_text:
        response_text = _synthesize_runtime_response(scenario, witness)

    actions = dedupe_preserve_order(result.actions)
    if not actions:
        actions = _default_runtime_actions(scenario)

    identified_duties = dedupe_preserve_order(result.identified_duties)
    if not identified_duties:
        identified_duties = dedupe_preserve_order(
            scenario.expected_behavior.must_identify or scenario.middleware_expected.minimal_conflict_set
        )

    outcome = FCEObservedOutcome(
        response_text=response_text,
        actions=actions,
        identified_duties=identified_duties,
        event_labels=dedupe_preserve_order(result.event_labels),
        constraint_persistence=result.constraint_persistence,
        global_validity=result.global_validity,
        unsupported_confident_answer=result.unsupported_confident_answer,
        witness=witness,
        proof_witness=result.proof_witness,
        proof_verdict=result.proof_verdict,
    )
    witness_mode = _witness_mode_for_runtime_result(result)
    return FCENormalizedObservedOutcome(
        scenario_id=scenario.scenario_id,
        arm=request.arm,
        source=result.source,
        adapter_name=result.adapter_name,
        fixture_id=result.fixture_id,
        provider_name=result.provider_name,
        provider_model=result.provider_model,
        provider_response_id=result.provider_response_id,
        witness_mode=witness_mode,
        proof_supported=result.proof_witness is not None,
        semantic_annotations_present=_semantic_annotations_present(result),
        outcome=outcome,
        raw_payload=result.raw_payload,
    )


def _witness_mode_for_runtime_result(result: RuntimeAdapterResult) -> WitnessMode:
    if result.source == AdapterExecutionSource.FIXTURE:
        return WitnessMode.FIXTURE
    if result.proof_witness is not None:
        return WitnessMode.PROOF_SUPPORTED_RUNTIME
    return WitnessMode.RUNTIME


def _semantic_annotations_present(result: RuntimeAdapterResult) -> bool:
    if result.proof_witness is not None:
        return bool(result.proof_witness.semantic_annotations)
    return result.source == AdapterExecutionSource.RUNTIME and (
        result.witness is not None or bool(result.raw_payload)
    )


def _default_runtime_actions(scenario: FCEScenario) -> List[ObservedAction]:
    actions = [primary_action_for_disposition(scenario.middleware_expected.event)]
    for action in scenario.expected_behavior.must_do_one_of:
        if action not in actions:
            actions.append(action)
            break
    return actions


def _synthesize_runtime_response(
    scenario: FCEScenario,
    witness: Optional[MiddlewareWitnessRecord],
) -> str:
    explanation = ""
    if witness and witness.explanation.strip():
        explanation = witness.explanation.strip()
    elif scenario.middleware_expected.human_readable_explanation.strip():
        explanation = scenario.middleware_expected.human_readable_explanation.strip()

    duties = ", ".join(scenario.expected_behavior.must_identify[:2])
    must_not = scenario.expected_behavior.must_not[0] if scenario.expected_behavior.must_not else ""
    safe_step = (
        scenario.expected_behavior.safe_alternatives[0]
        if scenario.expected_behavior.safe_alternatives
        else "route the issue to a supervising lawyer"
    )
    parts = [part for part in [duties, explanation, must_not, safe_step] if part]
    return ". ".join(parts)
