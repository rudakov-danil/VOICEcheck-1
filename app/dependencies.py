"""Shared dependency injection utilities."""

import logging
from typing import Optional

from .llm_analyzer import LLMAnalyzer

logger = logging.getLogger(__name__)

_llm_analyzer_instance: Optional[LLMAnalyzer] = None


def get_llm_analyzer() -> Optional[LLMAnalyzer]:
    """Get or create the global LLM analyzer instance (lazy init)."""
    global _llm_analyzer_instance
    if _llm_analyzer_instance is None:
        try:
            _llm_analyzer_instance = LLMAnalyzer()
            logger.info("LLM Analyzer initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM Analyzer: {e}")
    return _llm_analyzer_instance
