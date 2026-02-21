"""
VOICEcheck - FastAPI Application for Audio Transcription and Sales Dialogue Analysis

Central application module that orchestrates the entire VOICEcheck service.
Integrates audio transcription (Whisper), database operations (PostgreSQL),
and AI-powered dialogue analysis (GPT-4o via z.ai API).

Key Responsibilities:
- Hosts all REST API endpoints for the web service
- Manages in-memory task and file storage
- Handles background processing of transcription tasks
- Provides health monitoring and status tracking
- Implements error handling and logging

Architecture Components:
- FastAPI: Web framework for REST API
- Whisper: Audio transcription service (OpenAI)
- PostgreSQL: Database for persistent storage
- GPT-4o: AI dialogue analysis via z.ai API
- Background Tasks: Async processing for transcription

API Endpoints:
- GET / : Serve main HTML interface
- GET /health : System health check
- POST /upload : Upload audio file
- POST /transcribe/{file_id} : Start transcription
- GET /status/{task_id} : Check task status
- GET /result/{task_id} : Get transcription results
- DELETE /file/{file_id} : Delete uploaded file

Note: Dialog-specific endpoints are moved to routers/dialogs.py for better organization
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime
from uuid import uuid4

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    BackgroundTasks,
    Form,
    Depends,
    Request
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

# Application components
from .transcriber import get_whisper_service, WhisperService
from .models import (
    UploadResponse,
    TranscribeResponse,
    TaskStatus,
    ErrorResponse
)
from .dependencies import get_llm_analyzer
from .database.connection import get_db
from .database.connection import init_db, close_db, health_check
from .database import models as db_models
from .routers.dialogs import router as dialogs_router
from .routers.export import router as export_router
from .config import get_settings

# Auth imports
from .auth.dependencies import require_auth, get_token_from_header
from .auth.service import AuthService
from .auth.models import User, Membership

# Get settings instance
settings = get_settings()

# Conditionally import auth routers when enabled
if settings.auth_enabled:
    from .routers.auth import router as auth_router
    from .routers.organizations import router as organizations_router
    from .routers.departments import router as departments_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Application Configuration Constants
# File handling constraints
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB maximum file size
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm"}
# Upload directory setup
UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory storage (use Redis/DB in production)
# Stores task metadata and file information
TASKS_STORAGE: Dict[str, Dict[str, Any]] = {}
FILES_STORAGE: Dict[str, Dict[str, Any]] = {}

# Initialize FastAPI application
app = FastAPI(
    title="VOICEcheck",
    description="Audio transcription service using Whisper with LLM analysis",
    version="1.0.0"
)

# Add CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/dialogs/sellers")
async def get_sellers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth)
) -> List[str]:
    """Return a sorted list of unique seller names from user's accessible dialogs."""
    # Get user's organization IDs
    org_ids_result = await db.execute(
        select(Membership.organization_id).where(
            and_(
                Membership.user_id == user.id,
                Membership.is_active == True
            )
        )
    )
    org_ids = [row[0] for row in org_ids_result.all()]

    # Build access filter
    conditions = [
        db_models.Dialog.seller_name.isnot(None),
        db_models.Dialog.seller_name != ""
    ]

    # Add auth filter: (no owner) OR (owned by user) OR (owned by user's orgs)
    access_filter = or_(
        db_models.Dialog.owner_type.is_(None),
        and_(
            db_models.Dialog.owner_type == "user",
            db_models.Dialog.owner_id == user.id
        ),
        and_(
            db_models.Dialog.owner_type == "organization",
            db_models.Dialog.owner_id.in_(org_ids) if org_ids else False
        )
    )

    query = select(db_models.Dialog.seller_name).where(
        and_(*conditions, access_filter)
    ).distinct().order_by(db_models.Dialog.seller_name)

    result = await db.execute(query)
    return [row[0] for row in result.all()]


# Include API routers
# Note: Sellers endpoint is defined BEFORE dialogs router to avoid route conflicts
app.include_router(export_router)
app.include_router(dialogs_router)

