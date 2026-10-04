"""Optional, opt-in language-model assistance.

Never on the path between a measurement and a decision: a model can propose a
grammar or a constraint, and the ordinary validator decides whether it is
usable. Nothing here runs unless a user asks for it.
"""

from .assist import Proposal, constraints_for, infer_grammar, read_examples, repair_grammar
from .client import LLMError, PROVIDERS, available, complete

__all__ = ["Proposal", "infer_grammar", "repair_grammar", "constraints_for",
           "read_examples", "LLMError", "PROVIDERS", "available", "complete"]
