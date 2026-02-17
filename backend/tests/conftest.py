"""Shared fixtures for backend tests."""

from __future__ import annotations

import json
import pytest


# ── Minimal CKP fixtures ────────────────────────────────────────


@pytest.fixture
def minimal_ckp() -> dict:
    """Smallest valid CKP document."""
    return {
        "procedure_id": "test_proc",
        "version": "1.0.0",
        "global_config": {"max_retries": 2, "retry_delay_ms": 500},
        "variables_schema": {"greeting": {"type": "string", "default": "hello"}},
        "workflow_graph": {
            "start_node": "start",
            "nodes": {
                "start": {
                    "type": "sequence",
                    "description": "Start node",
                    "next_node": "end",
                    "steps": [
                        {
                            "step_id": "log_hello",
                            "action": "log",
                            "message": "Hello from test",
                        }
                    ],
                },
                "end": {
                    "type": "terminate",
                    "status": "success",
                },
            },
        },
    }


@pytest.fixture
def complex_ckp() -> dict:
    """CKP with multiple node types for comprehensive testing."""
    return {
        "procedure_id": "complex_proc",
        "version": "2.0.0",
        "global_config": {
            "max_retries": 3,
            "retry_delay_ms": 1000,
            "timeout_ms": 60000,
            "secrets_config": {
                "provider": "env_vars",
                "secret_references": {
                    "api_key": "API_KEY",
                    "db_password": "DB_PASSWORD",
                },
            },
        },
        "variables_schema": {
            "items": {"type": "array", "default": [1, 2, 3]},
        },
        "workflow_graph": {
            "start_node": "init",
            "nodes": {
                "init": {
                    "type": "sequence",
                    "agent": "MasterAgent",
                    "next_node": "decide",
                    "is_checkpoint": True,
                    "steps": [
                        {"step_id": "s1", "action": "log", "message": "init"},
                        {"step_id": "s2", "action": "set_variable", "variable": "x", "value": 10},
                    ],
                },
                "decide": {
                    "type": "logic",
                    "rules": [
                        {"condition": "vars.x > 5", "next_node": "process"},
                        {"condition": "vars.x <= 5", "next_node": "skip"},
                    ],
                    "default_next_node": "skip",
                },
                "process": {
                    "type": "loop",
                    "iterator": "items",
                    "iterator_variable": "current_item",
                    "body_node": "loop_body",
                    "next_node": "finish",
                    "max_iterations": 100,
                },
                "loop_body": {
                    "type": "sequence",
                    "steps": [
                        {"step_id": "lb1", "action": "log", "message": "processing"},
                    ],
                },
                "skip": {
                    "type": "processing",
                    "operations": [
                        {"action": "log", "message": "skipped"},
                    ],
                    "next_node": "finish",
                },
                "finish": {
                    "type": "terminate",
                    "status": "success",
                    "outputs": {"result": "done"},
                },
            },
        },
    }


@pytest.fixture
def invalid_ckp_missing_start() -> dict:
    """CKP with missing start node reference."""
    return {
        "procedure_id": "broken_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "nonexistent_node",
            "nodes": {
                "step1": {
                    "type": "sequence",
                    "steps": [],
                },
            },
        },
    }


@pytest.fixture
def invalid_ckp_dangling_ref() -> dict:
    """CKP with dangling next_node reference."""
    return {
        "procedure_id": "dangling_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "step1",
            "nodes": {
                "step1": {
                    "type": "sequence",
                    "next_node": "does_not_exist",
                    "steps": [],
                },
            },
        },
    }


@pytest.fixture
def ckp_with_parallel() -> dict:
    """CKP with parallel node type."""
    return {
        "procedure_id": "parallel_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "par",
            "nodes": {
                "par": {
                    "type": "parallel",
                    "branches": [
                        {"branch_id": "b1", "start_node": "branch1"},
                        {"branch_id": "b2", "start_node": "branch2"},
                    ],
                    "wait_strategy": "all",
                    "next_node": "end",
                },
                "branch1": {
                    "type": "sequence",
                    "steps": [{"step_id": "bs1", "action": "log", "message": "branch1"}],
                },
                "branch2": {
                    "type": "sequence",
                    "steps": [{"step_id": "bs2", "action": "log", "message": "branch2"}],
                },
                "end": {
                    "type": "terminate",
                    "status": "success",
                },
            },
        },
    }


@pytest.fixture
def ckp_with_human_approval() -> dict:
    """CKP with human approval node."""
    return {
        "procedure_id": "approval_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "approval",
            "nodes": {
                "approval": {
                    "type": "human_approval",
                    "prompt": "Do you approve?",
                    "decision_type": "approve_reject",
                    "on_approve": "approved",
                    "on_reject": "rejected",
                    "on_timeout": "timeout",
                    "timeout_ms": 5000,
                },
                "approved": {"type": "terminate", "status": "success"},
                "rejected": {"type": "terminate", "status": "failed"},
                "timeout": {"type": "terminate", "status": "failed"},
            },
        },
    }


@pytest.fixture
def ckp_with_llm_action() -> dict:
    """CKP with LLM action node."""
    return {
        "procedure_id": "llm_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "llm_step",
            "nodes": {
                "llm_step": {
                    "type": "llm_action",
                    "prompt": "Summarize the document",
                    "model": "gpt-4",
                    "temperature": 0.5,
                    "max_tokens": 1000,
                    "attachments": [
                        {
                            "type": "file",
                            "source": "document.pdf",
                            "description": "The document to summarize",
                        }
                    ],
                    "outputs": {"summary": "summary_var"},
                    "next_node": "end",
                },
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }


@pytest.fixture
def ckp_with_transform() -> dict:
    """CKP with transform node."""
    return {
        "procedure_id": "transform_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "transform",
            "nodes": {
                "transform": {
                    "type": "transform",
                    "transformations": [
                        {
                            "type": "map",
                            "source_variable": "items",
                            "expression": "item.name",
                            "output_variable": "names",
                        }
                    ],
                    "next_node": "end",
                },
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }


@pytest.fixture
def ckp_with_subflow() -> dict:
    """CKP with subflow node."""
    return {
        "procedure_id": "parent_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "sub",
            "nodes": {
                "sub": {
                    "type": "subflow",
                    "procedure_id": "child_proc",
                    "version": "1.0.0",
                    "input_mapping": {"parent_var": "child_var"},
                    "output_mapping": {"child_result": "parent_result"},
                    "on_failure": "fail_parent",
                    "next_node": "end",
                },
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }
