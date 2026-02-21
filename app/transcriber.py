"""
Deepgram-based transcription service.

This service provides audio transcription via the Deepgram REST API with:
- Speaker diarization (built-in, no pyannote needed)
- Smart formatting and punctuation
- In-memory LRU caching for repeated transcriptions
- Same interface as the previous Whisper-based service (drop-in replacement)

Environment variables:
    DEEPGRAM_API_KEY  – API key (required)
    DEEPGRAM_MODEL    – Model name (default: whisper)
    DEEPGRAM_LANGUAGE – Default language (default: ru)
    DEEPGRAM_TIMEOUT  – HTTP timeout in seconds (default: 300)
"""

import os
import re
import json
import logging
import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "d5ce6dd70dcd52f6073c22b2525b6d3a5f5e7440")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "whisper")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "ru")
DEEPGRAM_TIMEOUT = int(os.getenv("DEEPGRAM_TIMEOUT", "300"))

# Z.ai (Claude) for diarization
ZAI_API_URL = "https://api.z.ai/api/anthropic/v1/messages"
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
ZAI_MODEL = os.getenv("ZAI_MODEL", "claude-3-5-sonnet")
ZAI_DIARIZATION_TIMEOUT = int(os.getenv("ZAI_TIMEOUT", "180"))

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm"}
DEFAULT_CACHE_SIZE = int(os.getenv("TRANSCRIPTION_CACHE_SIZE", "100"))

# Content-type mapping for Deepgram
CONTENT_TYPES: Dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".mp4": "video/mp4",
    ".webm": "audio/webm",
}

# Speaker labels
SPEAKER_SALES = "SPEAKER_00"
SPEAKER_CUSTOMER = "SPEAKER_01"
SPEAKER_DEFAULT_LABEL = SPEAKER_SALES


