"""
Public adapter exports for FCE baseline, replay, and runtime execution.
"""

from fiduciary.fce.adapters.anthropic import AnthropicBaselineAdapter
from fiduciary.fce.adapters.base import (
    AdapterExecutionSource,
    BASELINE_EVALUATION_ARMS,
    RUNNER_EVALUATION_ARMS,
    BaselineAdapterResult,
    BaselineArmAdapter,
    BaselineArmRequest,
    FCEExecutionReport,
    FCENormalizedObservedOutcome,
    HTTPJSONResponse,
    HTTPJSONTransport,
    LiveBaselineAdapter,
    LiveProviderConfig,
    RuntimeAdapterResult,
    RuntimeArmAdapter,
    RuntimeArmRequest,
    build_live_conversation,
    dedupe_preserve_order,
    default_http_json_transport,
    normalize_baseline_result,
    normalize_runtime_result,
    primary_action_for_disposition,
    supported_runner_arm_values,
    supports_runner_arm,
)
from fiduciary.fce.adapters.openai import OpenAIBaselineAdapter
from fiduciary.fce.adapters.replay import ReplayBaselineAdapter, ReplayBaselineRecord, load_replay_records

__all__ = [
    "AdapterExecutionSource",
    "AnthropicBaselineAdapter",
    "BASELINE_EVALUATION_ARMS",
    "BaselineAdapterResult",
    "BaselineArmAdapter",
    "BaselineArmRequest",
    "FCEExecutionReport",
    "FCENormalizedObservedOutcome",
    "HTTPJSONResponse",
    "HTTPJSONTransport",
    "LiveBaselineAdapter",
    "LiveProviderConfig",
    "OpenAIBaselineAdapter",
    "RUNNER_EVALUATION_ARMS",
    "ReplayBaselineAdapter",
    "ReplayBaselineRecord",
    "RuntimeAdapterResult",
    "RuntimeArmAdapter",
    "RuntimeArmRequest",
    "build_live_conversation",
    "dedupe_preserve_order",
    "default_http_json_transport",
    "load_replay_records",
    "normalize_baseline_result",
    "normalize_runtime_result",
    "primary_action_for_disposition",
    "supported_runner_arm_values",
    "supports_runner_arm",
]
