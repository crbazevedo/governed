"""Tests for GAP 2: TOML/dict governance profile loading."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from governed_agents import ActionContext, Verdict
from governed_agents.domain import GovernanceProfile
from governed_agents.profile_loader import load_pipeline_config, load_profile


# ── load_profile from dict ────────────────────────────────


class TestLoadProfileDict:
    def test_minimal_dict(self):
        profile = load_profile({"domain": "test"})
        assert profile.domain == "test"
        assert profile.default_vt == 2

    def test_full_dict(self):
        profile = load_profile({
            "domain": "corporate",
            "default_vt": 3,
            "vt_floor": {"send_email": 2, "deploy": 4},
            "blocked_tools": ["personal_calendar"],
            "pii_sensitivity": 2,
            "audit_required": True,
        })
        assert profile.domain == "corporate"
        assert profile.default_vt == 3
        assert profile.get_vt_floor("send_email") == 2
        assert profile.get_vt_floor("deploy") == 4
        assert profile.get_vt_floor("unknown") == 3  # default
        assert not profile.is_tool_allowed("personal_calendar")
        assert profile.is_tool_allowed("search_docs")
        assert profile.pii_sensitivity == 2
        assert profile.audit_required is True

    def test_blocked_tools_as_list(self):
        profile = load_profile({
            "domain": "test",
            "blocked_tools": ["a", "b"],
        })
        assert not profile.is_tool_allowed("a")
        assert not profile.is_tool_allowed("b")
        assert profile.is_tool_allowed("c")

    def test_blocked_tools_as_dict_with_tools_key(self):
        profile = load_profile({
            "domain": "test",
            "blocked_tools": {"tools": ["x", "y"]},
        })
        assert not profile.is_tool_allowed("x")
        assert not profile.is_tool_allowed("y")

    def test_allowed_tools(self):
        profile = load_profile({
            "domain": "test",
            "allowed_tools": ["a", "b"],
        })
        assert profile.is_tool_allowed("a")
        assert profile.is_tool_allowed("b")
        assert not profile.is_tool_allowed("c")

    def test_default_domain(self):
        profile = load_profile({})
        assert profile.domain == "default"


# ── load_pipeline_config from dict ────────────────────────


class TestLoadPipelineConfigDict:
    def test_basic_pipeline(self):
        pipeline = load_pipeline_config({
            "handlers": ["pii_filter", "vt_governance"],
        })
        assert len(pipeline.handlers) == 2

    def test_pipeline_with_config(self):
        pipeline = load_pipeline_config({
            "handlers": ["rate_limiter", "vt_governance"],
            "rate_limiter": {"max_per_window": 20, "window_seconds": 120},
        })
        assert len(pipeline.handlers) == 2

    def test_pipeline_audit_is_optional(self):
        pipeline = load_pipeline_config({
            "handlers": ["vt", "audit"],
        })
        # audit handler should be marked optional
        for reg in pipeline.handlers:
            if reg.handler.name == "audit_logger":
                assert reg.optional is True

    def test_full_pipeline(self):
        pipeline = load_pipeline_config({
            "handlers": ["pii_filter", "rate_limiter", "vt_governance", "budget", "audit"],
            "rate_limiter": {"max_per_window": 10, "window_seconds": 60},
            "budget": {"limit_usd": 5.0},
        })
        assert len(pipeline.handlers) == 5

    async def test_pipeline_executes(self):
        pipeline = load_pipeline_config({
            "handlers": ["pii_filter", "vt_governance"],
        })
        ctx = ActionContext(action="test", agent_id="bot", vt_tier=0)
        result = await pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW

    def test_empty_handlers_raises(self):
        with pytest.raises(ValueError, match="handlers"):
            load_pipeline_config({"handlers": []})

    def test_unknown_handler_raises(self):
        with pytest.raises(ValueError, match="Unknown handler"):
            load_pipeline_config({"handlers": ["nonexistent"]})

    def test_handler_aliases(self):
        """All aliases should produce valid handlers."""
        for alias in ["pii", "pii_filter", "rate_limit", "rate_limiter",
                       "vt", "vt_governance", "audit", "audit_logger",
                       "budget", "budget_gatekeeper", "compliance",
                       "compliance_checker", "ux", "ux_handler"]:
            pipeline = load_pipeline_config({"handlers": [alias]})
            assert len(pipeline.handlers) == 1


# ── TOML file loading ────────────────────────────────────


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
class TestLoadFromTOML:
    def test_load_profile_from_toml(self, tmp_path: Path):
        toml_content = b"""
[profile]
domain = "corporate"
default_vt = 2

[profile.vt_floor]
send_email = 2
deploy = 3

[profile.blocked_tools]
tools = ["personal_calendar"]
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_bytes(toml_content)

        profile = load_profile(toml_file)
        assert profile.domain == "corporate"
        assert profile.get_vt_floor("send_email") == 2
        assert not profile.is_tool_allowed("personal_calendar")

    def test_load_pipeline_from_toml(self, tmp_path: Path):
        toml_content = b"""
[pipeline]
handlers = ["pii_filter", "rate_limiter", "vt_governance"]

[pipeline.rate_limiter]
max_per_window = 10
window_seconds = 60
"""
        toml_file = tmp_path / "pipeline.toml"
        toml_file.write_bytes(toml_content)

        pipeline = load_pipeline_config(toml_file)
        assert len(pipeline.handlers) == 3

    def test_load_example_toml(self):
        """The bundled governance.toml example should load without error."""
        example = Path(__file__).parent.parent / "examples" / "governance.toml"
        if example.exists():
            pipeline = load_pipeline_config(example)
            assert len(pipeline.handlers) >= 3


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="Only tests 3.10 fallback")
class TestTOMLFallback:
    def test_toml_loading_raises_on_old_python(self, tmp_path: Path):
        toml_file = tmp_path / "test.toml"
        toml_file.write_text("[profile]\ndomain = 'test'\n")
        with pytest.raises(RuntimeError, match="Python 3.11"):
            load_profile(toml_file)
