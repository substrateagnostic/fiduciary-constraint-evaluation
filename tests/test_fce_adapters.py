"""
Adapter tests for replay imports and live provider normalization.
"""

import csv
import json

from fiduciary.fce import (
    AdapterExecutionSource,
    AnthropicBaselineAdapter,
    ConstraintPersistenceState,
    EvaluationArm,
    GlobalValidityState,
    OpenAIBaselineAdapter,
    ReplayBaselineAdapter,
    ReplayBaselineRecord,
    build_baseline_request,
    get_pilot_scenario,
    normalize_baseline_result,
    run_pilot,
    write_report_bundle,
)
from fiduciary.fce.adapters import HTTPJSONResponse, load_replay_records
from fiduciary.fce.models import ObservedAction
from fiduciary.fce.runner import PilotExecutionMode


def test_replay_adapter_imports_jsonl_and_normalizes_result(tmp_path):
    scenario = get_pilot_scenario("FCE-COMP-004-V1")
    replay_path = tmp_path / "replay.jsonl"
    replay_path.write_text(
        json.dumps(
            {
                "scenario_id": scenario.scenario_id,
                "arm": EvaluationArm.RAW_MODEL.value,
                "response_text": "I need to verify the citation before use and route this for review.",
                "actions": [
                    ObservedAction.REFUSE.value,
                    ObservedAction.VERIFY_BEFORE_USE.value,
                ],
                "identified_duties": ["candor", "competence"],
                "constraint_persistence": ConstraintPersistenceState.MAINTAINED.value,
                "global_validity": GlobalValidityState.VALID.value,
                "provider_name": "external_tool",
                "provider_model": "captured-runner-v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    adapter = ReplayBaselineAdapter(input_path=replay_path)
    request = build_baseline_request(scenario, EvaluationArm.RAW_MODEL)
    normalized = normalize_baseline_result(request, adapter.invoke(request))

    assert normalized.source == AdapterExecutionSource.REPLAY
    assert normalized.provider_name == "external_tool"
    assert normalized.provider_model == "captured-runner-v1"
    assert normalized.outcome.actions == [
        ObservedAction.REFUSE,
        ObservedAction.VERIFY_BEFORE_USE,
    ]
    assert normalized.raw_payload["import"] is True


def test_replay_loader_imports_csv_with_pipe_delimited_lists(tmp_path):
    replay_path = tmp_path / "replay.csv"
    with replay_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario_id",
                "arm",
                "response_text",
                "actions",
                "identified_duties",
                "constraint_persistence",
                "global_validity",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "scenario_id": "FCE-COMP-004-V1",
                "arm": EvaluationArm.PROMPTED_MODEL.value,
                "response_text": "I need more information before any citation is used.",
                "actions": "clarify|verify_before_use",
                "identified_duties": "candor|competence",
                "constraint_persistence": ConstraintPersistenceState.MAINTAINED.value,
                "global_validity": GlobalValidityState.VALID.value,
            }
        )

    records = load_replay_records(replay_path)

    assert len(records) == 1
    assert records[0].arm == EvaluationArm.PROMPTED_MODEL
    assert records[0].actions == [
        ObservedAction.CLARIFY,
        ObservedAction.VERIFY_BEFORE_USE,
    ]
    assert records[0].identified_duties == ["candor", "competence"]


def test_openai_adapter_normalizes_chat_completion_payload(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def transport(*, url, headers, payload, timeout_seconds):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "gpt-test"
        assert payload["messages"][0]["role"] == "system"
        return HTTPJSONResponse(
            payload={
                "id": "chatcmpl_test_123",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Escalate this for partner review before using any citation.",
                        }
                    }
                ],
            },
            headers={"x-request-id": "req_test_123"},
        )

    scenario = get_pilot_scenario("FCE-COMP-004-V1")
    request = build_baseline_request(scenario, EvaluationArm.PROMPTED_MODEL)
    adapter = OpenAIBaselineAdapter(model="gpt-test", transport=transport)

    result = adapter.invoke(request)
    normalized = normalize_baseline_result(request, result)

    assert result.source == AdapterExecutionSource.LIVE
    assert result.provider_name == "openai"
    assert result.provider_model == "gpt-test"
    assert result.provider_response_id == "chatcmpl_test_123"
    assert "Escalate this for partner review" in normalized.outcome.response_text


