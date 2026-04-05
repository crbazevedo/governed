"""Tests for GAP 2: TOML/dict governance profile loading + multi-domain."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from governed_agents import ActionContext, Verdict
from governed_agents.profile_loader import load_domain_config, load_pipeline_config, load_profile


# ── load_profile from dict ────────────────────────────────


class TestLoadProfileDict:
    def test_minimal_dict(self):
        profile = load_profile({"domain": "test"})
        assert profile.domain == "test"
        assert profile.default_vt == 2

    def test_full_dict(self):
        profile = load_profile(
            {
                "domain": "corporate",
                "default_vt": 3,
                "vt_floor": {"send_email": 2, "deploy": 4},
                "blocked_tools": ["personal_calendar"],
                "pii_sensitivity": 2,
                "audit_required": True,
            }
        )
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
        profile = load_profile(
            {
                "domain": "test",
                "blocked_tools": ["a", "b"],
            }
        )
        assert not profile.is_tool_allowed("a")
        assert not profile.is_tool_allowed("b")
        assert profile.is_tool_allowed("c")

    def test_blocked_tools_as_dict_with_tools_key(self):
        profile = load_profile(
            {
                "domain": "test",
                "blocked_tools": {"tools": ["x", "y"]},
            }
        )
        assert not profile.is_tool_allowed("x")
        assert not profile.is_tool_allowed("y")

    def test_allowed_tools(self):
        profile = load_profile(
            {
                "domain": "test",
                "allowed_tools": ["a", "b"],
            }
        )
        assert profile.is_tool_allowed("a")
        assert profile.is_tool_allowed("b")
        assert not profile.is_tool_allowed("c")

    def test_default_domain(self):
        profile = load_profile({})
        assert profile.domain == "default"


# ── load_pipeline_config from dict ────────────────────────


class TestLoadPipelineConfigDict:
    def test_basic_pipeline(self):
        pipeline = load_pipeline_config(
            {
                "handlers": ["pii_filter", "vt_governance"],
            }
        )
        assert len(pipeline.handlers) == 2

    def test_pipeline_with_config(self):
        pipeline = load_pipeline_config(
            {
                "handlers": ["rate_limiter", "vt_governance"],
                "rate_limiter": {"max_per_window": 20, "window_seconds": 120},
            }
        )
        assert len(pipeline.handlers) == 2

    def test_pipeline_audit_is_optional(self):
        pipeline = load_pipeline_config(
            {
                "handlers": ["vt", "audit"],
            }
        )
        # audit handler should be marked optional
        for reg in pipeline.handlers:
            if reg.handler.name == "audit_logger":
                assert reg.optional is True

    def test_full_pipeline(self):
        pipeline = load_pipeline_config(
            {
                "handlers": ["pii_filter", "rate_limiter", "vt_governance", "budget", "audit"],
                "rate_limiter": {"max_per_window": 10, "window_seconds": 60},
                "budget": {"limit_usd": 5.0},
            }
        )
        assert len(pipeline.handlers) == 5

    async def test_pipeline_executes(self):
        pipeline = load_pipeline_config(
            {
                "handlers": ["pii_filter", "vt_governance"],
            }
        )
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
        for alias in [
            "pii",
            "pii_filter",
            "rate_limit",
            "rate_limiter",
            "vt",
            "vt_governance",
            "audit",
            "audit_logger",
            "budget",
            "budget_gatekeeper",
            "compliance",
            "compliance_checker",
            "ux",
            "ux_handler",
        ]:
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


# ── Multi-domain loading (load_domain_config) ─────────────


class TestLoadDomainConfig:
    def test_basic_multi_domain(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "personal": {"default_vt": 1},
                    "corporate": {"default_vt": 2},
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        assert "personal" in cfg.profiles
        assert "corporate" in cfg.profiles
        assert cfg.profiles["personal"].default_vt == 1
        assert cfg.profiles["corporate"].default_vt == 2
        assert cfg.profiles["personal"].domain == "personal"
        assert cfg.profiles["corporate"].domain == "corporate"

    def test_barrier_created(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "personal": {"default_vt": 1},
                    "corporate": {"default_vt": 2},
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        assert cfg.barrier is not None
        assert cfg.barrier.name == "domain_barrier"

    def test_barrier_custom_allowed_fields(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "a": {"default_vt": 1},
                    "b": {"default_vt": 2},
                },
                "barrier": {"allowed_fields": ["timestamp", "urgency"]},
                "pipeline": {"handlers": ["vt"]},
            }
        )
        assert cfg.barrier._allowed_fields == frozenset({"timestamp", "urgency"})

    def test_pipeline_has_barrier_first(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "personal": {"default_vt": 1},
                },
                "pipeline": {"handlers": ["pii", "vt"]},
            }
        )
        handler_names = [r.handler.name for r in cfg.pipeline.handlers]
        assert handler_names[0] == "domain_barrier"
        # pii and vt follow
        assert "pii_filter" in handler_names
        assert "vt_governance" in handler_names

    def test_profiles_have_vt_floors(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "corporate": {
                        "default_vt": 2,
                        "vt_floor": {"send_email": 2, "deploy": 3},
                    },
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        corp = cfg.profiles["corporate"]
        assert corp.get_vt_floor("send_email") == 2
        assert corp.get_vt_floor("deploy") == 3
        assert corp.get_vt_floor("unknown") == 2  # default

    def test_profiles_have_blocked_tools(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "corporate": {
                        "default_vt": 2,
                        "blocked_tools": ["personal_calendar", "health_records"],
                    },
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        corp = cfg.profiles["corporate"]
        assert not corp.is_tool_allowed("personal_calendar")
        assert not corp.is_tool_allowed("health_records")
        assert corp.is_tool_allowed("search_docs")

    def test_no_domains_raises(self):
        with pytest.raises(ValueError, match="domains"):
            load_domain_config(
                {
                    "pipeline": {"handlers": ["vt"]},
                }
            )

    def test_empty_domains_raises(self):
        with pytest.raises(ValueError, match="domains"):
            load_domain_config(
                {
                    "domains": {},
                    "pipeline": {"handlers": ["vt"]},
                }
            )

    async def test_domain_elevates_vt(self):
        """Corporate domain should elevate VT floor for send_email."""
        cfg = load_domain_config(
            {
                "domains": {
                    "personal": {
                        "default_vt": 1,
                        "vt_floor": {"send_email": 1},
                    },
                    "corporate": {
                        "default_vt": 2,
                        "vt_floor": {"send_email": 2},
                    },
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        # Personal: VT1 action in VT1 domain -> allowed (VT1 = log)
        ctx_personal = ActionContext(
            action="send_email",
            agent_id="bot",
            vt_tier=1,
            metadata={"domain_scope": "personal"},
        )
        result_p = await cfg.pipeline.execute(ctx_personal)
        assert result_p.action != Verdict.BLOCK

        # Corporate: VT1 action in VT2 domain -> elevated to VT2 -> blocked
        ctx_corp = ActionContext(
            action="send_email",
            agent_id="bot",
            vt_tier=1,
            metadata={"domain_scope": "corporate"},
        )
        result_c = await cfg.pipeline.execute(ctx_corp)
        assert result_c.action == Verdict.BLOCK

    async def test_pipeline_executes_vt0(self):
        cfg = load_domain_config(
            {
                "domains": {
                    "personal": {"default_vt": 1},
                },
                "pipeline": {"handlers": ["vt"]},
            }
        )
        ctx = ActionContext(
            action="read",
            agent_id="bot",
            vt_tier=0,
            metadata={"domain_scope": "personal"},
        )
        result = await cfg.pipeline.execute(ctx)
        assert result.action == Verdict.ALLOW


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
class TestLoadDomainConfigFromTOML:
    def test_load_multi_domain_toml(self, tmp_path: Path):
        toml_content = b"""
