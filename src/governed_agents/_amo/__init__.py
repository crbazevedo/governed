"""Optional AMO (Autonomous Multi-agent Oversight) integration.

Requires the [amo] extra: pip install governed-agents[amo]
"""

try:
    from governed_agents._amo.dynamic_vt import DynamicVTHandler

    __all__ = ["DynamicVTHandler"]
except ImportError:
    __all__ = []
