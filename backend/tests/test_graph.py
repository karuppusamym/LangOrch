"""Tests for the graph extraction service."""

from __future__ import annotations

import pytest

from app.services.graph_service import extract_graph


class TestExtractGraph:
    """Tests for extract_graph()."""

    def test_empty_graph(self):
        result = extract_graph({})
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_single_terminate_node(self):
        wg = {
            "start_node": "end",
            "nodes": {"end": {"type": "terminate", "status": "success"}},
        }
        result = extract_graph(wg)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "end"
        assert result["nodes"][0]["data"]["nodeType"] == "terminate"
        assert result["nodes"][0]["data"]["isStart"] is True
        assert result["edges"] == []

    def test_linear_sequence(self):
        wg = {
            "start_node": "a",
            "nodes": {
                "a": {"type": "sequence", "next_node": "b"},
                "b": {"type": "sequence", "next_node": "c"},
                "c": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2
        sources = [(e["source"], e["target"]) for e in result["edges"]]
        assert ("a", "b") in sources
        assert ("b", "c") in sources

    def test_logic_node_edges(self):
        wg = {
            "start_node": "decide",
            "nodes": {
                "decide": {
                    "type": "logic",
                    "rules": [
                        {"condition": "x > 10", "next_node": "high"},
                        {"condition": "x <= 10", "next_node": "low"},
                    ],
                    "default_next_node": "fallback",
                },
                "high": {"type": "terminate", "status": "success"},
                "low": {"type": "terminate", "status": "success"},
                "fallback": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        assert len(result["nodes"]) == 4
        # 2 rule edges + 1 default
        logic_edges = [e for e in result["edges"] if e["source"] == "decide"]
        assert len(logic_edges) == 3
        targets = {e["target"] for e in logic_edges}
        assert targets == {"high", "low", "fallback"}
        # All conditional edges should be animated
        assert all(e["animated"] for e in logic_edges)

    def test_human_approval_edges(self):
        wg = {
            "start_node": "approve",
            "nodes": {
                "approve": {
                    "type": "human_approval",
                    "on_approve": "yes",
                    "on_reject": "no",
                    "on_timeout": "timeout",
                },
                "yes": {"type": "terminate", "status": "success"},
                "no": {"type": "terminate", "status": "failed"},
                "timeout": {"type": "terminate", "status": "failed"},
            },
        }
        result = extract_graph(wg)
        approval_edges = [e for e in result["edges"] if e["source"] == "approve"]
        assert len(approval_edges) == 3
        labels = {e["label"] for e in approval_edges}
        assert labels == {"approve", "reject", "timeout"}

    def test_loop_edges(self):
        wg = {
            "start_node": "loop",
            "nodes": {
                "loop": {
                    "type": "loop",
                    "body_node": "body",
                    "next_node": "done",
                },
                "body": {"type": "sequence", "next_node": None},
                "done": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        loop_edges = [e for e in result["edges"] if e["source"] == "loop"]
        assert len(loop_edges) == 2
        targets = {e["target"] for e in loop_edges}
        assert targets == {"body", "done"}

    def test_parallel_branch_edges(self):
        wg = {
            "start_node": "par",
            "nodes": {
                "par": {
                    "type": "parallel",
                    "branches": [
                        {"branch_id": "b1", "start_node": "task1"},
                        {"branch_id": "b2", "start_node": "task2"},
                    ],
                    "next_node": "merge",
                },
                "task1": {"type": "sequence", "next_node": None},
                "task2": {"type": "sequence", "next_node": None},
                "merge": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        par_edges = [e for e in result["edges"] if e["source"] == "par"]
        # 2 branch edges + 1 next_node
        assert len(par_edges) == 3
        targets = {e["target"] for e in par_edges}
        assert targets == {"task1", "task2", "merge"}

    def test_node_positions_auto_layout(self):
        wg = {
            "start_node": "a",
            "nodes": {
                "a": {"type": "sequence", "next_node": "b"},
                "b": {"type": "sequence", "next_node": "c"},
                "c": {"type": "sequence", "next_node": "d"},
                "d": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        positions = [n["position"] for n in result["nodes"]]
        # Verify all nodes have position
        assert all("x" in p and "y" in p for p in positions)

    def test_node_colors(self):
        wg = {
            "start_node": "s",
            "nodes": {
                "s": {"type": "sequence", "next_node": "l"},
                "l": {"type": "logic", "rules": [], "default_next_node": "t"},
                "t": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        colors = {n["data"]["nodeType"]: n["data"]["color"] for n in result["nodes"]}
        assert colors["sequence"] == "#3B82F6"
        assert colors["logic"] == "#F59E0B"
        assert colors["terminate"] == "#6B7280"

    def test_dangling_next_node_ignored(self):
        """Edges to non-existent nodes should be dropped."""
        wg = {
            "start_node": "a",
            "nodes": {
                "a": {"type": "sequence", "next_node": "nonexistent"},
            },
        }
        result = extract_graph(wg)
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 0

    def test_agent_in_data(self):
        wg = {
            "start_node": "s",
            "nodes": {
                "s": {"type": "sequence", "agent": "EmailBot", "next_node": None},
            },
        }
        result = extract_graph(wg)
        assert result["nodes"][0]["data"]["agent"] == "EmailBot"

    def test_description_as_label(self):
        wg = {
            "start_node": "s",
            "nodes": {
                "s": {"type": "sequence", "description": "My Step", "next_node": None},
            },
        }
        result = extract_graph(wg)
        assert result["nodes"][0]["data"]["label"] == "My Step"

    def test_sample_multi_agent_workflow(self):
        """Smoke test with a realistic workflow structure."""
        wg = {
            "start_node": "init_workflow",
            "nodes": {
                "init_workflow": {"type": "sequence", "agent": "MasterAgent", "next_node": "fetch_emails"},
                "fetch_emails": {"type": "sequence", "agent": "EMAIL", "next_node": "parse_invoice_data"},
                "parse_invoice_data": {"type": "processing", "agent": "MasterAgent", "next_node": "validate_invoice_count"},
                "validate_invoice_count": {
                    "type": "logic",
                    "agent": "MasterAgent",
                    "rules": [
                        {"condition": "has_invoices", "next_node": "loop_invoices"},
                    ],
                    "default_next_node": "no_invoices_node",
                },
                "loop_invoices": {
                    "type": "loop",
                    "body_node": "process_in_erp",
                    "next_node": "workflow_complete",
                },
                "process_in_erp": {"type": "sequence", "agent": "DESKTOP", "next_node": None},
                "no_invoices_node": {"type": "processing", "next_node": "workflow_complete"},
                "workflow_complete": {"type": "terminate", "status": "success"},
            },
        }
        result = extract_graph(wg)
        assert len(result["nodes"]) == 8
        assert len(result["edges"]) > 0
        # All nodes reachable from start
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == set(wg["nodes"].keys())