class DeepgramTranscriptionService:
    """
    Audio transcription service using the Deepgram REST API.

    Implements the **same public interface** as the old WhisperService so that
    ``main.py`` and ``routers/dialogs.py`` continue to work without changes.

    Key methods:
        transcribe(audio_path, language, ..., with_speakers)  → Dict
        get_audio_duration(file_path)                          → float (async)
        clear_cache()
        get_cache_stats() → Dict
        get_model_info()  → Dict
    """

    # Singleton ---------------------------------------------------------------

    _instance: Optional["DeepgramTranscriptionService"] = None

    def __new__(cls, **kwargs) -> "DeepgramTranscriptionService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        timeout: Optional[int] = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
        **_ignored,
    ):
        if self._initialized:
            return

        self.api_key = api_key or DEEPGRAM_API_KEY
        self.model = model or DEEPGRAM_MODEL
        self.language = language or DEEPGRAM_LANGUAGE
        self.timeout = timeout or DEEPGRAM_TIMEOUT
        self.cache_size = cache_size

        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_order: List[str] = []

        if not self.api_key:
            logger.warning(
                "DEEPGRAM_API_KEY is not set — transcription will fail. "
                "Set it via env var or pass api_key= to the constructor."
            )

        logger.info(
            f"DeepgramTranscriptionService initialized "
            f"(model={self.model}, language={self.language or 'auto'}, "
            f"timeout={self.timeout}s, cache_size={self.cache_size})"
        )
        self._initialized = True

    # Cache -------------------------------------------------------------------

    def _cache_key(self, audio_path: Path, language: Optional[str]) -> str:
        lang = language or self.language or "auto"
        return f"{audio_path}:{lang}"

    def _cache_put(self, key: str, value: Dict[str, Any]) -> None:
        if key in self._cache:
            self._cache_order.remove(key)
        self._cache[key] = value
        self._cache_order.append(key)
        while len(self._cache_order) > self.cache_size:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_order.clear()
        logger.info("Transcription cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cached_items": len(self._cache),
            "max_cache_size": self.cache_size,
            "cache_keys": list(self._cache.keys()),
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "language": self.language,
            "type": "deepgram",
            "api_url": DEEPGRAM_API_URL,
        }

    # Public interface --------------------------------------------------------

    def transcribe(
        self,
        audio_path,
        language: Optional[str] = None,
        temperature: float = 0.0,
        beam_size: int = 5,
        best_of: int = 5,
        with_speakers: bool = False,
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Deepgram API.

        The signature is intentionally compatible with the old WhisperService.
        ``temperature``, ``beam_size``, ``best_of`` are accepted but ignored
        (not applicable to Deepgram).

        Args:
            audio_path:    Path to audio file (str or Path).
            language:      Language code (e.g. 'ru', 'en'). None → auto-detect.
            with_speakers: Enable speaker diarization (default False).

        Returns:
            Dict with keys: text, language, language_probability, duration,
            segments, transcription_time, real_time_factor.
            If ``with_speakers`` is True, segments include ``speaker`` field.
        """
        if not isinstance(audio_path, Path):
            audio_path = Path(audio_path)

        # Validate extension
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio format: {audio_path.suffix}. "
                f"Supported: {', '.join(SUPPORTED_AUDIO_EXTENSIONS)}"
            )

        # Check cache
        cache_key = self._cache_key(audio_path, language)
        if cache_key in self._cache:
            logger.info(f"Cache hit for {audio_path.name}")
            return self._cache[cache_key]

        # Build Deepgram request — diarize removed, z.ai handles speaker roles
        lang = language or self.language
        params: Dict[str, str] = {
            "model": self.model,
            "punctuate": "true",
            "smart_format": "true",
        }
        if lang and lang != "auto":
            params["language"] = lang

        content_type = CONTENT_TYPES.get(
            audio_path.suffix.lower(), "audio/mpeg"
        )

        logger.info(
            f"Transcribing {audio_path.name} via Deepgram "
            f"(model={self.model}, lang={lang or 'auto'})"
        )

        start_time = time.time()

        # Read file & POST to Deepgram
        if not self.api_key:
            raise RuntimeError(
                "Deepgram API key is not configured. "
                "Set DEEPGRAM_API_KEY in your .env file."
            )

        audio_bytes = audio_path.read_bytes()

        response = httpx.post(
            DEEPGRAM_API_URL,
            params=params,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": content_type,
            },
            content=audio_bytes,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error(f"Deepgram API error {response.status_code}: {error_text}")
            raise RuntimeError(
                f"Deepgram API returned status {response.status_code}: {error_text}"
            )

        data = response.json()
        transcription_time = time.time() - start_time

        # Parse response without speaker info (Deepgram diarize disabled)
        result = self._parse_deepgram_response(data, False, transcription_time)

        # Apply z.ai diarization if requested
        if with_speakers and result.get("segments"):
            logger.info("Running z.ai diarization...")
            result["segments"], zai_debug = _diarize_with_zai(result["segments"])
            result["_zai_debug"] = zai_debug

            # Build speaker_roles from z.ai-labeled segments
            speaker_word_counts: Dict[str, int] = {}
            for seg in result["segments"]:
                spk = seg.get("speaker")
                if spk:
                    speaker_word_counts[spk] = (
                        speaker_word_counts.get(spk, 0) + len(seg["text"].split())
                    )
            speaker_roles: Dict[str, str] = {
                SPEAKER_SALES: "sales",
                SPEAKER_CUSTOMER: "customer",
            }
            result["speaker_roles"] = {
                spk: speaker_roles.get(spk, "unknown")
                for spk in speaker_word_counts
            }
            result["num_speakers"] = len(speaker_word_counts)

        # Cache
        self._cache_put(cache_key, result)

        logger.info(
            f"Transcription completed in {transcription_time:.2f}s "
            f"(language: {result['language']}, duration: {result['duration']:.1f}s, "
            f"RTF: {result['real_time_factor']:.2f}x)"
        )

        return result

    # Deepgram response parsing ------------------------------------------------

    @staticmethod
    def _parse_deepgram_response(
        data: Dict[str, Any],
        with_speakers: bool,
        transcription_time: float,
    ) -> Dict[str, Any]:
        """
        Convert Deepgram JSON into the same dict format the old WhisperService
        returned so the rest of the codebase needs zero changes.
        """
        results = data.get("results", {})
        channels = results.get("channels", [])

        if not channels:
            return {
                "text": "",
                "language": "unknown",
                "language_probability": 0.0,
                "duration": 0.0,
                "segments": [],
                "transcription_time": transcription_time,
                "real_time_factor": 0.0,
            }

        channel = channels[0]
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return {
                "text": "",
                "language": channel.get("detected_language", "unknown"),
                "language_probability": 0.0,
                "duration": 0.0,
                "segments": [],
                "transcription_time": transcription_time,
                "real_time_factor": 0.0,
            }

        best = alternatives[0]
        full_text = best.get("transcript", "")
        words = best.get("words", [])

        # Detected language from metadata
        metadata = data.get("metadata", {})
        duration = metadata.get("duration", 0.0)
        detected_lang = (
            channel.get("detected_language")
            or metadata.get("language", "ru")
        )
        lang_confidence = channel.get("language_confidence", 0.9)

        # Build segments from words — group by punctuation or speaker change
        segments = _words_to_segments(words, with_speakers)

        rtf = transcription_time / duration if duration > 0 else 0

        result: Dict[str, Any] = {
            "text": full_text,
            "language": detected_lang,
            "language_probability": lang_confidence,
            "duration": duration,
            "segments": segments,
            "transcription_time": transcription_time,
            "real_time_factor": rtf,
        }

        return result

    # Audio duration ----------------------------------------------------------

    async def get_audio_duration(self, file_path: str) -> float:
        """Return audio duration in seconds (async)."""
        loop = asyncio.get_event_loop()

        def _get_duration() -> float:
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(file_path)
                return len(audio) / 1000.0
            except ImportError:
                import subprocess
                proc = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        file_path,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return float(proc.stdout.strip())
                raise RuntimeError("Failed to get audio duration")
            except Exception as e:
                logger.error(f"Failed to get duration for {file_path}: {e}")
                raise

        return await loop.run_in_executor(None, _get_duration)


# ---------------------------------------------------------------------------
# Helper: convert Deepgram words → segments (sentence-like chunks)
# ---------------------------------------------------------------------------

def _words_to_segments(
    words: List[Dict[str, Any]],
    with_speakers: bool,
) -> List[Dict[str, Any]]:
    """
    Group Deepgram word-level results into sentence-like segments.

    Splitting rules:
    - on sentence-ending punctuation (.!?)
    - on speaker change (when diarization is enabled)
    - when gap between words > 1.5 s

    Each segment has: id, start, end, text, words, speaker (if diarized).
    """
    if not words:
        return []

    segments: List[Dict[str, Any]] = []
    current_words: List[Dict[str, Any]] = []
    current_speaker: Optional[int] = None
    seg_id = 0

    def _flush():
        nonlocal seg_id
        if not current_words:
            return
        text = " ".join(w["punctuated_word"] if "punctuated_word" in w else w.get("word", "") for w in current_words)
        seg: Dict[str, Any] = {
            "id": seg_id,
            "start": current_words[0].get("start", 0.0),
            "end": current_words[-1].get("end", 0.0),
            "text": text.strip(),
            "words": [
                {
                    "word": w.get("word", ""),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                    "probability": w.get("confidence", 0.0),
                }
                for w in current_words
            ],
        }
        if with_speakers and current_speaker is not None:
            seg["speaker"] = f"SPEAKER_{current_speaker:02d}"
        segments.append(seg)
        seg_id += 1

    for w in words:
        speaker = w.get("speaker")
        word_text = w.get("punctuated_word") or w.get("word", "")

        # Check if we should start a new segment
        speaker_changed = with_speakers and speaker is not None and speaker != current_speaker
        long_pause = (
            current_words
            and w.get("start", 0) - current_words[-1].get("end", 0) > 1.5
        )
        ends_sentence = current_words and any(
            word_text.rstrip().endswith(p) for p in (".", "!", "?")
        )

        if speaker_changed or long_pause:
            _flush()
            current_words = []

        current_words.append(w)
        current_speaker = speaker if speaker is not None else current_speaker

        # Flush after sentence-ending punctuation
        if ends_sentence:
            _flush()
            current_words = []

    _flush()
    return segments


# ---------------------------------------------------------------------------
# Z.ai diarization: identify speaker roles using Claude via z.ai API
# ---------------------------------------------------------------------------

def _diarize_with_zai(segments: List[Dict[str, Any]]) -> tuple:
    """
    Use z.ai (Claude) to assign SPEAKER_00 / SPEAKER_01 labels to segments.

    Sends a numbered list of segment texts to Claude and asks it to classify
    each segment as belonging to the sales agent (SPEAKER_00) or the customer
    (SPEAKER_01). Falls back gracefully — returns unchanged segments on any error.
    """
    global _last_zai_debug

    if not segments:
        return segments, None

    if not ZAI_API_KEY:
        logger.warning("z.ai diarization skipped: ZAI_API_KEY not set")
        return segments, {"error": "ZAI_API_KEY not set"}

    # Build numbered segment list (truncate very long segments for the prompt)
    lines = [
        f"[{i}] {seg.get('text', '')[:300]}"
        for i, seg in enumerate(segments)
    ]
    segments_text = "\n".join(lines)

    prompt = (
        "Ты анализируешь транскрипцию телефонного разговора. "
        "Твоя задача — определить, кому принадлежит каждая реплика.\n\n"
        "Роли участников:\n"
        "• SPEAKER_00 — сотрудник компании: менеджер по продажам, секретарь, консультант. "
        "Как правило, первым начинает разговор, представляется, задаёт вопросы, "
        "рассказывает об услугах или товарах, работает с возражениями.\n"
        "• SPEAKER_01 — клиент / покупатель: звонит или отвечает на звонок, "
        "задаёт вопросы, сомневается, принимает решение о покупке.\n\n"
        "Если в записи явно слышны три разные роли (например, секретарь + менеджер + клиент), "
        "всё равно используй только два кода: сотрудник → SPEAKER_00, клиент → SPEAKER_01.\n\n"
        f"Пронумерованные реплики:\n{segments_text}\n\n"
        "Верни ТОЛЬКО JSON-массив без каких-либо пояснений. Формат каждого элемента:\n"
        '{"id": <номер>, "speaker": "SPEAKER_00" или "SPEAKER_01"}\n\n'
        "Пример ответа:\n"
        '[{"id":0,"speaker":"SPEAKER_00"},{"id":1,"speaker":"SPEAKER_01"},{"id":2,"speaker":"SPEAKER_00"}]'
    )

    try:
        resp = httpx.post(
            ZAI_API_URL,
            json={
                "model": ZAI_MODEL,
                "max_tokens": max(512, len(segments) * 25),
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={
                "x-api-key": ZAI_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=ZAI_DIARIZATION_TIMEOUT,
        )

        resp_json = resp.json()
        debug_info = {
            "status_code": resp.status_code,
            "prompt": prompt,
            "raw_response": resp_json,
        }

        if resp.status_code != 200:
            logger.error(
                f"z.ai diarization API error {resp.status_code}: {resp.text[:300]}"
            )
            return segments, debug_info

        content_blocks = resp_json.get("content", [])
        raw_text = content_blocks[0].get("text", "") if content_blocks else ""
        debug_info["raw_text"] = raw_text

        # Extract JSON array from the response (Claude may add surrounding text)
        match = re.search(r"\[[\s\S]*?\]", raw_text)
        if not match:
            logger.warning(
                f"z.ai diarization: no JSON array found in response: {raw_text[:200]}"
            )
            return segments, debug_info

        labels = json.loads(match.group())
        label_map: Dict[int, str] = {
            item["id"]: item["speaker"]
            for item in labels
            if isinstance(item.get("id"), int) and "speaker" in item
        }

        for i, seg in enumerate(segments):
            if i in label_map:
                seg["speaker"] = label_map[i]

        logger.info(
            f"z.ai diarization complete: {len(label_map)}/{len(segments)} segments labeled"
        )
        _last_zai_debug = debug_info
        return segments, debug_info

    except Exception as exc:
        logger.error(f"z.ai diarization failed: {exc}")
        _last_zai_debug = {"error": str(exc)}
        return segments, {"error": str(exc)}  # graceful fallback


# ---------------------------------------------------------------------------
# Debug store: last z.ai diarization response (temporary, for dev only)
# ---------------------------------------------------------------------------

_last_zai_debug: Optional[Dict[str, Any]] = None


def get_last_zai_debug() -> Optional[Dict[str, Any]]:
    """Return the last stored z.ai diarization debug info (in-memory)."""
    return _last_zai_debug


# ---------------------------------------------------------------------------
# Singleton accessor (same names as before for backward compatibility)
# ---------------------------------------------------------------------------

_service_instance: Optional[DeepgramTranscriptionService] = None


def get_transcription_service(**kwargs) -> DeepgramTranscriptionService:
    """
    Get or create the singleton transcription service.

    Accepts the same keyword arguments as old ``get_transcription_service``
    for backward compatibility (model_size, device, etc.) — they are ignored.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = DeepgramTranscriptionService(**kwargs)
    return _service_instance


# Backward-compatible alias used in main.py and routers
get_whisper_service = get_transcription_service
# Keep class name alias so `from .transcriber import WhisperService` still works
WhisperService = DeepgramTranscriptionService
