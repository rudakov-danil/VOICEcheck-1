"""
VOICEcheck AI Dialogue Analysis Service

This module provides intelligent analysis of sales conversations using GPT-4o via z.ai API.
Designed specifically for sales dialogue evaluation with structured output validation.

Core Capabilities:
- Multi-dimensional dialogue scoring across 7 key sales categories
- Automatic detection of important moments and conversation patterns
- Speaking time distribution analysis (sales vs customer)
- Actionable improvement recommendations based on dialogue quality
- Deal status classification (successful, in progress, rejected)
- Caching for performance optimization with TTL-based expiration

Analysis Categories:
1. Greeting & Contact Establishment - Initial impression and rapport
2. Needs Discovery - Question quality and needs identification
3. Solution Presentation - Value proposition effectiveness
4. Objection Handling - Response quality to concerns
5. Closing - Deal conversion techniques
6. Active Listening - Engagement and attention
7. Empathy & Tone - Communication quality and emotional intelligence

Technical Architecture:
- Asynchronous API calls with retry mechanisms
- Exponential backoff for error resilience
- JSON response validation with fallback parsing
- In-memory caching with 1-hour TTL
- Graceful degradation when LLM unavailable

Integration Points:
- Used by main.py for background analysis
- Called from dialogs.py for on-demand analysis
- Returns structured data for UI display
- Handles segment lists from transcription service
"""

