"""
Pydantic schemas for database models and API requests/responses.

This module provides Pydantic models for data validation, serialization,
and API contract definition. The schemas follow REST API conventions
 and are organized by domain (Dialog, Transcription, Analysis).

Key features:
- Input validation for API endpoints
- Response serialization with proper type hints
- Field descriptions for API documentation
- Inheritance patterns for code reuse
- Support for pagination and filtering

Organization:
- Dialog schemas: Audio file management and metadata
- Transcription schemas: Speech-to-text results
- Analysis schemas: Dialogue quality assessment
- Response schemas: API response structures
- Utility schemas: Pagination and filtering
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Dialog schemas for audio file management
# ============================================================================
class DialogBase(BaseModel):
    """
    Base schema for dialog data without ID and timestamps.

    Used for creating new dialog records and as base for other schemas.
    """
    filename: str = Field(..., min_length=1, max_length=255,
                         description="Original audio filename")
    duration: float = Field(..., gt=0,
                           description="Audio duration in seconds")
    status: str = Field(default="pending",
                       description="Dialog processing status: pending, processing, completed, failed")
    file_path: str = Field(..., min_length=1, max_length=512,
                          description="Path to audio file in filesystem")
    language: Optional[str] = Field(None, max_length=10,
                                    description="Detected language code (e.g., 'ru', 'en')")
    seller_name: Optional[str] = Field(None, max_length=255,
                                       description="Salesperson name")


class DialogCreate(DialogBase):
    """
    Schema for creating a new dialog.

    Inherits all fields from DialogBase. Used in POST requests
    for creating new audio file records.
    """
    pass


class DialogUpdate(BaseModel):
    """
    Schema for updating existing dialog records.

    Only status and language can be updated. All fields are optional
    to allow partial updates.
    """
    status: Optional[str] = Field(None, pattern="^(pending|processing|completed|failed)$",
                                 description="Dialog processing status")
    language: Optional[str] = Field(None, max_length=10,
                                   description="Updated detected language code")


class Dialog(DialogBase):
    """
    Complete dialog schema with system-generated fields.

    Used for API responses when retrieving dialog data.
    Includes auto-generated ID and timestamps.
    """
    id: UUID = Field(..., description="Unique dialog identifier")
    created_at: datetime = Field(..., description="Dialog creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


# ============================================================================
# Transcription schemas for speech-to-text results
# ============================================================================
class TranscriptionBase(BaseModel):
    """
    Base schema for transcription data.

    Contains the complete transcribed content with metadata and segments.
    Used as base for other transcription schemas.
    """
    text: str = Field(..., min_length=1, description="Complete transcribed text")
    language: str = Field(..., max_length=10, description="Language code of transcription")
    language_probability: float = Field(..., ge=0, le=1,
                                      description="Confidence score for language detection")
    segments: List[Dict[str, Any]] = Field(..., min_items=1,
                                           description="List of transcription segments with timing and speaker info")


class TranscriptionCreate(TranscriptionBase):
    """
    Schema for creating new transcription records.

    Extends TranscriptionBase with dialog_id to associate
    transcription with its parent dialog.
    """
    dialog_id: UUID = Field(..., description="ID of the associated dialog")


class Transcription(TranscriptionBase):
    """
    Complete transcription schema with system fields.

    Used for API responses when retrieving transcription data.
    Includes auto-generated ID, dialog reference, and creation timestamp.
    """
    id: UUID = Field(..., description="Unique transcription identifier")
    dialog_id: UUID = Field(..., description="ID of the associated dialog")
    created_at: datetime = Field(..., description="Transcription creation timestamp")

    class Config:
        from_attributes = True


# ============================================================================
# Segment schemas for diarization and timing information
# ============================================================================
class SegmentWithSpeaker(BaseModel):
    """
    Schema for transcription segment with speaker diarization.

    Represents a time-bound segment of speech with speaker identification.
    Used for detailed transcription results with speaker separation.
    """
    start: float = Field(..., ge=0, description="Segment start time in seconds")
    end: float = Field(..., gt=0, description="Segment end time in seconds")
    text: str = Field(..., min_length=1, description="Transcribed text for this segment")
    speaker: str = Field(default="SPEAKER_00",
                         description="Speaker identifier (e.g., 'продавец', 'клиент')")


class TranscriptionResponseWithSpeaker(BaseModel):
    """
    Complete transcription response with speaker diarization.

    Used for API responses that include detailed segmentation
    and speaker identification results.
    """
    text: str = Field(..., description="Complete transcribed text")
    language: str = Field(..., description="Detected language code")
    language_probability: float = Field(..., ge=0, le=1,
                                        description="Confidence score for language detection")
    duration: float = Field(..., gt=0, description="Total audio duration in seconds")
    segments: List[SegmentWithSpeaker] = Field(...,
                                               description="Time-bound segments with speaker labels")


# ============================================================================
# Dialog analysis schemas for quality assessment and recommendations
# ============================================================================
class DialogAnalysisBase(BaseModel):
    """
    Base schema for dialog analysis results.

    Contains comprehensive analysis data including quality scores,
    key moments, recommendations, dialogue summary, and speaking statistics.
    """
    scores: Dict[str, float] = Field(...,
                                     description="Quality scores for dialogue categories (0-10 scale)")
    key_moments: List[Dict[str, Any]] = Field(...,
                                             description="Important moments with timestamps and descriptions")
    recommendations: List[str] = Field(...,
                                      description="Actionable recommendations for improvement")
    summary: str = Field(..., min_length=1, description="Brief dialogue summary (2-3 sentences)")
    speaking_time: Dict[str, float] = Field(...,
                                          description="Speaking time statistics by speaker category")


class DialogAnalysisCreate(DialogAnalysisBase):
    """
    Schema for creating dialog analysis records.

    Extends DialogAnalysisBase with dialog_id to associate analysis
    with its parent dialog.
    """
    dialog_id: UUID = Field(..., description="ID of the associated dialog")


class DialogAnalysis(DialogAnalysisBase):
    """
    Complete dialog analysis schema with system fields.

    Used for API responses when retrieving analysis data.
    Includes auto-generated ID, dialog reference, and creation timestamp.
    """
    id: UUID = Field(..., description="Unique analysis identifier")
    dialog_id: UUID = Field(..., description="ID of the associated dialog")
    created_at: datetime = Field(..., description="Analysis creation timestamp")

    class Config:
        from_attributes = True


# ============================================================================
# Utility schemas for analysis and API responses
# ============================================================================
class ScoreCategory(BaseModel):
    """
    Schema for individual analysis score categories.

    Represents a single quality dimension with name, score, and description.
    Used for structured analysis presentation.
    """
    name: str = Field(..., min_length=1, description="Category name (e.g., 'greeting', 'product')")
    score: float = Field(..., ge=0, le=10, description="Score value on 0-10 scale")
    description: str = Field(..., min_length=1, description="Human-readable category description")


# Analysis response schema
class AnalysisResponse(BaseModel):
    """
    Complete analysis response with all dialog data.

    Aggregates dialog, transcription, and analysis results into a single
    comprehensive response for the API client.
    """
    dialog: Dialog = Field(..., description="Dialog metadata and file information")
    transcription: Optional[Transcription] = Field(None,
                                                  description="Transcription result if available")
    analysis: Optional[DialogAnalysis] = Field(None,
                                             description="Analysis result if available")
    scores: List[ScoreCategory] = Field(...,
                                      description="Quality score categories with descriptions")
    key_moments: List[Dict[str, Any]] = Field(...,
                                             description="Important dialogue moments")
    recommendations: List[str] = Field(...,
                                      description="Actionable recommendations for improvement")
    summary: Optional[str] = Field(None, description="Brief dialogue summary if available")
    speaking_time: Dict[str, float] = Field(...,
                                          description="Speaking time distribution")


# ============================================================================
# API utility schemas for filtering and pagination
# ============================================================================
class DialogFilter(BaseModel):
    """
    Schema for filtering dialog queries.

    Supports multiple filter criteria for flexible dialog retrieval.
    All fields are optional to allow partial filtering.
    """
    status: Optional[str] = Field(None, pattern="^(pending|processing|completed|failed)$",
                                 description="Filter by processing status")
    language: Optional[str] = Field(None, max_length=10,
                                   description="Filter by detected language")
    start_date: Optional[datetime] = Field(None,
                                          description="Filter by creation date (inclusive)")
    end_date: Optional[datetime] = Field(None,
                                        description="Filter by creation date (exclusive)")
    search: Optional[str] = Field(None, max_length=255,
                                 description="Search in filename (case-insensitive)")


# ============================================================================
# Pagination schemas for API responses
# ============================================================================
class PaginationParams(BaseModel):
    """
    Schema for pagination parameters.

    Validates pagination input with sensible defaults and constraints
    to prevent excessive data retrieval.
    """
    page: int = Field(default=1, ge=1, le=1000,
                     description="Page number (1-based, max 1000)")
    per_page: int = Field(default=10, ge=1, le=100,
                          description="Items per page (1-100)")


class PaginatedResponse(BaseModel):
    """
    Schema for paginated API responses.

    Standardizes pagination response format across all endpoints.
    Provides metadata for client-side pagination UI and navigation.
    """
    items: List[Any] = Field(..., description="List of items for current page")
    total: int = Field(..., ge=0, description="Total number of items across all pages")
    page: int = Field(..., ge=1, description="Current page number")
    per_page: int = Field(..., ge=1, description="Number of items per page")
    total_pages: int = Field(..., ge=0, description="Total number of pages")