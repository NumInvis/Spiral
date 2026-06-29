"""Agent state and trace models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentStep:
    step: int
    name: str
    status: str = "running"  # running / done / error
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class AgentState:
    original_text: str
    rank: Optional[int] = None
    profile: Optional[Any] = None
    candidates_count: int = 0
    groups_count: int = 0
    selected: List[Dict[str, Any]] = field(default_factory=list)
    special_selected: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    trace: List[AgentStep] = field(default_factory=list)
    final_html: Optional[str] = None
