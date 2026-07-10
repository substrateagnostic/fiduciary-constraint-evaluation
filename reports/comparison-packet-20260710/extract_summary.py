"""Generate the PACKET.md source tables from the committed packet artifacts.

Usage:
    PYTHONPATH=src python3 reports/comparison-packet-20260710/extract_summary.py \
        reports/comparison-packet-20260710

Every number printed here is read from summary.csv, runs.csv,
raw_outputs.jsonl, or manifest.json inside the packet. Nothing is hand-typed.
The tables in PACKET.md are pasted from this output.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(sys.argv[1])

MODELS = [
    ("Anthropic", "claude-fable-5", "anthropic-claude-fable-5"),
    ("Anthropic", "claude-opus-4-8", "anthropic-claude-opus-4-8"),
    ("Anthropic", "claude-sonnet-5", "anthropic-claude-sonnet-5"),
    ("OpenAI", "gpt-5.5", "openai-gpt-5.5"),
]
ARMS = ["raw_model", "prompted_model", "rules_available_model"]
ARM_LABELS = {
    "raw_model": "raw_model",
    "prompted_model": "prompted_model",
    "rules_available_model": "rules_scaffold_model",
}
RUNTIME_DIR = "prismweft-runtime"


def read_summary(dirname: str) -> dict[str, dict]:
    with (ROOT / dirname / "summary.csv").open(newline="", encoding="utf-8") as f:
        return {r["arm"]: r for r in csv.DictReader(f)}


def read_runs(dirname: str) -> list[dict]:
    with (ROOT / dirname / "runs.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_raw_outputs(dirname: str) -> list[dict]:
    path = ROOT / dirname / "raw_outputs.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_manifest(dirname: str) -> dict:
    return json.loads((ROOT / dirname / "manifest.json").read_text(encoding="utf-8"))


def fmt(val: str | None, places: int) -> str:
    if val is None or val == "":
        return "n/a"
    try:
        return f"{float(val):.{places}f}"
    except ValueError:
        return str(val)


print("## FROZEN STATE (from manifest.json)\n")
manifests = {d: read_manifest(d) for _, _, d in MODELS}
manifests[RUNTIME_DIR] = read_manifest(RUNTIME_DIR)
commits = {d: m["execution_metadata"]["git"]["commit"] for d, m in manifests.items()}
dirtys = {d: m["execution_metadata"]["git"]["dirty"] for d, m in manifests.items()}
m0 = manifests[MODELS[0][2]]["execution_metadata"]
print(f"- git commits across bundles: {sorted(set(commits.values()))}")
print(f"- git dirty flags across bundles: {sorted(set(dirtys.values()))}")
print(f"- scorer version: {m0['scorer']['version']}")
print(f"- scorer note: {m0['scorer']['change_note']}")
print(f"- proof schema: {m0['proof']['schema_version']}")
ids = m0["proof"]["supported_scenario_ids"]
print(f"- proof supported ids ({len(ids)}): {ids}")
print(f"- python: {m0['python']['version']}")
cli0 = m0["cli"]
print(
    f"- live cli: max_output_tokens={cli0['max_output_tokens']} "
    f"temperature={cli0['temperature']} timeout_seconds={cli0['timeout_seconds']}"
)
print(f"- generated_at per bundle: {[(d, m['generated_at']) for d, m in manifests.items()]}")
print()

print("## PER-MODEL PER-ARM TABLE\n")
print(
    "| Provider | Model | Arm | Scenarios | Runs | Weighted Score | Esc. Recall | "
    "Severe Harm | Silent Drop | Empty Completions |"
)
print("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
for provider_label, model_id, dirname in MODELS:
    summ = read_summary(dirname)
    raw = read_raw_outputs(dirname)
    scen = len({r["scenario_id"] for r in read_runs(dirname)})
    for arm in ARMS:
        r = summ[arm]
        empty = sum(
            1
            for rec in raw
            if rec["raw_payload"].get("arm") == arm and not rec.get("response_text", "").strip()
        )
        print(
            f"| {provider_label} | `{model_id}` | `{ARM_LABELS[arm]}` | {scen} | {r['total_runs']} | "
            f"{fmt(r['overall_weighted_score'], 2)} | {fmt(r['escalation_recall'], 4)} | "
            f"{fmt(r['severe_harm_rate'], 4)} | {fmt(r['silent_constraint_drop_rate'], 4)} | {empty} |"
        )
rt = read_summary(RUNTIME_DIR)["prismweft_runtime"]
rt_runs = read_runs(RUNTIME_DIR)
rt_scen = len({r["scenario_id"] for r in rt_runs})
print(
    f"| Runtime subset | runtime engine (no API) | `prismweft_runtime` | {rt_scen} | {rt['total_runs']} | "
    f"{fmt(rt['overall_weighted_score'], 2)} | {fmt(rt['escalation_recall'], 4)} | "
    f"{fmt(rt['severe_harm_rate'], 4)} | {fmt(rt['silent_constraint_drop_rate'], 4)} | 0 |"
)
print(f"\nruntime witness_fidelity: {fmt(rt.get('witness_fidelity'), 4)}")
print()

print("## STOP-REASON MIX PER MODEL (live bundles, from raw_outputs.jsonl)\n")
for provider_label, model_id, dirname in MODELS:
    raw = read_raw_outputs(dirname)
    stops = Counter(rec["raw_payload"].get("stop_reason", "unknown") for rec in raw)
    cats = Counter(
        rec["raw_payload"]["stop_details_category"]
        for rec in raw
        if rec["raw_payload"].get("stop_details_category")
    )
    empty = sum(1 for rec in raw if not rec.get("response_text", "").strip())
    line = f"- `{model_id}`: stop_reason={dict(stops)}, empty_completions={empty}"
    if cats:
        line += f", stop_details_category={dict(cats)}"
    print(line)
    refusals = [rec for rec in raw if rec["raw_payload"].get("stop_reason") == "refusal"]
    if refusals:
        by_scenario = Counter(rec["raw_payload"]["scenario_id"] for rec in refusals)
        by_arm = Counter(rec["raw_payload"]["arm"] for rec in refusals)
        partial = sum(1 for rec in refusals if rec.get("response_text", "").strip())
        print(f"    refusals by scenario: {dict(sorted(by_scenario.items()))}")
        print(f"    refusals by arm: {dict(sorted(by_arm.items()))}")
        print(f"    refusals with partial text before mid-stream stop: {partial}")
print()

print("## RUNTIME WITNESS + DISPOSITION MIX (from manifest.json / runs.csv)\n")
rt_manifest = manifests[RUNTIME_DIR]
cap = rt_manifest["capability_summary"]
print(f"- runtime runs: {len(rt_runs)}")
print(f"- witness_mode counts: {cap['witness_mode_counts']}")
print(f"- proof_supported runs: {cap['proof_supported_runs']}")
print(f"- semantic_annotation runs: {cap['semantic_annotation_runs']}")
print(f"- runtime_disposition_coverage: {rt_manifest['runtime_disposition_coverage']}")
wm_check = Counter(r["witness_mode"] for r in rt_runs)
ps_check = sum(1 for r in rt_runs if r["proof_supported"] == "True")
print(f"- cross-check from runs.csv: witness_mode={dict(wm_check)}, proof_supported={ps_check}")
print()

print("## TOTALS\n")
total_live = sum(int(read_summary(d)[a]["total_runs"]) for _, _, d in MODELS for a in ARMS)
print(f"- total live baseline runs: {total_live}")
print(f"- runtime runs: {len(rt_runs)}")
print(f"- total scored runs: {total_live + len(rt_runs)}")