def test_anthropic_adapter_normalizes_message_payload(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def transport(*, url, headers, payload, timeout_seconds):
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "test-key"
        assert payload["model"] == "claude-test"
        assert isinstance(payload["messages"], list)
        return HTTPJSONResponse(
            payload={
                "id": "msg_test_123",
                "content": [
                    {
                        "type": "text",
                        "text": "I cannot proceed until the conflict is reviewed by supervising counsel.",
                    }
                ],
            }
        )

    scenario = get_pilot_scenario("FCE-CONF-001-V1")
    request = build_baseline_request(scenario, EvaluationArm.RULES_AVAILABLE_MODEL)
    adapter = AnthropicBaselineAdapter(model="claude-test", transport=transport)

    result = adapter.invoke(request)

    assert result.source == AdapterExecutionSource.LIVE
    assert result.provider_name == "anthropic"
    assert result.provider_model == "claude-test"
    assert result.provider_response_id == "msg_test_123"
    assert "supervising counsel" in result.response_text


def test_anthropic_adapter_records_thinking_only_truncation_as_data(monkeypatch):
    """max_tokens consumed by always-on thinking must not crash the run.

    claude-fable-5 has thinking always on; max_tokens caps total output
    including thinking tokens. A small budget yields thinking blocks and no
    text block with stop_reason "max_tokens". The adapter records an empty
    completion and surfaces stop_reason instead of raising.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def transport(*, url, headers, payload, timeout_seconds):
        assert "temperature" not in payload
        return HTTPJSONResponse(
            payload={
                "id": "msg_trunc_1",
                "stop_reason": "max_tokens",
                "content": [{"type": "thinking", "thinking": ""}],
            }
        )

    scenario = get_pilot_scenario("FCE-CONF-001-V1")
    request = build_baseline_request(scenario, EvaluationArm.RAW_MODEL)
    adapter = AnthropicBaselineAdapter(model="claude-fable-5", transport=transport)

    result = adapter.invoke(request)
    normalized = normalize_baseline_result(request, result)

    assert result.response_text == ""
    assert result.raw_payload["stop_reason"] == "max_tokens"
    assert normalized.outcome.response_text == ""


def test_anthropic_adapter_records_refusal_stop_details(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def transport(*, url, headers, payload, timeout_seconds):
        return HTTPJSONResponse(
            payload={
                "id": "msg_refusal_1",
                "stop_reason": "refusal",
                "stop_details": {"type": "refusal", "category": "cyber"},
                "content": [],
            }
        )

    scenario = get_pilot_scenario("FCE-CONF-001-V1")
    request = build_baseline_request(scenario, EvaluationArm.RAW_MODEL)
    adapter = AnthropicBaselineAdapter(model="claude-fable-5", transport=transport)

    result = adapter.invoke(request)

    assert result.response_text == ""
    assert result.raw_payload["stop_reason"] == "refusal"
    assert result.raw_payload["stop_details_category"] == "cyber"


def test_openai_adapter_gpt5_payload_and_null_content_tolerance(monkeypatch):
    """GPT-5 family: max_completion_tokens, no temperature, null-content tolerance."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def transport(*, url, headers, payload, timeout_seconds):
        assert payload["model"] == "gpt-5.5"
        assert "max_completion_tokens" in payload
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        return HTTPJSONResponse(
            payload={
                "id": "chatcmpl_trunc_1",
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": None},
                    }
                ],
            }
        )

    scenario = get_pilot_scenario("FCE-COMP-004-V1")
    request = build_baseline_request(scenario, EvaluationArm.RAW_MODEL)
    adapter = OpenAIBaselineAdapter(model="gpt-5.5", transport=transport)

    result = adapter.invoke(request)

    assert result.response_text == ""
    assert result.raw_payload["stop_reason"] == "length"


def test_replay_run_writes_manifest_jsonl(tmp_path):
    scenario = get_pilot_scenario("FCE-COMP-004-V1")
    adapter = ReplayBaselineAdapter(
        records=[
            ReplayBaselineRecord(
                scenario_id=scenario.scenario_id,
                arm=EvaluationArm.RAW_MODEL,
                response_text="I need to verify the citation before use.",
                actions=[ObservedAction.VERIFY_BEFORE_USE],
                identified_duties=["candor", "competence"],
            )
        ]
    )

    result = run_pilot(
        arms=[EvaluationArm.RAW_MODEL],
        mode=PilotExecutionMode.FIXTURES,
        scenarios=[scenario],
        baseline_adapter=adapter,
        manifest_metadata={"cli": {"baseline_adapter": "replay"}},
    )
    paths = write_report_bundle(tmp_path, result, PilotExecutionMode.FIXTURES)

    manifest_lines = paths["manifest_jsonl"].read_text(encoding="utf-8").strip().splitlines()
    session_record = json.loads(manifest_lines[0])
    completed_record = json.loads(manifest_lines[1])
    raw_record = json.loads(paths["raw_outputs_jsonl"].read_text(encoding="utf-8").strip())
    normalized_record = json.loads(
        paths["normalized_outputs_jsonl"].read_text(encoding="utf-8").strip()
    )

    assert session_record["record_type"] == "session"
    assert session_record["execution_metadata"]["cli"]["baseline_adapter"] == "replay"
    assert completed_record["record_type"] == "completed_run"
    assert completed_record["source"] == AdapterExecutionSource.REPLAY.value
    assert completed_record["witness_mode"] == "none"
    assert completed_record["proof_supported"] is False
    assert completed_record["semantic_annotations_present"] is False
    assert raw_record["scenario_id"] == scenario.scenario_id
    assert raw_record["raw_payload"]["import"] is True
    assert normalized_record["scenario_id"] == scenario.scenario_id
    assert normalized_record["source"] == AdapterExecutionSource.REPLAY.value
    assert normalized_record["witness_mode"] == "none"
    assert normalized_record["proof_supported"] is False
    assert normalized_record["semantic_annotations_present"] is False
