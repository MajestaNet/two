# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the context broker (B05). No network."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from two.context import (
    CHARS_PER_TOKEN,
    COMPACTION_THRESHOLD_RATIO,
    DECLARED_CONTEXT_TOKENS,
    MAX_FILES_PER_SEARCH,
    MAX_LINES_PER_HIT,
    CodeExcerpt,
    ContextBudgetPolicy,
    FileInspection,
    TaskMemory,
    TestExecution,
    TokenBand,
    build_context_packet,
    build_review_handoff,
    default_context_budget,
    estimate_tokens,
    is_excluded_path,
    load_context_budget,
    load_task_memory,
    memory_path,
    query_lsp_symbols,
    save_task_memory,
    search_lexical,
    should_compact,
)
from two.validation.results import GateResult, ValidationResult

_RG_AVAILABLE = shutil.which("rg") is not None


def _memory(**overrides: object) -> TaskMemory:
    payload: dict[str, object] = {
        "task_id": "task-b05",
        "objective": "Add optimistic locking",
        "acceptance_criteria": ["No silent overwrite"],
        "plan": "Inspect lock helper, add test, patch updater",
        "current_step": "Inspect",
    }
    payload.update(overrides)
    return TaskMemory.model_validate(payload)


def test_memory_schema_rejects_transcript() -> None:
    with pytest.raises(ValidationError):
        TaskMemory.model_validate(
            {
                "task_id": "task-b05",
                "objective": "x",
                "transcript": "implementation chat",
            }
        )
    with pytest.raises(ValidationError):
        TaskMemory.model_validate(
            {
                "task_id": "task-b05",
                "objective": "x",
                "reasoning": "free-form",
            }
        )


def test_memory_json_round_trip(tmp_path: Path) -> None:
    memory = _memory(
        files_inspected=[FileInspection(path="src/app.py", reason="updater")],
        files_changed=["src/app.py"],
        tests_executed=[TestExecution(command="make test", passed=True, exit_code=0)],
        unresolved_hypotheses=["lock key may be tenant-scoped"],
        blockers=[],
        next_actions=["write the test"],
    )
    path = save_task_memory(memory, data_dir=tmp_path)
    assert path == tmp_path / "tasks" / "task-b05" / "memory.json"
    assert path == memory_path("task-b05", data_dir=tmp_path)
    loaded = load_task_memory("task-b05", data_dir=tmp_path)
    assert loaded == memory
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "transcript" not in raw
    assert "reasoning" not in raw
    assert raw["objective"] == memory.objective
    assert raw["files_changed"] == ["src/app.py"]


def test_inventory_excludes_vendor_and_generated_paths() -> None:
    assert is_excluded_path(".venv/lib/site.py")
    assert is_excluded_path("node_modules/pkg/index.js")
    assert is_excluded_path("vendor/foo.c")
    assert is_excluded_path("dist/bundle.min.js")
    assert is_excluded_path("build/out.js")
    assert is_excluded_path("src/app.min.js")
    assert is_excluded_path(".env")
    assert not is_excluded_path("src/two/context/memory.py")
    assert not is_excluded_path("README.md")


def test_missing_rg_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("rg")

    monkeypatch.setattr("two.context.search._run_rg", _missing)
    result = search_lexical(tmp_path, "UNIQUE_BROKER_TOKEN")
    assert result.status == "unavailable"
    assert "rg" in result.reason
    assert result.excerpts == []


@pytest.mark.skipif(not _RG_AVAILABLE, reason="rg not on PATH")
def test_rg_returns_excerpts_not_whole_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    lines = [f"padding line {index}" for index in range(1, 81)]
    lines[39] = "UNIQUE_BROKER_TOKEN = 1"
    (src / "wide.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "hidden.py").write_text(
        "UNIQUE_BROKER_TOKEN = hidden\n",
        encoding="utf-8",
    )
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text(
        "const UNIQUE_BROKER_TOKEN = 2;\n",
        encoding="utf-8",
    )

    result = search_lexical(tmp_path, "UNIQUE_BROKER_TOKEN", max_lines_per_hit=8)
    assert result.status == "ok"
    assert result.excerpts
    for excerpt in result.excerpts:
        assert excerpt.path != "wide.py" or excerpt.text.count("\n") + 1 <= 10
        assert "padding line 1" not in excerpt.text or excerpt.start_line > 1
        assert not excerpt.path.startswith(".venv/")
        assert not excerpt.path.startswith("node_modules/")
        assert len(excerpt.text.splitlines()) <= MAX_LINES_PER_HIT + 1
    wide = next(item for item in result.excerpts if item.path.endswith("wide.py"))
    assert "UNIQUE_BROKER_TOKEN" in wide.text
    assert wide.start_line >= 1
    whole = (src / "wide.py").read_text(encoding="utf-8")
    assert wide.text != whole
    assert len(wide.text) < len(whole)


