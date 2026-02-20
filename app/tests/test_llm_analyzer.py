"""
Tests for LLM Analyzer service.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime

from app.llm_analyzer import LLMAnalyzer, DialogAnalysis
from app.models import Segment


@pytest.fixture
def sample_segments():
    """Sample segments for testing."""
    return [
        Segment(
            start=0.0,
            end=10.0,
            text="Здравствуйте, это Алексей из компании TechSolutions",
            speaker="SPEAKER_00"
        ),
        Segment(
            start=10.0,
            end=20.0,
            text="Здравствуйте, меня зовут Мария. Что у вас за предложение?",
            speaker="SPEAKER_01"
        ),
        Segment(
            start=20.0,
            end=30.0,
            text="Мы предлагаем современное решение для автоматизации бизнеса",
            speaker="SPEAKER_00"
        )
    ]


@pytest.fixture
def llm_analyzer():
    """LLM analyzer instance with mocked API."""
    with patch('app.llm_analyzer.LLMAnalyzer._get_api_key') as mock_key:
        mock_key.return_value = "test_key"
        analyzer = LLMAnalyzer()
        analyzer._call_llm_api = Mock()
        return analyzer


@pytest.mark.asyncio
async def test_analyze_dialog_success(llm_analyzer, sample_segments):
    """Test successful dialogue analysis."""
    # Mock LLM response
    mock_response = """
    {
        "scores": {
            "greeting": 8.0,
            "needs_discovery": 7.0,
            "presentation": 6.0,
            "objection_handling": 9.0,
            "closing": 5.0,
            "active_listening": 8.0,
            "empathy": 7.0,
            "overall": 7.3
        },
        "status": "in_progress",
        "key_moments": [
            {
                "type": "interest",
                "time": 10.0,
                "text": "Что у вас за предложение?"
            }
        ],
        "recommendations": [
            {
                "text": "Улучшить закрывающие вопросы",
                "time_range": [25, 30]
            }
        ],
        "speaking_time": {
            "sales": 20,
            "customer": 10
        }
    }
    """

    llm_analyzer._call_llm_api.return_value = mock_response

    # Perform analysis
    result = await llm_analyzer.analyze_dialog(sample_segments)

    # Verify result
    assert isinstance(result, DialogAnalysis)
    assert result.scores["greeting"] == 8.0
    assert result.status == "in_progress"
    assert len(result.key_moments) == 1
    assert len(result.recommendations) == 1
    assert result.speaking_time["sales"] == 20
    assert result.speaking_time["customer"] == 10


@pytest.mark.asyncio
async def test_analyze_dialog_cache(llm_analyzer, sample_segments):
    """Test that analysis results are cached."""
    # Mock LLM response
    mock_response = """
    {
        "scores": {"greeting": 8.0, "needs_discovery": 7.0, "presentation": 6.0,
                  "objection_handling": 9.0, "closing": 5.0, "active_listening": 8.0,
                  "empathy": 7.0, "overall": 7.3},
        "status": "in_progress",
        "key_moments": [],
        "recommendations": [],
        "speaking_time": {"sales": 20, "customer": 10}
    }
    """

    llm_analyzer._call_llm_api.return_value = mock_response

    # First analysis should call API
    await llm_analyzer.analyze_dialog(sample_segments)
    assert llm_analyzer._call_llm_api.call_count == 1

    # Second analysis should use cache
    await llm_analyzer.analyze_dialog(sample_segments)
    assert llm_analyzer._call_llm_api.call_count == 1  # No additional call


def test_get_analysis_summary(llm_analyzer, sample_segments):
    """Test analysis summary generation."""
    # Create mock analysis
    analysis = DialogAnalysis(
        scores={"greeting": 5.0, "needs_discovery": 7.0, "presentation": 6.0,
               "objection_handling": 4.0, "closing": 5.0, "active_listening": 8.0,
               "empathy": 6.0, "overall": 5.9},
        status="in_progress",
        key_moments=[],
        recommendations=[],
        speaking_time={"sales": 100, "customer": 150},
        confidence=0.85,
        reasoning="Test analysis"
    )

    summary = llm_analyzer.get_analysis_summary(analysis)

    # Verify summary structure
    assert "scores" in summary
    assert "status_display" in summary
    assert "status_display" in summary
    assert "key_moments_count" in summary
    assert "recommendations" in summary
    assert "speaking_time_percentages" in summary
    assert "improvement_areas" in summary

    # Verify status display
    assert summary["status_display"] == "🔄 В работе"

    # Verify improvement areas
    assert "Работа с возражениями" in summary["improvement_areas"]


def test_get_improvement_areas(llm_analyzer):
    """Test improvement areas identification."""
    low_scores = {
        "greeting": 4.0,
        "needs_discovery": 7.0,
        "presentation": 5.0,
        "objection_handling": 3.0,
        "closing": 4.0,
        "active_listening": 8.0,
        "empathy": 6.0
    }

    high_scores = {
        "greeting": 9.0,
        "needs_discovery": 8.0,
        "presentation": 9.0,
        "objection_handling": 8.0,
        "closing": 9.0,
        "active_listening": 9.0,
        "empathy": 9.0
    }

    # Low scores should identify improvement areas
    areas_low = llm_analyzer._get_improvement_areas(low_scores)
    assert "Приветствие и контакт" in areas_low
    assert "Презентация решения" in areas_low
    assert "Работа с возражениями" in areas_low
    assert "Закрытие сделки" in areas_low

    # High scores should indicate no improvement needed
    areas_high = llm_analyzer._get_improvement_areas(high_scores)
    assert areas_high == ["Все аспекты диалога в норме"]


@pytest.mark.asyncio
async def test_analyze_dialog_empty_segments(llm_analyzer):
    """Test analysis with empty segments."""
    with pytest.raises(ValueError, match="No segments provided"):
        await llm_analyzer.analyze_dialog([])


@pytest.mark.asyncio
async def test_analyze_dialog_api_failure(llm_analyzer, sample_segments):
    """Test handling of API failure."""
    # Mock API failure
    llm_analyzer._call_llm_api.side_effect = Exception("API Error")

    with pytest.raises(RuntimeError, match="Analysis failed"):
        await llm_analyzer.analyze_dialog(sample_segments)


@pytest.mark.asyncio
async def test_speaking_time_fallback(llm_analyzer, sample_segments):
    """Test manual speaking time calculation when LLM fails."""
    # Mock LLM failure
    llm_analyzer._call_llm_api.side_effect = Exception("API Error")

    # Override _analyze_speaking_time to test fallback
    manual_result = await llm_analyzer._analyze_speaking_time(sample_segments)

    # Verify manual calculation
    assert manual_result["sales"] > 0
    assert manual_result["customer"] > 0
    assert manual_result["sales"] + manual_result["customer"] == 30.0  # Total duration