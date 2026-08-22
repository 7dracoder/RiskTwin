"""RiskTwin specialist agent roles.

Multi-agent means specialised roles with separate structured outputs over shared
durable state — not five large models resident at once (spec section 6.1).
"""

from agents.base import AgentContext, write_evidence

__all__ = ["AgentContext", "write_evidence"]