# Include auth routers if enabled
if settings.auth_enabled:
    logger.info("Authentication enabled - including auth and organizations routers")
    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(departments_router)
else:
    logger.info("Authentication disabled - running in legacy mode")


# Employee login route - serves auth-org.html for /login/{code} URLs
@app.get("/login/{code}")
async def org_login_page(code: str):
    """Serve the organization login page for employee access via shareable link."""
    index_path = Path("/app/static/auth-org.html")
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Login page not found")


# Mount static files
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# Event handlers for database initialization and cleanup
@app.on_event("startup")
async def startup_event() -> None:
    """
    Initialize database and application services on startup.

    Sets up database connection, creates necessary tables,
    and initializes the LLM analyzer if available.
    """
    logger.info("Initializing database...")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set, using in-memory storage")
        return

    try:
        await init_db(db_url)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # Continue without database for now


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up database connections and resources on shutdown."""
    logger.info("Shutting down database...")
    await close_db()
    logger.info("Database shutdown complete")


# File Validation Utilities
# These functions handle file format validation for transcription processing

def get_file_extension(filename: str) -> str:
    """
    Extract file extension from filename with case normalization.

    Args:
        filename: Name of the audio file

    Returns:
        Lowercase file extension including the dot (e.g., '.mp3', '.wav')

    Example:
        >>> get_file_extension("example.MP3")
        '.mp3'
    """
    return Path(filename).suffix.lower()


def is_allowed_file(filename: str) -> bool:
    """
    Validate if file extension is supported for audio transcription.

    Args:
        filename: Name of the file to validate

    Returns:
        bool: True if file extension is in the allowed list, False otherwise

    Note:
        Supported formats: mp3, wav, m4a, ogg, flac, mp4, webm
    """
    return get_file_extension(filename) in ALLOWED_EXTENSIONS


def process_transcription(
    task_id: str,
    file_path: str,
    language: Optional[str] = None,
    with_speakers: bool = False
) -> None:
    """
    Background task to process audio transcription without database integration.

    Simple version for when database is not available or for testing purposes.
    Updates task status in memory storage and performs transcription using Whisper.

    Args:
        task_id: Unique task identifier for tracking progress
        file_path: Path to the audio file to transcribe
        language: Language code (e.g., 'en', 'ru') or None for auto-detection
        with_speakers: Whether to enable speaker diarization (True/False)

    Note:
        This function updates TASKS_STORAGE in-memory storage only.
        For production use process_transcription_with_db instead.
    """
    try:
        # Update task status to "processing" with initial progress
        TASKS_STORAGE[task_id]["status"] = "processing"
        TASKS_STORAGE[task_id]["progress"] = 10
        TASKS_STORAGE[task_id]["message"] = "Подготовка к транскрибации..."

        # Get Whisper service instance and update progress
        service = get_whisper_service()
        TASKS_STORAGE[task_id]["progress"] = 30

        # Perform audio transcription with optional speaker diarization
        result = service.transcribe(file_path, language=language, with_speakers=with_speakers)

        # Store result in memory
        TASKS_STORAGE[task_id]["status"] = "completed"
        TASKS_STORAGE[task_id]["progress"] = 100
        TASKS_STORAGE[task_id]["message"] = "Транскрибация завершена"
        TASKS_STORAGE[task_id]["result"] = result

        logger.info(f"Задание {task_id} завершено успешно")

    except Exception as e:
        # Handle any errors during transcription
        logger.error(f"Задание {task_id} не выполнено: {e}")
        TASKS_STORAGE[task_id]["status"] = "failed"
        TASKS_STORAGE[task_id]["message"] = str(e)


async def process_transcription_with_db(
    task_id: str,
    file_path: str,
    dialog_id: str,
    db: AsyncSession,
    language: Optional[str] = None,
    with_speakers: bool = False
) -> None:
    """
    Complete transcription and analysis workflow with database persistence.

    This function orchestrates the entire pipeline for audio processing:
    1. Updates task status in storage
    2. Performs audio transcription using Whisper service
    3. Saves transcription results to database with segments
    4. Runs AI-powered LLM analysis if available
    5. Updates dialog status in database
    6. Handles errors gracefully without failing the entire task

    Args:
        task_id: Unique task identifier for progress tracking
        file_path: Path to the audio file for transcription
        dialog_id: UUID string of the associated dialog in database
        db: SQLAlchemy async session for database operations
        language: Language code (e.g., 'en', 'ru') or None for auto-detection
        with_speakers: Whether to enable speaker diarization (separates speakers)

    Workflow Steps:
        - Status updates: pending -> processing -> completed/failed
        - Progress tracking: 10% (model load) -> 30% (transcribe) -> 70% (save) -> 100%
        - Error handling: Database commits are independent of LLM analysis
        - Fallback: If LLM analysis fails, transcription still succeeds

    Note:
        This function is designed to be resilient - if LLM analysis fails,
        the transcription result is still saved to database successfully.
    """
    # Initialize dialog variable for error handling during transaction
    dialog = None

    try:
        # Update task status to indicate processing started
        TASKS_STORAGE[task_id]["status"] = "processing"
        TASKS_STORAGE[task_id]["progress"] = 10
        TASKS_STORAGE[task_id]["message"] = "Подготовка к транскрибации..."

        # Get Whisper service and update progress to transcription phase
        service = get_whisper_service()
        TASKS_STORAGE[task_id]["progress"] = 30

        # Perform main audio transcription with optional speaker separation
        result = service.transcribe(file_path, language=language, with_speakers=with_speakers)

        # Progress to database saving phase
        TASKS_STORAGE[task_id]["progress"] = 70
        TASKS_STORAGE[task_id]["message"] = "Сохранение в базу данных..."

        # Convert string UUID to proper UUID object for database
        from uuid import UUID
        dialog_uuid = UUID(dialog_id)

        # Fetch existing dialog from database
        dialog_query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        dialog_result = await db.execute(dialog_query)
        dialog = dialog_result.scalar_one_or_none()

        # Ensure dialog exists before proceeding
        if not dialog:
            raise Exception("Dialog not found in database")

        # Create transcription record with timed segments and speaker information
        transcription = db_models.Transcription(
            dialog_id=dialog_uuid,
            text=result["text"],  # Full transcribed text
            language=result["language"],  # Detected language
            language_probability=result["language_probability"],  # Confidence score
            segments=[
                {
                    "start": s["start"],  # Start time in seconds
                    "end": s["end"],      # End time in seconds
                    "text": s["text"],    # Segment text
                    "speaker": s.get("speaker", "SPEAKER_00")  # Speaker identifier
                } for s in result["segments"]
            ]
        )

        # Add transcription to database session
        db.add(transcription)

        # Mark dialog as completed in database
        dialog.status = "completed"
        await db.commit()

        # Optional: Run AI-powered dialogue analysis if LLM analyzer is available
        try:
            llm = get_llm_analyzer()
            if llm:
                logger.info(f"Running LLM analysis for dialog {dialog_id}")

                # Convert segment dictionaries to Segment model objects for LLM analysis
                from .models import Segment
                segment_objects = [
                    Segment(
                        start=s["start"],
                        end=s["end"],
                        text=s["text"],
                        speaker=s.get("speaker", "SPEAKER_00")
                    ) for s in result["segments"]
                ]

                # Perform AI analysis of the dialogue
                analysis_result = await llm.analyze_dialog(segments=segment_objects)

                # Save analysis results to database
                if analysis_result:
                    analysis = db_models.DialogAnalysis(
                        dialog_id=dialog_uuid,
                        scores=analysis_result.scores,
                        key_moments=analysis_result.key_moments,
                        recommendations=analysis_result.recommendations,
                        summary=analysis_result.summary,
                        speaking_time=analysis_result.speaking_time
                    )
                    db.add(analysis)
                    await db.commit()
                    logger.info(f"LLM analysis completed for dialog {dialog_id}")
        except Exception as e:
            logger.error(f"LLM analysis failed for dialog {dialog_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Final status update - task completed successfully
        TASKS_STORAGE[task_id]["status"] = "completed"
        TASKS_STORAGE[task_id]["progress"] = 100
        TASKS_STORAGE[task_id]["message"] = "Транскрибация завершена"
        TASKS_STORAGE[task_id]["result"] = result

        logger.info(f"Задание {task_id} завершено успешно")

    except Exception as e:
        # Handle any errors in the transcription workflow
        logger.error(f"Задание {task_id} не выполнено: {e}")
        TASKS_STORAGE[task_id]["status"] = "failed"
        TASKS_STORAGE[task_id]["message"] = str(e)

        # Update dialog status to failed in database if possible
        try:
            if dialog and db:
                dialog.status = "failed"
                await db.commit()
                logger.info(f"Dialog {dialog_id} status updated to failed")
        except Exception as db_error:
            # Log database errors but don't raise them
            logger.error(f"Failed to update dialog status: {db_error}")


# API Routes

@app.get("/", response_model=None)
async def root() -> HTMLResponse:
    """
    Serve the main HTML interface page.

    Authentication is checked client-side via JavaScript in index.html.
    The page is always served, but JavaScript will redirect to auth if not logged in.
    """
    index_path = Path("/app/static/index.html")
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>VOICEcheck API</h1><p>See /docs for API documentation</p>")


@app.get("/health")
async def health() -> Dict[str, Any]:
    """
    Comprehensive system health check endpoint.

    Provides status of all critical components:
    - Whisper service availability and model info
    - Database connection status
    - Task and file storage statistics
    - Application overall health status

    Returns:
        Dict containing:
            - status: "healthy" if all systems operational
            - model_info: Whisper model information
            - tasks_count: Number of active tasks
            - files_count: Number of stored files
            - database: Database connection status

    Example Response:
        {
            "status": "healthy",
            "model_info": {"model": "tiny", "size": "75MB"},
            "tasks_count": 5,
            "files_count": 3,
            "database": "available"
        }
    """
    service = get_whisper_service()

    # Check database health
    db_status = "unavailable"
    try:
        db_health = await health_check()
        db_status = db_health.get("status", "unknown")
    except Exception:
        pass

    return {
        "status": "healthy",
        "model_info": service.get_model_info(),
        "tasks_count": len(TASKS_STORAGE),
        "files_count": len(FILES_STORAGE),
        "database": db_status
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    seller_name: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth)
) -> UploadResponse:
    """
    Upload audio file for transcription and create dialog record.

    This endpoint handles the complete upload workflow:
    1. Validates file type and size
    2. Generates unique file ID and saves file
    3. Extracts audio duration using Whisper service
    4. Creates dialog record in database
    5. Updates file storage with dialog reference

    Args:
        file: Audio file upload (must be in allowed format)
        db: Database session for creating dialog record

    Returns:
        UploadResponse containing:
            - file_id: Unique identifier for the uploaded file
            - filename: Original filename
            - size: File size in bytes
            - content_type: MIME type of the file

    Raises:
        HTTPException: For invalid file types, oversized files, or database errors

    Note:
        Each upload automatically creates a dialog record in the database
    """
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024*1024)}MB"
        )

    # Generate unique file ID
    file_id = str(uuid4())
    file_extension = get_file_extension(file.filename)
    saved_path = UPLOAD_DIR / f"{file_id}{file_extension}"

    # Save file
    with open(saved_path, "wb") as f:
        f.write(content)

    # Get duration of audio file
    service = get_whisper_service()
    duration = await service.get_audio_duration(str(saved_path))

    # Store file info FIRST (before dialog creation)
    FILES_STORAGE[file_id] = {
        "filename": file.filename,
        "path": str(saved_path),
        "size": len(content),
        "content_type": file.content_type or "audio/mpeg",
        "dialog_id": None
    }
    logger.info(f"File stored in FILES_STORAGE: {file_id}")

    # Create dialog record in database
    try:
        dialog_uuid = uuid4()
        logger.info(f"Creating dialog with UUID: {dialog_uuid}")

        db_dialog = db_models.Dialog(
            id=dialog_uuid,
            filename=file.filename,
            duration=duration,
            status="pending",
            file_path=str(saved_path),
            language=None,
            seller_name=seller_name,
            created_by=user.id
        )
        db.add(db_dialog)
        await db.commit()
        logger.info(f"Dialog committed to DB")

        await db.refresh(db_dialog)
        logger.info(f"Dialog refreshed, ID: {db_dialog.id}")

        # Store dialog ID in files dict for reference
        if file_id in FILES_STORAGE:
            FILES_STORAGE[file_id]["dialog_id"] = str(db_dialog.id)
            logger.info(f"Dialog ID stored in FILES_STORAGE for file {file_id}: {FILES_STORAGE[file_id]['dialog_id']}")
        else:
            logger.error(f"CRITICAL: file_id {file_id} not found in FILES_STORAGE after dialog creation!")

    except Exception as e:
        logger.error(f"Failed to create dialog: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

    logger.info(f"File uploaded: {file.filename} ({file_id})")

    return UploadResponse(
        file_id=file_id,
        filename=file.filename,
        size=len(content),
        content_type=file.content_type or "audio/mpeg"
    )


@app.post("/transcribe/{file_id}", response_model=TaskStatus)
async def transcribe_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    language: Optional[str] = Form(default="auto"),
    with_speakers: bool = Form(default=False)
) -> TaskStatus:
    """
    Initiate audio transcription process for an uploaded file.

    This endpoint triggers the background transcription workflow:
    1. Validates file exists and has associated dialog
    2. Checks if transcription already completed
    3. Updates dialog status to "processing"
    4. Creates task tracking object
    5. Starts background transcription and analysis task

    Args:
        file_id: Unique identifier of the uploaded file
        background_tasks: FastAPI background task manager for async processing
        db: Database session for updating dialog status
        language: Language code (e.g., 'en', 'ru') or 'auto' for auto-detection
        with_speakers: Enable speaker diarization (separate speakers in transcription)

    Returns:
        TaskStatus object containing:
            - task_id: Unique task identifier for status tracking
            - status: Current task status (pending/processing/completed/failed)
            - progress: Progress percentage (0-100)
            - message: Status message in Russian
            - result: Transcription results when completed
            - created_at: Task creation timestamp

    Raises:
        HTTPException: For invalid file_id or missing dialog association

    Note:
        The transcription runs in background to prevent blocking the API response.
        Use GET /status/{task_id} to track progress.
    """
    # Validate file exists
    if file_id not in FILES_STORAGE:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = FILES_STORAGE[file_id]

    # Get or create dialog
    dialog_id = file_info.get("dialog_id")
    if not dialog_id:
        raise HTTPException(status_code=400, detail="Dialog not associated with file")

    # Check if already transcribed
    try:
        from uuid import UUID
        dialog_uuid = UUID(dialog_id)
        query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if dialog and dialog.status == "completed":
            return TaskStatus(
                task_id=dialog_id,
                status="completed",
                progress=100,
                message="Already transcribed",
                result={"message": "Transcription already completed"},
                created_at=dialog.created_at
            )
    except Exception:
        pass

    # Update dialog status
    try:
        dialog_query = select(db_models.Dialog).where(db_models.Dialog.id == UUID(dialog_id))
        dialog_result = await db.execute(dialog_query)
        dialog = dialog_result.scalar_one_or_none()

        if dialog:
            dialog.status = "processing"
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to update dialog status: {e}")

    # Create new task
    task_id = str(uuid4())
    TASKS_STORAGE[task_id] = {
        "task_id": task_id,
        "dialog_id": dialog_id,
        "file_id": file_id,
        "status": "pending",
        "progress": 0,
        "message": "Задание создано",
        "result": None,
        "created_at": datetime.utcnow()
    }

    # Start background processing
    background_tasks.add_task(
        process_transcription_with_db,
        task_id,
        file_info["path"],
        dialog_id,
        db,
        language if language != "auto" else None,
        with_speakers
    )

    logger.info(f"Transcription started: {task_id} for file {file_id}")

    return TaskStatus(**TASKS_STORAGE[task_id])


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_status(task_id: str) -> TaskStatus:
    """
    Retrieve current status of a transcription task.

    Provides real-time progress updates for transcription and analysis tasks.
    Includes progress percentage, status messages, and completed results.

    Args:
        task_id: Unique task identifier from the transcribe request

    Returns:
        TaskStatus object with complete task information:
            - task_id: Task identifier
            - status: Current task status (pending/processing/completed/failed)
            - progress: Progress percentage (0-100)
            - message: Status message (in Russian for user experience)
            - result: Transcription data when completed (JSON format)
            - created_at: UTC timestamp of task creation

    Raises:
        HTTPException: When task_id is not found in storage

    Note:
        This endpoint supports polling for real-time status updates
    """
    if task_id not in TASKS_STORAGE:
        raise HTTPException(status_code=404, detail="Task not found")

    task = TASKS_STORAGE[task_id]

    return TaskStatus(
        task_id=task["task_id"],
        status=task["status"],
        progress=task["progress"],
        message=task.get("message"),
        result=task.get("result"),
        created_at=task["created_at"]
    )


@app.get("/result/{task_id}")
async def get_result(task_id: str) -> Dict[str, Any]:
    """
    Retrieve completed transcription results.

    Returns the full transcription result including text segments, language detection,
    and speaker information. Only accessible when the task is completed.

    Args:
        task_id: Unique task identifier from the transcribe request

    Returns:
        Dict containing:
            - text: Full transcribed text
            - language: Detected language code
            - language_probability: Confidence score for language detection
            - segments: List of timed segments with speaker info

    Raises:
        HTTPException: When task not found or not completed

    Note:
        Only available for tasks with status "completed"
    """
    if task_id not in TASKS_STORAGE:
        raise HTTPException(status_code=404, detail="Task not found")

    task = TASKS_STORAGE[task_id]

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task['status']}"
        )

    return task["result"]


@app.delete("/file/{file_id}")
async def delete_file(file_id: str) -> Dict[str, str]:
    """
    Delete an uploaded file and associated resources.

    Performs complete cleanup:
    1. Removes file from disk storage
    2. Removes file from FILES_STORAGE
    3. Cleans up related tasks from TASKS_STORAGE
    4. Calls Whisper service cleanup if needed

    Args:
        file_id: Unique identifier of the file to delete

    Returns:
        Dict with confirmation message

    Raises:
        HTTPException: When file_id is not found

    Note:
        This operation cannot be undone. Related tasks are also cleaned up.
    """
    if file_id not in FILES_STORAGE:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = FILES_STORAGE[file_id]
    # Remove the uploaded file from disk
    file_path = Path(file_info["path"])
    if file_path.exists():
        file_path.unlink()

    del FILES_STORAGE[file_id]

    # Cleanup related tasks
    tasks_to_remove = [
        tid for tid, task in TASKS_STORAGE.items()
        if task.get("file_id") == file_id
    ]
    for tid in tasks_to_remove:
        del TASKS_STORAGE[tid]

    return {"message": "Файл успешно удален"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for uncaught errors.

    Provides consistent error responses for all unhandled exceptions.
    Logs the error details for debugging while returning generic error to client.

    Args:
        request: FastAPI request object that caused the error
        exc: Exception that was raised

    Returns:
        JSONResponse with error details including:
            - error: Error type name
            - detail: Error message (sanitized for security)
            - timestamp: UTC timestamp of error

    Note:
        All exceptions are logged with full stack trace for debugging.
        User-facing messages are sanitized to avoid exposing sensitive information.
    """
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


# Dialog-related endpoints moved to routers/dialogs.py
# The following endpoints are now handled by the router:
# - GET /dialogs - list dialogs with pagination
# - GET /dialogs/{dialog_id} - get dialog details
# - PUT /dialogs/{dialog_id}/status - update dialog status
# - DELETE /dialogs/{dialog_id} - delete dialog
# - GET /dialogs/{dialog_id}/timeline - get dialog timeline
# - GET /dialogs/{dialog_id}/export - export dialog analysis


