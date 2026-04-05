# Configuration

`governed-agents` supports declarative TOML configuration for governance profiles and pipeline setup. Define policies in a file instead of code.

## TOML Governance Profiles

A governance profile defines domain-specific policy: VT floors, allowed/blocked tools, PII sensitivity, and audit requirements.

```toml
# governance.toml
[profile]
domain = "corporate"
default_vt = 2

[profile.vt_floor]
read_email = 0
send_email = 2
deploy = 3
delete_data = 4

[profile.blocked_tools]
tools = ["personal_calendar", "health_records"]
```

Load it:

```python
from governed_agents.profile_loader import load_profile

profile = load_profile("governance.toml")
print(profile.domain)       # "corporate"
print(profile.default_vt)   # 2
print(profile.get_vt_floor("send_email"))  # 2
print(profile.get_vt_floor("read_data"))   # 2 (uses default_vt)
```

## Loading from Dict

For Python 3.10 (no stdlib TOML) or programmatic configuration:

```python
profile = load_profile({
    "domain": "corporate",
    "default_vt": 2,
    "vt_floor": {"send_email": 2, "deploy": 3},
    "blocked_tools": ["personal_calendar"],
})
```

## Pipeline Configuration

Define the full pipeline declaratively:

```toml
# governance.toml
[pipeline]
handlers = ["pii", "rate_limiter", "vt", "audit"]

[pipeline.rate_limiter]
max_per_window = 10
window_seconds = 60

[pipeline.budget]
limit_usd = 5.0
```

Load and use it:

```python
from governed_agents.profile_loader import load_pipeline_config

pipeline = load_pipeline_config("governance.toml")
result = await pipeline.execute(ctx)
```

## Handler Aliases

The pipeline loader supports both full names and short aliases:

| Alias | Full Name | Handler Class |
|-------|-----------|---------------|
| `pii` | `pii_filter` | `PIIFilter` |
| `rate_limiter` | `rate_limit` | `RateLimiter` |
| `vt` | `vt_governance` | `VTGovernanceHandler` |
| `audit` | `audit_logger` | `AuditLogger` |
| `budget` | `budget_gatekeeper` | `BudgetGatekeeper` |
| `compliance` | `compliance_checker` | `ComplianceChecker` |
| `ux` | `ux_handler` | `UXHandler` |

Handlers named `audit` or `audit_logger` are automatically marked as `optional=True`.

## Handler-Specific Configuration

Each handler accepts configuration keys in a subsection named after the handler:

### Rate Limiter

```toml
[pipeline.rate_limiter]
max_per_window = 10
window_seconds = 60
```

### Budget Gatekeeper

```toml
[pipeline.budget]
limit_usd = 5.0
```

### PII Filter

```toml
[pipeline.pii]
redact = true
patterns = ["\\bINTERNAL-\\d{6}\\b"]
```

### Compliance Checker

```toml
[pipeline.compliance]
max_payload_kb = 256
strict_mode = true
```

## Domain Profiles

Use profiles with `DomainBarrierHandler` for cross-domain governance:

```python
from governed_agents.profile_loader import load_profile
from governed_agents.domain import DomainBarrierHandler

personal = load_profile({
    "domain": "personal",
    "default_vt": 1,
    "vt_floor": {"send_email": 1},
})

corporate = load_profile({
    "domain": "corporate",
    "default_vt": 2,
    "vt_floor": {"send_email": 2, "deploy": 3},
    "blocked_tools": ["personal_calendar"],
})

barrier = DomainBarrierHandler(profiles={
    "personal": personal,
    "corporate": corporate,
})
pipeline.add(barrier)
```

## Complete Example

```toml
# governance.toml

[profile]
domain = "corporate"
default_vt = 2
pii_sensitivity = 2
audit_required = true

[profile.vt_floor]
read_data = 0
query_database = 1
send_email = 2
deploy = 3
delete_data = 4

[profile.blocked_tools]
tools = ["personal_calendar", "health_records"]

[pipeline]
handlers = ["pii", "rate_limiter", "budget", "compliance", "vt", "audit"]

[pipeline.pii]
redact = true

[pipeline.rate_limiter]
max_per_window = 20
window_seconds = 60

[pipeline.budget]
limit_usd = 10.0

[pipeline.compliance]
max_payload_kb = 512
strict_mode = true
```

```python
from governed_agents.profile_loader import load_profile, load_pipeline_config

profile = load_profile("governance.toml")
pipeline = load_pipeline_config("governance.toml")

# Use profile with domain barrier
from governed_agents.domain import DomainBarrierHandler
barrier = DomainBarrierHandler(profiles={"corporate": profile})
# Insert barrier before VT governance in the pipeline
```

!!! note "Python version requirement"
    TOML loading requires Python 3.11+ (stdlib `tomllib`). On Python 3.10, use `load_profile(dict)` and `load_pipeline_config(dict)` instead.