[domains.personal]
default_vt = 1

[domains.personal.vt_floor]
send_email = 1

[domains.corporate]
default_vt = 2
audit_required = true

[domains.corporate.vt_floor]
send_email = 2
deploy = 3

[domains.corporate.blocked_tools]
tools = ["personal_calendar"]

[barrier]
allowed_fields = ["timestamp", "urgency"]

[pipeline]
handlers = ["pii", "vt", "audit"]
"""
        toml_file = tmp_path / "multi.toml"
        toml_file.write_bytes(toml_content)

        cfg = load_domain_config(toml_file)
        assert "personal" in cfg.profiles
        assert "corporate" in cfg.profiles
        assert cfg.profiles["corporate"].audit_required is True
        assert cfg.profiles["corporate"].get_vt_floor("deploy") == 3
        assert not cfg.profiles["corporate"].is_tool_allowed("personal_calendar")
        assert cfg.barrier._allowed_fields == frozenset({"timestamp", "urgency"})

    def test_load_example_toml_multi_domain(self):
        """The bundled governance.toml now has multi-domain config."""
        example = Path(__file__).parent.parent / "examples" / "governance.toml"
        if example.exists():
            cfg = load_domain_config(example)
            assert "personal" in cfg.profiles
            assert "corporate" in cfg.profiles
            assert len(cfg.pipeline.handlers) >= 3
