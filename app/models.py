"""
Pydantic models for API request/response validation.

This module defines data models for the VOICEcheck application including:
- Upload and transcription responses
- Analysis scores and metrics
- Task status tracking
- Error handling models
- Segment and dialogue models

All models include proper validation, serialization, and documentation.
"""

import logging
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)
from typing import Optional, List, Dict, Any
from datetime import datetime


class UploadResponse(BaseModel):
    """Response model for successful file upload operation."""
    file_id: str = Field(..., description="Уникальный идентификатор файла")
    filename: str = Field(..., description="Исходное имя файла")
    size: int = Field(..., ge=0, description="Размер файла в байтах")
    content_type: str = Field(..., description="MIME тип файла")


class AnalysisScores(BaseModel):
    """Comprehensive scoring for dialogue analysis categories."""
    greeting: float = Field(..., ge=0, le=10, description="Приветствие и установление контакта")
    needs_discovery: float = Field(..., ge=0, le=10, description="Выявление потребностей")
    presentation: float = Field(..., ge=0, le=10, description="Презентация решения")
    objection_handling: float = Field(..., ge=0, le=10, description="Работа с возражениями")
    closing: float = Field(..., ge=0, le=10, description="Закрытие сделки / Call-to-action")
    active_listening: float = Field(..., ge=0, le=10, description="Активное слушание")
    empathy: float = Field(..., ge=0, le=10, description="Эмпатия и тон общения")
    overall: float = Field(..., ge=0, le=10, description="Общий балл встречи")

    @validator('overall')
    def validate_overall_score(cls, v, values):
        """Ensure overall score is consistent with category scores."""
        if 'greeting' in values and 'needs_discovery' in values and 'presentation' in values \
           and 'objection_handling' in values and 'closing' in values \
           and 'active_listening' in values and 'empathy' in values:
            calculated = (
                values['greeting'] + values['needs_discovery'] + values['presentation'] +
                values['objection_handling'] + values['closing'] +
                values['active_listening'] + values['empathy']
            ) / 7.0
            if abs(v - calculated) > 0.1:  # Allow small rounding differences
                logger.warning(f"Overall score {v} differs from calculated {calculated}")
        return v


class KeyMoment(BaseModel):
    """Key moment in dialogue."""
    type: str = Field(..., description="Тип момента")
    time: float = Field(..., description="Время в секундах")
    text: str = Field(..., description="Текст момента")


class Recommendation(BaseModel):
    """Recommendation for improvement."""
    text: str = Field(..., description="Текст рекомендации")
    time_range: List[float] = Field(..., description="Временной интервал [start, end]")


class SpeakingTime(BaseModel):
    """Speaking time statistics."""
    sales: float = Field(..., description="Время речи продавца (сек)")
    customer: float = Field(..., description="Время речи клиента (сек)")


class DialogAnalysisResponse(BaseModel):
    """Complete dialogue analysis response."""
    scores: AnalysisScores = Field(..., description="Оценки по категориям")
    status: str = Field(..., description="Статус сделки")
    key_moments: List[KeyMoment] = Field(..., description="Ключевые моменты")
    recommendations: List[Recommendation] = Field(..., description="Рекомендации")
    summary: Optional[str] = Field(None, description="Краткое резюме диалога")
    speaking_time: SpeakingTime = Field(..., description="Статистика времени речи")
    confidence: float = Field(..., ge=0, le=1, description="Уверенность в анализе")
    reasoning: str = Field(..., description="Обоснование анализа")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Время создания")


class DialogStatusUpdate(BaseModel):
    """Model for updating dialog status."""
    status: str = Field(..., description="Новый статус: dealed|in_progress|rejected")


class DialogDetail(BaseModel):
    """Complete dialog details with analysis."""
    id: str = Field(..., description="Dialog ID")
    filename: str = Field(..., description="Original filename")
    duration: float = Field(..., description="Audio duration (seconds)")
    status: str = Field(..., description="Dialog status")
    language: Optional[str] = Field(None, description="Detected language")
    seller_name: Optional[str] = Field(None, description="Salesperson name")
    created_at: datetime = Field(..., description="Creation time")
    transcription: Optional[str] = Field(None, description="Transcription text")
    segments: Optional[List[dict]] = Field(None, description="Segments with speaker labels")
    analysis: Optional[DialogAnalysisResponse] = Field(None, description="Analysis results")


class TranscribeRequest(BaseModel):
    """Request model for transcription."""
    language: Optional[str] = Field(
        default="auto",
        description="Language code or 'auto' for detection"
    )
    task: str = Field(
        default="transcribe",
        description="Task type: 'transcribe' or 'translate'"
    )


class Segment(BaseModel):
    """Transcription segment with timestamps."""
    start: float = Field(..., description="Segment start time in seconds")
    end: float = Field(..., description="Segment end time in seconds")
    text: str = Field(..., description="Segment text")
    speaker: str = Field(default="SPEAKER_00", description="Speaker label")


class TranscribeResponse(BaseModel):
    """Response model for transcription result."""
    text: str = Field(..., description="Transcribed text")
    language: str = Field(..., description="Detected language code")
    language_probability: float = Field(
        ...,
        description="Confidence of language detection"
    )
    duration: float = Field(..., description="Audio duration in seconds")
    segments: List[Segment] = Field(default_factory=list, description="Timestamp segments")


class TaskStatus(BaseModel):
    """Status of a transcription task."""
    task_id: str = Field(..., description="Task identifier")
    status: str = Field(
        ...,
        description="Task status: pending, processing, completed, failed"
    )
    progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Progress percentage (0-100)"
    )
    message: Optional[str] = Field(default=None, description="Status message")
    result: Optional[TranscribeResponse] = Field(
        default=None,
        description="Transcription result (if completed)"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error info")