def test_packet_builder_truncates_over_budget() -> None:
    memory = _memory(plan="x" * 40)
    huge = "y" * 400
    excerpts = [
        CodeExcerpt(path="a.py", start_line=1, end_line=20, text=huge, source="rg"),
        CodeExcerpt(path="b.py", start_line=1, end_line=20, text=huge, source="rg"),
        CodeExcerpt(
            path="node_modules/skip.js",
            start_line=1,
            end_line=2,
            text="should not appear",
            source="rg",
        ),
    ]
    policy = default_context_budget().model_copy(
        update={
            "budgets": default_context_budget().budgets.model_copy(
                update={
                    "task_memory_and_plan": TokenBand(
                        min_tokens=1, max_tokens=2000, target_tokens=1500
                    ),
                    "retrieved_code_and_diagnostics": TokenBand(
                        min_tokens=1, max_tokens=30, target_tokens=20
                    ),
                }
            )
        }
    )
    packet = build_context_packet(memory, excerpts, policy=policy)
    assert packet.truncated
    assert packet.estimated_excerpt_tokens <= 30
    assert estimate_tokens("".join(item.text for item in packet.excerpts)) <= 30
    assert all(not item.path.startswith("node_modules/") for item in packet.excerpts)
    assert packet.omitted_excerpts >= 1
    assert packet.estimated_memory_tokens <= 2000


def test_packet_builder_compacts_memory_lists() -> None:
    inspected = [
        FileInspection(path=f"src/file_{index}.py", reason="why " * 20) for index in range(40)
    ]
    memory = _memory(files_inspected=inspected)
    policy = default_context_budget().model_copy(
        update={
            "budgets": default_context_budget().budgets.model_copy(
                update={
                    "task_memory_and_plan": TokenBand(
                        min_tokens=1, max_tokens=80, target_tokens=40
                    ),
                    "retrieved_code_and_diagnostics": TokenBand(
                        min_tokens=1, max_tokens=10, target_tokens=8
                    ),
                }
            )
        }
    )
    original = estimate_tokens(memory.model_dump_json(exclude_defaults=True))
    packet = build_context_packet(memory, [], policy=policy)
    assert packet.truncated
    assert len(packet.memory.files_inspected) < len(inspected)
    assert packet.estimated_memory_tokens < original


def test_estimate_tokens_character_heuristic() -> None:
    assert CHARS_PER_TOKEN == 4
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_context_budget_yaml_and_compaction() -> None:
    policy = load_context_budget()
    assert policy.declared_context_tokens == DECLARED_CONTEXT_TOKENS
    assert policy.compaction_threshold_ratio == COMPACTION_THRESHOLD_RATIO
    assert 0.70 <= policy.compaction_threshold_ratio <= 0.75
    assert policy.compaction_start_tokens == int(16384 * 0.72)
    assert policy.budgets.system_tool_policy.min_tokens == 2000
    assert policy.budgets.system_tool_policy.max_tokens == 3000
    assert policy.budgets.task_memory_and_plan.max_tokens == 2000
    assert policy.budgets.retrieved_code_and_diagnostics.max_tokens == 7000
    assert policy.budgets.reserved_model_output.max_tokens == 8000
    assert policy.retrieval.max_files_per_search == MAX_FILES_PER_SEARCH
    assert policy.retrieval.max_lines_per_hit == MAX_LINES_PER_HIT
    assert should_compact(policy.compaction_start_tokens, policy)
    assert not should_compact(policy.compaction_start_tokens - 1, policy)
    with pytest.raises(ValidationError):
        ContextBudgetPolicy.model_validate(
            {
                **policy.model_dump(),
                "compaction_threshold_ratio": 0.9,
            }
        )


def test_lsp_unavailable_does_not_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWO_LSP_ENDPOINT", raising=False)
    result = query_lsp_symbols(tmp_path, "TaskMemory")
    assert result.status == "unavailable"
    assert "no language server" in result.reason
    assert result.names == []


def test_review_handoff_has_no_transcript(tmp_path: Path) -> None:
    memory = _memory(
        files_changed=["src/app.py"],
        tests_executed=[TestExecution(command="make test", passed=True, exit_code=0, summary="ok")],
        next_actions=["fresh review"],
    )
    validation = ValidationResult(
        passed=True,
        gates=[GateResult(name="test", passed=True, exit_code=0, summary="ok", duration_ms=3)],
        artifact_dir=tmp_path / "validation",
        worktree=tmp_path / "worktree",
        task_id="task-b05",
    )
    handoff = build_review_handoff(
        memory,
        diff_summary="1 file changed, 3 insertions(+)",
        validation=validation,
    )
    dumped = handoff.model_dump()
    assert "transcript" not in dumped
    assert "reasoning" not in dumped
    assert handoff.objective == memory.objective
    assert handoff.acceptance_criteria == memory.acceptance_criteria
    assert handoff.diff_summary.startswith("1 file changed")
    assert handoff.validation_passed is True
    assert handoff.files_changed == ["src/app.py"]
    rendered = handoff.render()
    assert "implementation transcript" in rendered
    assert "Task lifecycle is not set" in rendered
    assert "COMPLETE" not in rendered
