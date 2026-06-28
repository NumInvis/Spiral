"""RecommendationAgent: an LLM-driven agent that orchestrates data tools.

The agent uses the validated recommendation engine as one of its tools and
exposes a transparent trace for every decision.  No LLM key => hard error.
"""

from typing import Optional
from sqlalchemy.orm import Session

from agent.state import AgentState
from agent.tools import (
    parse_profile_tool,
    retrieve_candidates_tool,
    risk_check_tool,
    generate_rationale_tool,
)


class RecommendationAgent:
    """Agent that turns free-text requirements into an explained volunteer table."""

    def __init__(self, text: str, rank: Optional[int] = None):
        self.state = AgentState(original_text=text, rank=rank)

    def run(self, db: Session) -> AgentState:
        """Execute the full pipeline and return the final state."""
        parse_profile_tool(self.state, db)
        retrieve_candidates_tool(self.state, db)
        risk_check_tool(self.state, db)
        generate_rationale_tool(self.state, db)
        return self.state