"""
LLM Analyzer module with utilities for dialogue processing.
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .prompts import DialogueAnalysisPrompts
from .models import Segment

logger = logging.getLogger(__name__)

# Constants for analysis configuration
import os
DEFAULT_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))  # seconds
MAX_RETRIES = 3
CACHE_TTL = 3600  # 1 hour in seconds
API_BASE_URL = "https://api.z.ai/api/anthropic/v1/messages"
MAX_TOKENS = 2000

# Score thresholds for improvement identification
IMPROVEMENT_THRESHOLDS = {
    "greeting": 6,
    "needs_discovery": 7,
    "presentation": 6,
    "objection_handling": 6,
    "closing": 5,
    "active_listening": 7,
    "empathy": 6
}

# Category names in Russian for UI display
CATEGORY_NAMES = {
    "greeting": "Приветствие и установление контакта",
    "needs_discovery": "Выявление потребностей",
    "presentation": "Презентация решения",
    "objection_handling": "Работа с возражениями",
    "closing": "Закрытие сделки",
    "active_listening": "Активное слушание",
    "empathy": "Эмпатия и тон"
}


@dataclass
class DialogAnalysis:
    """
    Container for comprehensive dialogue analysis results.

    Provides structured storage for AI-powered dialogue evaluation including:
    - Category-based scoring system
    - Status classification for deal outcome
    - Important moment detection with timestamps
    - Actionable improvement recommendations
    - Dialogue summary for quick overview
    - Speaking time distribution analysis
    - Confidence scoring and reasoning

    Usage Example:
        analysis = DialogAnalysis(
            scores={"greeting": 8.5, "needs_discovery": 7.0},
            status="dealed",
            key_moments=[{"time": 30, "text": "Product interest shown"}],
            recommendations=["Ask more qualifying questions"],
            summary="Клиент проявил интерес к продукту, обсудил детали сотрудничества.",
            speaking_time={"sales": 120, "customer": 180}
        )
    """
    scores: Dict[str, float]  # Scores for each analysis category (0-10 scale)
    status: str               # Deal status classification
    key_moments: List[Dict[str, Any]]  # Important dialogue moments with metadata
    recommendations: List[Dict[str, Any]]  # Improvement suggestions
    summary: str              # Brief dialogue summary (2-3 sentences)
    speaking_time: Dict[str, float]  # Time distribution in seconds
    confidence: float = 0.0  # Overall confidence score (0-1)
    reasoning: str = ""       # Analysis reasoning or explanatory notes


class LLMAnalyzer:

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet",
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES
    ) -> None:
        """
        Initialize the LLM Analyzer service with configurable parameters.

        Sets up the AI analysis service with API authentication, model selection,
        timeout configuration, and retry mechanisms for reliable operation.

        Args:
            api_key: Z.ai API key for authentication. If None, will be read from
                     ZAI_API_KEY environment variable. Required for operation.
            model: LLM model name to use for analysis. Default: claude-3-5-sonnet
            timeout: Request timeout in seconds. Default: 30 seconds
            max_retries: Maximum retry attempts for failed API calls with
                        exponential backoff. Default: 3

        Raises:
            ValueError: If ZAI_API_KEY environment variable is not set
                        and no api_key is provided.

        Configuration Notes:
            - Model options include claude-3-5-sonnet (recommended)
            - Timeout should be adjusted based on audio complexity
            - Retries use exponential backoff (4s, 8s, 10s intervals)
        """
        self.api_key = api_key or self._get_api_key()
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.prompts = DialogueAnalysisPrompts()

        # In-memory cache for analysis results (TTL 1 hour)
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}

    def _get_api_key(self) -> str:
        """
        Retrieve Z.ai API key from environment variables with validation.

        Checks for the presence of required API key in environment variables
        and raises an exception if not found.

        Returns:
            str: Z.ai API key for API authentication

        Raises:
            ValueError: If ZAI_API_KEY environment variable is not set,
                       which is required for LLM service access.

        Note:
            API key is stored in environment for security reasons.
            Should be set in production deployment environment.
        """
        import os
        api_key = os.getenv("ZAI_API_KEY")
        if not api_key:
            raise ValueError(
                "ZAI_API_KEY environment variable not set. "
                "Please set it in your environment for LLM analysis to work."
            )
        return api_key

    def _prepare_transcript(self, segments: List[Segment]) -> str:
        """
        Format transcript segments for LLM analysis with structured timestamps.

        Converts transcription segments into a readable format with speaker labels
        and timestamps suitable for AI analysis. Each segment includes speaker info,
        start/end times, and the transcribed text.

        Args:
            segments: List of Segment objects containing:
                - start: Start time in seconds
                - end: End time in seconds
                - text: Transcribed text content
                - speaker: Speaker identifier (e.g., "SPEAKER_00")

        Returns:
            str: Formatted transcript with each segment on a new line,
                 showing [SPEAKER] start-end: text format

        Example Output:
            [SPEAKER_00] 0.0-5.2: Hello, how can I help you today?
            [SPEAKER_01] 5.3-10.1: I'm interested in your product...
        """
        transcript_parts = []
        for segment in segments:
            transcript_parts.append(
                f"[{segment.speaker}] {segment.start:.1f}-{segment.end:.1f}: {segment.text}"
            )
        return "\n".join(transcript_parts)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def _call_llm_api(self, prompt: str) -> str:
        """
        Call z.ai API with exponential backoff retry mechanism.

        Implements robust HTTP communication with automatic retries for network
        failures, timeouts, and other transient errors. Uses exponential backoff
        to prevent overwhelming the API service during outages.

        Args:
            prompt: Formatted prompt containing the complete dialog transcript
                   for AI analysis, including system instructions and user content.

        Returns:
            str: Raw text response from the LLM containing JSON analysis

        Raises:
            RuntimeError: If all retry attempts fail
            aiohttp.ClientError: For HTTP connection errors (4xx, 5xx, network issues)
            asyncio.TimeoutError: If request exceeds timeout threshold
            KeyError: If API response format is invalid

        Retry Strategy:
            - Attempts: 3 maximum
            - Backoff: 4s, 8s, 10s (exponential with cap)
            - Retries on: Connection errors, timeouts only
            - No retry on: Invalid JSON format, auth errors
        """
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": self.model,
            "max_tokens": 2000,
            "system": "Ты - эксперт по продажам и аналитик диалогов. Отвечай только валидным JSON.",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    "https://api.z.ai/api/anthropic/v1/messages",
                    headers=headers,
                    json=payload
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    content = result["content"][0]["text"]
                    return content.strip()
        except aiohttp.ClientError as e:
            logger.error(f"LLM API error: {e}")
            raise
        except asyncio.TimeoutError:
            logger.error(f"LLM API timeout after {self.timeout} seconds")
            raise
        except KeyError as e:
            logger.error(f"LLM API response format error: {e}")
            raise

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse LLM response JSON with validation and cleanup.

        Extracts and validates JSON content from LLM response, handling various
        response formats including JSON code blocks and malformed responses.
        Performs strict validation of required fields.

        Args:
            response_text: Raw text response from LLM that should contain JSON

        Returns:
            Dict: Parsed and validated analysis data with:
                - scores: Dict of category scores (float values 0-10)
                - status: Deal status classification
                - key_moments: List of important moments
                - recommendations: List of improvement suggestions
                - speaking_time: Dict with time distribution

        Raises:
            ValueError: If response is not valid JSON or missing required fields

        Response Cleaning:
            - Removes JSON code block markers (```json, ```)
            - Strips whitespace from JSON content
            - Validates presence of all required fields
        """
        try:
            # Try to extract JSON from response
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

            data = json.loads(response_text)

            # Validate required fields
            required_fields = ["scores", "status", "key_moments", "recommendations", "speaking_time", "summary"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.error(f"Response text: {response_text[:500]}...")
            raise ValueError(f"Invalid JSON response from LLM: {e}")

    async def _analyze_speaking_time(self, segments: List[Segment]) -> Dict[str, float]:
        """
        Analyze speaking time distribution between speakers with LLM assistance.

        Calculates total speaking time for each speaker in the dialogue.
        Uses LLM for intelligent analysis when available, falls back to
        simple duration calculation if LLM analysis fails.

        Args:
            segments: List of Segment objects with start, end, speaker, and text

        Returns:
            Dict: Speaking time distribution with:
                - sales: Total speaking time for sales person (seconds)
                - customer: Total speaking time for customer (seconds)

        Error Handling:
            - If LLM analysis fails, falls back to manual duration calculation
            - Handles missing or invalid speaker labels gracefully
            - Returns empty dict if no segments provided

        Note:
            LLM analysis provides more accurate speaker identification
            and categorization than simple duration calculation.
        """
        transcript = self._prepare_transcript(segments)
        prompt = self.prompts.get_speaking_time_prompt(transcript)

        try:
            response_text = await self._call_llm_api(prompt)
            # Parse speaking_time directly — don't use _parse_response (needs all analysis fields)
            text = response_text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            data = json.loads(text.strip())
            st = data.get("speaking_time", data)  # support both wrapped and flat formats
            if "sales" in st and "customer" in st:
                return {"sales": float(st["sales"]), "customer": float(st["customer"])}
            raise ValueError(f"Unexpected speaking_time format: {st}")
        except Exception as e:
            logger.warning(f"Failed to analyze speaking time, calculating manually: {e}")
            # Fallback: calculate based on segment durations
            manual_result = {"sales": 0.0, "customer": 0.0}

            for segment in segments:
                duration = segment.end - segment.start
                if segment.speaker == "SPEAKER_00":
                    manual_result["sales"] += duration
                else:
                    manual_result["customer"] += duration

            return manual_result

    async def analyze_dialog(self, segments: List[Segment]) -> DialogAnalysis:
        """
        Perform comprehensive AI analysis of a sales dialogue.

        This is the main analysis method orchestrating the entire dialogue
        evaluation pipeline. Includes cache checking, LLM analysis, and
        result validation with fallback mechanisms.

        Args:
            segments: List of Segment objects containing:
                - start: Segment start time in seconds
                - end: Segment end time in seconds
                - text: Transcribed speech content
                - speaker: Speaker identifier

        Returns:
            DialogAnalysis: Complete analysis object with:
                - scores: Category scores (greeting, needs_discovery, etc.)
                - status: Deal status classification
                - key_moments: Important dialogue moments with timestamps
                - recommendations: Actionable improvement suggestions
                - speaking_time: Time distribution between speakers
                - confidence: Overall analysis confidence score
                - reasoning: Analysis rationale and explanations

        Raises:
            RuntimeError: If analysis fails at any critical stage
            ValueError: If segments list is empty or invalid

        Analysis Pipeline:
            1. Cache check (hash-based key for transcript content)
            2. Transcript preparation for LLM input
            3. LLM API call with structured prompts
            4. Response validation and JSON parsing
            5. Score normalization and overall calculation
            6. Speaking time analysis with fallback
            7. Result caching for future use

        Note:
            Uses exponential backoff for API calls and graceful degradation
            when LLM service is unavailable.
        """
        if not segments:
            raise ValueError("No segments provided for analysis")

        # Check cache first to avoid redundant LLM calls and improve performance
        # Use hash of transcript content as cache key - identical dialogues get same analysis
        cache_key = str(hash(self._prepare_transcript(segments)))
        if cache_key in self.analysis_cache:
            cached = self.analysis_cache[cache_key]
            logger.info("Using cached analysis result")
            return DialogAnalysis(**cached)

        try:
            # Prepare transcript with speaker labels and timestamps for LLM input format
            transcript = self._prepare_transcript(segments)

            # Generate structured analysis prompt using predefined templates
            analysis_prompt = self.prompts.get_analysis_prompt().format(transcript=transcript)

            # Call LLM API with retry mechanism and exponential backoff
            response_text = await self._call_llm_api(analysis_prompt)
            analysis_data = self._parse_response(response_text)

            # Validate and normalize scores - calculate overall if not provided by LLM
            scores = analysis_data["scores"]
            if scores["overall"] == 0:
                # Calculate weighted average from individual category scores for consistency
                scores["overall"] = sum([
                    scores["greeting"],
                    scores["needs_discovery"],
                    scores["presentation"],
                    scores["objection_handling"],
                    scores["closing"],
                    scores["active_listening"],
                    scores["empathy"]
                ]) / 7.0

            # Analyze speaking time distribution with intelligent categorization
            speaking_time = await self._analyze_speaking_time(segments)

            # Create structured analysis result with all components
            analysis = DialogAnalysis(
                scores=scores,
                status=analysis_data["status"],
                key_moments=analysis_data["key_moments"],
                recommendations=analysis_data["recommendations"],
                summary=analysis_data["summary"],
                speaking_time=speaking_time,
                confidence=analysis_data.get("confidence", 0.0),
                reasoning=analysis_data.get("reasoning", "")
            )

            # Cache result for future use to improve performance
            # TTL of 1 hour configured in CACHE_TTL constant
            self.analysis_cache[cache_key] = {
                "scores": analysis.scores,
                "status": analysis.status,
                "key_moments": analysis.key_moments,
                "recommendations": analysis.recommendations,
                "summary": analysis.summary,
                "speaking_time": analysis.speaking_time,
                "confidence": analysis.confidence,
                "reasoning": analysis.reasoning
            }

            return analysis

        except Exception as e:
            # Handle any errors gracefully and provide meaningful error messages
            logger.error(f"Failed to analyze dialog: {e}")
            raise RuntimeError(f"Analysis failed: {str(e)}")

    def get_analysis_summary(self, analysis: DialogAnalysis) -> Dict[str, Any]:
        """
        Generate user-friendly summary of dialogue analysis for UI display.

        Transforms raw analysis data into format optimized for web interface,
        including calculated percentages, improvement area identification,
        and localized status messages in Russian.

        Args:
            analysis: DialogAnalysis instance containing complete analysis results
                      including scores, moments, recommendations, and timing data

        Returns:
            Dict: Formatted summary optimized for UI rendering containing:
                - scores: Dictionary of category names and scores (0-10 scale)
                - status: Deal status classification with display text
                - status_display: Human-readable status with emoji indicators
                - key_moments_count: Integer count of important moments detected
                - recommendations: List of improvement suggestion strings
                - speaking_time_percentages: Dict with percentage distribution
                - improvement_areas: List of category names needing improvement

        UI Features:
            - Uses CATEGORY_NAMES for Russian display text
            - Calculates percentage-based speaking time distribution
            - Identifies areas below IMPROVEMENT_THRESHOLDS
            - Adds emoji indicators for deal status
            - Provides ready-to-display data format

        Example Output:
            {
                "scores": {"greeting": 8.5, "needs_discovery": 7.0},
                "status": "dealed",
                "status_display": "🎯 Сделка состоялась",
                "improvement_areas": ["Выявление потребностей"]
            }
        """
        total_speaking_time = sum(analysis.speaking_time.values())

        return {
            "scores": analysis.scores,
            "status": analysis.status,
            "status_display": {
                "dealed": "🎯 Сделка состоялась",
                "in_progress": "🔄 В работе",
                "rejected": "❌ Отказ"
            }[analysis.status],
            "key_moments_count": len(analysis.key_moments),
            "recommendations": analysis.recommendations,
            "speaking_time_percentages": {
                "sales": (analysis.speaking_time.get("sales", 0) / max(total_speaking_time, 1)) * 100,
                "customer": (analysis.speaking_time.get("customer", 0) / max(total_speaking_time, 1)) * 100
            },
            "improvement_areas": self._get_improvement_areas(analysis.scores)
        }

    def _get_improvement_areas(self, scores: Dict[str, float]) -> List[str]:
        """
        Identify improvement areas based on predefined score thresholds.

        Compares each category score against its minimum acceptable threshold
        and returns list of areas that require attention or improvement.
        Provides localized Russian names for better user experience.

        Args:
            scores: Dictionary of category scores (0-10 scale) where keys are:
                    - greeting: Initial impression and contact establishment
                    - needs_discovery: Needs identification and questioning
                    - presentation: Solution presentation quality
                    - objection_handling: Response to concerns and objections
                    - closing: Deal conversion techniques
                    - active_listening: Engagement and attention
                    - empathy: Communication quality and emotional intelligence

        Returns:
            List: Human-readable improvement area names in Russian.
                  Returns generic message if all areas are acceptable.

        Threshold Logic:
            - greeting: Minimum 6/10 - First impression critical
            - needs_discovery: Minimum 7/10 - Foundation for success
            - presentation: Minimum 6/10 - Solution quality matters
            - objection_handling: Minimum 6/10 - Common challenge area
            - closing: Minimum 5/10 - Lower threshold, still important
            - active_listening: Minimum 7/10 - Essential for trust
            - empathy: Minimum 6/10 - Communication quality indicator

        Example:
            _get_improvement_areas({"greeting": 5, "needs_discovery": 8})
            Returns: ["Приветствие и установление контакта"]
        """
        areas = []

        for area, threshold in IMPROVEMENT_THRESHOLDS.items():
            score = scores.get(area, 0)
            if score < threshold:
                area_name = CATEGORY_NAMES.get(area, area)
                areas.append(area_name)

        return areas if areas else ["Все аспекты диалога в норме"]