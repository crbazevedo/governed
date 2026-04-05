"""Load governance profiles from TOML/dict configuration.

# Layer: Persistent (configuration-driven)

Define governance policies declaratively instead of in code.
Uses TOML (Python 3.11+ stdlib ``tomllib``) or plain dicts for 3.10.
No new dependencies -- TOML parsing is stdlib.

This bridges the gap between "code-defined governance" and
"config-driven governance": operators can change policies by editing
a TOML file instead of redeploying code.

Supports both single-domain and multi-domain configurations.

Single-domain example (governance.toml)::

    [profile]
    domain = "corporate"
    default_vt = 2

    [profile.vt_floor]
    read_email = 0
    send_email = 2

    [pipeline]
    handlers = ["pii_filter", "vt_governance", "audit"]

Multi-domain example (governance.toml)::

    [domains.personal]
    default_vt = 1
    pii_sensitivity = 1

    [domains.personal.vt_floor]
    read_email = 0
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
    allowed_fields = ["timestamp", "duration_minutes", "urgency", "action_type"]

    [pipeline]
    handlers = ["pii", "blast_radius", "trust_evolution", "vt", "audit"]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from governed_agents.domain import DomainBarrierHandler, GovernanceProfile
from governed_agents.pipeline import GovernancePipeline

if TYPE_CHECKING:
    from governed_agents.handler import GovernanceHandler

# Use tomllib (3.11+) or fall back to no TOML support on 3.10
if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]

    HAS_TOML = True
else:
    HAS_TOML = False


def _read_toml(path: str | Path) -> dict[str, Any]:
    """Read a TOML file and return as a dict.

    Raises:
        RuntimeError: If Python < 3.11 (no stdlib TOML parser).
        FileNotFoundError: If the file doesn't exist.
    """
    if not HAS_TOML:
        raise RuntimeError(
            "TOML loading requires Python 3.11+ (stdlib tomllib). "
            "On Python 3.10, use load_profile(dict) instead."
        )
    path = Path(path)
    with path.open("rb") as f:
        return tomllib.load(f)


def load_profile(source: str | Path | dict[str, Any]) -> GovernanceProfile:
    """Load a GovernanceProfile from a TOML file path or a plain dict.

    This is the primary entry point for declarative governance configuration.
    Pass a file path (str or Path) to load from TOML, or a dict for
    programmatic configuration (works on all Python versions).

    Args:
        source: Path to a TOML file, or a dict with profile configuration.

    Returns:
        A GovernanceProfile instance ready for use with DomainBarrierHandler.

    Raises:
        RuntimeError: If TOML loading is attempted on Python < 3.11.
        KeyError: If the config dict is missing required fields.

    Example dict input::

        load_profile({
            "domain": "corporate",
            "default_vt": 2,
            "vt_floor": {"send_email": 2, "deploy": 3},
            "blocked_tools": ["personal_calendar"],
        })
    """
    if isinstance(source, (str, Path)):
        raw = _read_toml(source)
        config = raw.get("profile", raw)
    else:
        config = source

    # Parse vt_floor
    vt_floor: dict[str, int] = {}
    raw_floor = config.get("vt_floor", {})
    if isinstance(raw_floor, dict):
        vt_floor = {k: int(v) for k, v in raw_floor.items()}

    # Parse blocked_tools
    blocked_tools: set[str] = set()
    raw_blocked = config.get("blocked_tools", {})
    if isinstance(raw_blocked, dict):
        # TOML: [profile.blocked_tools] tools = [...]
        blocked_tools = set(raw_blocked.get("tools", []))
    elif isinstance(raw_blocked, (list, set)):
        blocked_tools = set(raw_blocked)

    # Parse allowed_tools
    allowed_tools: set[str] | None = None
    raw_allowed = config.get("allowed_tools", None)
    if raw_allowed is not None:
        if isinstance(raw_allowed, dict):
            allowed_tools = set(raw_allowed.get("tools", []))
        elif isinstance(raw_allowed, (list, set)):
            allowed_tools = set(raw_allowed)

    return GovernanceProfile(
        domain=config.get("domain", "default"),
        vt_floor=vt_floor,
        default_vt=int(config.get("default_vt", 2)),
        blocked_tools=blocked_tools,
        allowed_tools=allowed_tools,
        pii_sensitivity=int(config.get("pii_sensitivity", 1)),
        audit_required=bool(config.get("audit_required", False)),
        metadata=config.get("metadata", {}),
    )


# ──────────────────────────────────────────────
# Handler registry for declarative pipeline config
# ──────────────────────────────────────────────

_HANDLER_REGISTRY: dict[str, type[GovernanceHandler]] = {}


def _ensure_registry() -> dict[str, type[GovernanceHandler]]:
    """Lazy-initialize the handler name -> class registry.

    This avoids circular imports by deferring handler imports until needed.
    """
    if _HANDLER_REGISTRY:
        return _HANDLER_REGISTRY

    from governed_agents.blast_radius import BlastRadiusHandler
    from governed_agents.handlers.audit import AuditLogger
    from governed_agents.handlers.budget import BudgetGatekeeper
    from governed_agents.handlers.compliance import ComplianceChecker
    from governed_agents.handlers.pii_filter import PIIFilter
    from governed_agents.handlers.rate_limiter import RateLimiter
    from governed_agents.handlers.ux import UXHandler
    from governed_agents.trust import TrustEvolutionHandler
    from governed_agents.vt import VTGovernanceHandler

    _HANDLER_REGISTRY.update(
        {
            "pii_filter": PIIFilter,
            "pii": PIIFilter,
            "rate_limiter": RateLimiter,
            "rate_limit": RateLimiter,
            "vt_governance": VTGovernanceHandler,
            "vt": VTGovernanceHandler,
            "audit": AuditLogger,
            "audit_logger": AuditLogger,
            "budget": BudgetGatekeeper,
            "budget_gatekeeper": BudgetGatekeeper,
            "compliance": ComplianceChecker,
            "compliance_checker": ComplianceChecker,
            "ux": UXHandler,
            "ux_handler": UXHandler,
            "blast_radius": BlastRadiusHandler,
            "trust_evolution": TrustEvolutionHandler,
        }
    )

    return _HANDLER_REGISTRY


def _build_handler(name: str, handler_config: dict[str, Any]) -> GovernanceHandler:
    """Instantiate a handler by name with optional config kwargs."""
    registry = _ensure_registry()
    handler_cls = registry.get(name)
    if handler_cls is None:
        available = sorted({cls.__name__ for cls in registry.values()})
        raise ValueError(f"Unknown handler '{name}'. Available: {', '.join(available)}")

    # Map config keys to constructor kwargs
    kwargs: dict[str, Any] = {}

    if name in ("rate_limiter", "rate_limit") and handler_config:
        if "max_per_window" in handler_config:
            kwargs["max_per_window"] = int(handler_config["max_per_window"])
        if "window_seconds" in handler_config:
            kwargs["window_seconds"] = int(handler_config["window_seconds"])

    elif name in ("budget", "budget_gatekeeper") and handler_config:
        if "limit_usd" in handler_config:
            kwargs["budget_limit_usd"] = float(handler_config["limit_usd"])

    elif name in ("pii_filter", "pii") and handler_config:
        if "redact" in handler_config:
            kwargs["redact"] = bool(handler_config["redact"])
        if "patterns" in handler_config:
            kwargs["patterns"] = list(handler_config["patterns"])

    elif name in ("compliance", "compliance_checker") and handler_config:
        if "max_payload_kb" in handler_config:
            kwargs["max_payload_kb"] = int(handler_config["max_payload_kb"])
        if "strict_mode" in handler_config:
            kwargs["strict_mode"] = bool(handler_config["strict_mode"])

    elif name == "blast_radius":
        from governed_agents.blast_radius import BlastRadiusPolicy

        kwargs["policy"] = BlastRadiusPolicy()

    elif name == "trust_evolution":
        from governed_agents.trust import TrustLedger

        kwargs["ledger"] = TrustLedger()

    return handler_cls(**kwargs)


def load_pipeline_config(
    source: str | Path | dict[str, Any],
) -> GovernancePipeline:
    """Build a complete GovernancePipeline from declarative configuration.

    Reads a TOML file or dict and constructs a pipeline with the specified
    handlers and their configurations.

    Args:
        source: Path to a TOML file, or a dict with pipeline configuration.

    Returns:
        A fully configured GovernancePipeline ready for ``execute()``.

    Example dict input::

        load_pipeline_config({
            "handlers": ["pii_filter", "rate_limiter", "vt_governance", "audit"],
            "rate_limiter": {"max_per_window": 10, "window_seconds": 60},
            "budget": {"limit_usd": 5.0},
        })
    """
    if isinstance(source, (str, Path)):
        raw = _read_toml(source)
        config = raw.get("pipeline", raw)
    else:
        config = source

    handler_names = config.get("handlers", [])
    if not handler_names:
        raise ValueError("Pipeline config must include a 'handlers' list")

    pipeline = GovernancePipeline()

    # "audit" handlers are marked optional by convention
    optional_handlers = {"audit", "audit_logger"}

    for name in handler_names:
        handler_config = config.get(name, {})
        handler = _build_handler(name, handler_config)
        pipeline.add(handler, optional=(name in optional_handlers))

    return pipeline


# ──────────────────────────────────────────────
# Multi-domain configuration
# ──────────────────────────────────────────────


@dataclass
class DomainConfig:
    """Result of loading a multi-domain governance configuration.

    Attributes:
        profiles: Dict mapping domain name to GovernanceProfile.
        barrier: A DomainBarrierHandler configured with the profiles.
        pipeline: A GovernancePipeline with the barrier prepended and
                  remaining handlers from the ``[pipeline]`` section.
    """

    profiles: dict[str, GovernanceProfile]
    barrier: DomainBarrierHandler
    pipeline: GovernancePipeline


def load_domain_config(
    source: str | Path | dict[str, Any],
) -> DomainConfig:
    """Load a multi-domain governance configuration.

    Reads a TOML file or dict containing a ``[domains.*]`` section with
    per-domain profiles, a ``[barrier]`` section with allowed cross-domain
    fields, and a ``[pipeline]`` section with handler names.

    The resulting pipeline has the DomainBarrierHandler prepended at the
    lowest priority, followed by the declared handlers.

    Args:
        source: Path to a TOML file, or a dict with multi-domain config.

    Returns:
        A DomainConfig containing profiles, barrier, and pipeline.

    Raises:
        ValueError: If no domains are defined.

    Example TOML::

        [domains.personal]
        default_vt = 1

        [domains.personal.vt_floor]
        read_email = 0
        send_email = 1

        [domains.corporate]
        default_vt = 2

        [domains.corporate.vt_floor]
        send_email = 2
        deploy = 3

        [barrier]
        allowed_fields = ["timestamp", "urgency"]

        [pipeline]
        handlers = ["pii", "vt", "audit"]

    Example dict::

        load_domain_config({
            "domains": {
                "personal": {"default_vt": 1, "vt_floor": {"send_email": 1}},
                "corporate": {"default_vt": 2, "vt_floor": {"send_email": 2}},
            },
            "barrier": {"allowed_fields": ["timestamp"]},
            "pipeline": {"handlers": ["pii", "vt", "audit"]},
        })
    """
    if isinstance(source, (str, Path)):
        raw = _read_toml(source)
    else:
        raw = source

    domains_raw = raw.get("domains", {})
    if not domains_raw:
        raise ValueError(
            "Multi-domain config must include a 'domains' section with at least one domain."
        )

    # Build profiles per domain
    profiles: dict[str, GovernanceProfile] = {}
    for domain_name, domain_conf in domains_raw.items():
        # Inject domain name so load_profile can use it
        conf = dict(domain_conf)
        conf.setdefault("domain", domain_name)
        profiles[domain_name] = load_profile(conf)

    # Build barrier handler
    barrier_conf = raw.get("barrier", {})
    allowed_fields_raw = barrier_conf.get("allowed_fields", None)
    if allowed_fields_raw is not None:
        allowed_fields = frozenset(allowed_fields_raw)
    else:
        # Use library default
        from governed_agents.domain import CROSS_DOMAIN_ALLOWED_FIELDS

        allowed_fields = CROSS_DOMAIN_ALLOWED_FIELDS

    barrier = DomainBarrierHandler(profiles=profiles, allowed_fields=allowed_fields)

    # Build pipeline with barrier prepended
    pipeline = GovernancePipeline()
    pipeline.register(barrier, priority=1)

    pipeline_conf = raw.get("pipeline", {})
    handler_names = pipeline_conf.get("handlers", [])

    optional_handlers = {"audit", "audit_logger"}

    for name in handler_names:
        handler_config = pipeline_conf.get(name, {})
        handler = _build_handler(name, handler_config)
        pipeline.add(handler, optional=(name in optional_handlers))

    return DomainConfig(
        profiles=profiles,
        barrier=barrier,
        pipeline=pipeline,
    )
