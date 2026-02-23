"""
REST API routes for dialog management.

This module provides endpoints for:
- Creating and listing dialogs
- Retrieving detailed dialog information
- Updating dialog status
- Deleting dialogs and related data
- Timeline and audio serving
- Dashboard aggregate statistics

All endpoints support optional authentication via FEATURE_FLAG_AUTH.
When auth is enabled, dialogs are filtered by user's organization access.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from uuid import UUID
from pathlib import Path
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Form
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, Float
from sqlalchemy.orm import selectinload

from ..database import models as db_models
from ..database.connection import get_db
from ..schemas import (
    DialogCreate,
    DialogUpdate,
    PaginatedResponse,
)
from ..models import (
    DialogDetail,
    DialogAnalysisResponse,
    DialogStatusUpdate,
    Segment,
)
from ..dependencies import get_llm_analyzer
from ..transcriber import get_whisper_service, get_last_zai_debug
from ..config import AUTH_ENABLED

# Auth imports
from ..auth.dependencies import require_auth, get_current_organization, OrganizationContext
from ..auth.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dialogs", tags=["dialogs"])


# ============================================================
# Auth Helper Functions
# ============================================================

async def get_accessible_dialog_filter(
    user: User,
    user_org_ids: List[UUID],
    active_org_id=None,
) -> List[Any]:
    """
    Build filter conditions for dialogs accessible by user.
    If active_org_id is set, filter by that single org only.
    """
    if active_org_id:
        return [
            and_(
                db_models.Dialog.owner_type == "organization",
                db_models.Dialog.owner_id == active_org_id,
            )
        ]

    conditions = []
    conditions.append(db_models.Dialog.owner_type.is_(None))
    conditions.append(
        and_(
            db_models.Dialog.owner_type == "user",
            db_models.Dialog.owner_id == user.id
        )
    )
    if user_org_ids:
        conditions.append(
            and_(
                db_models.Dialog.owner_type == "organization",
                db_models.Dialog.owner_id.in_(user_org_ids)
            )
        )
    return conditions


async def get_user_org_ids(
    user: User,
    db: AsyncSession
) -> List[UUID]:
    """
    Get list of organization IDs for a user.

    Args:
        user: User object
        db: Database session

    Returns:
        List of organization UUIDs
    """
    from ..auth.models import Membership

    result = await db.execute(
        select(Membership.organization_id).where(
            and_(
                Membership.user_id == user.id,
                Membership.is_active == True
            )
        )
    )
    return [row[0] for row in result.all()]


# ---------------------------------------------------------------------------
# Sellers list (must be before /{dialog_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/sellers-list")
async def get_sellers():
    """Return a sorted list of unique seller names."""
    return ["test1", "test2"]


# ---------------------------------------------------------------------------
# Dashboard endpoint (must be before /{dialog_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    date_from: Optional[datetime] = Query(None, description="Start date filter"),
    date_to: Optional[datetime] = Query(None, description="End date filter"),
    seller_name: Optional[str] = Query(None, description="Filter by seller name"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
) -> Dict[str, Any]:
    """
    Return aggregate statistics for the team dashboard.

    Only includes statistics from user's accessible dialogs.
    """
    try:
        # Get user's organization IDs
        org_ids = await get_user_org_ids(user, db)
        active_org_id = org_ctx.organization.id if org_ctx else None

        # Base conditions for dialogs
        conditions = []
        if date_from:
            conditions.append(db_models.Dialog.created_at >= date_from)
        if date_to:
            conditions.append(db_models.Dialog.created_at <= date_to)
        if seller_name:
            conditions.append(db_models.Dialog.seller_name.ilike(f"%{seller_name}%"))

        # Apply auth filter
        access_conditions = await get_accessible_dialog_filter(user, org_ids, active_org_id)
        # Combine access filter with other conditions using AND
        # Access filter is an OR list, so we need to wrap it
        if conditions:
            combined_conditions = [or_(*access_conditions)] + conditions
        else:
            combined_conditions = access_conditions
        total_query = select(func.count(db_models.Dialog.id)).where(and_(*combined_conditions))

        # Total dialogs
        total_dialogs = (await db.execute(total_query)).scalar() or 0

        # Deal rate
        analyzed_statuses = ['dealed', 'in_progress', 'rejected']

        if AUTH_ENABLED and user:
            access_conditions = await get_accessible_dialog_filter(user, org_ids, active_org_id)
            base_cond = [or_(*access_conditions)]
        else:
            base_cond = []

        analyzed_cond = base_cond + [db_models.Dialog.status.in_(analyzed_statuses)] + conditions
        completed_count = (await db.execute(
            select(func.count(db_models.Dialog.id)).where(and_(*analyzed_cond))
        )).scalar() or 0

        dealed_cond = base_cond + [db_models.Dialog.status == 'dealed'] + conditions
        dealed_count = (await db.execute(
            select(func.count(db_models.Dialog.id)).where(and_(*dealed_cond))
        )).scalar() or 0

        deal_rate = dealed_count / max(completed_count, 1)

        # Fetch all analyses with their dialog dates for scoring dynamics
        analyses_query = (
            select(
                db_models.Dialog.created_at,
                db_models.DialogAnalysis.scores,
                db_models.DialogAnalysis.key_moments,
            )
            .join(db_models.DialogAnalysis, db_models.Dialog.id == db_models.DialogAnalysis.dialog_id)
        )

        if AUTH_ENABLED and user:
            access_conditions = await get_accessible_dialog_filter(user, org_ids, active_org_id)
            if conditions:
                analyses_query = analyses_query.where(and_(or_(*access_conditions), and_(*conditions)))
            else:
                analyses_query = analyses_query.where(or_(*access_conditions))
        elif conditions:
            analyses_query = analyses_query.where(and_(*conditions))

        analyses_query = analyses_query.order_by(db_models.Dialog.created_at.asc())

        analyses_result = await db.execute(analyses_query)
        analyses_rows = analyses_result.all()

        # Scoring dynamics by date
        daily_scores: Dict[str, list] = {}
        all_scores_sum: Dict[str, float] = {
            "greeting": 0, "needs_discovery": 0, "presentation": 0,
            "objection_handling": 0, "closing": 0, "active_listening": 0,
            "empathy": 0, "overall": 0
        }
        total_analyses = 0

        # Common objections
        objection_texts: list = []

        for row in analyses_rows:
            created_at, scores, key_moments = row
            date_key = created_at.strftime('%Y-%m-%d')

            overall = scores.get('overall', 0) if scores else 0
            if date_key not in daily_scores:
                daily_scores[date_key] = []
            daily_scores[date_key].append(overall)

            # Accumulate category scores
            if scores:
                total_analyses += 1
                for cat in all_scores_sum:
                    all_scores_sum[cat] += scores.get(cat, 0)

            # Collect objections
            if key_moments:
                for moment in key_moments:
                    if moment.get('type') == 'objection':
                        objection_texts.append(moment.get('text', ''))

        # Build scoring dynamics array
        scoring_dynamics = []
        for date_key in sorted(daily_scores.keys()):
            values = daily_scores[date_key]
            scoring_dynamics.append({
                "date": date_key,
                "overall_score": round(sum(values) / len(values), 1)
            })

        # Average category scores
        avg_category_scores = {}
        if total_analyses > 0:
            for cat, total in all_scores_sum.items():
                avg_category_scores[cat] = round(total / total_analyses, 1)

        # Common objections (top 10)
        objection_counter = Counter(objection_texts)
        common_objections = [
            {"text": text, "count": count}
            for text, count in objection_counter.most_common(10)
            if text
        ]

        return {
            "total_dialogs": total_dialogs,
            "avg_overall_score": avg_category_scores.get("overall"),
            "deal_rate": round(deal_rate, 3),
            "avg_category_scores": avg_category_scores,
            "scoring_dynamics": scoring_dynamics,
            "common_objections": common_objections,
        }

    except Exception as e:
        logger.error(f"Failed to get dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load dashboard: {str(e)}")


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=dict, status_code=201)
async def create_dialog(
    background_tasks: BackgroundTasks,
    dialog_data: DialogCreate,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Create a new dialog record and start background processing."""
    try:
        db_dialog = db_models.Dialog(
            filename=dialog_data.filename,
            duration=dialog_data.duration,
            status="processing",
            file_path=dialog_data.file_path,
            language=dialog_data.language
        )

        db.add(db_dialog)
        await db.commit()
        await db.refresh(db_dialog)

        task_id = str(db_dialog.id)
        background_tasks.add_task(
            process_transcription_and_analysis,
            task_id,
            dialog_data.file_path,
            dialog_data.language,
            db
        )

        logger.info(f"Created dialog {db_dialog.id} with task {task_id}")

        return {
            "id": str(db_dialog.id),
            "filename": db_dialog.filename,
            "status": "processing",
            "task_id": task_id,
            "created_at": db_dialog.created_at.isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to create dialog: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка создания диалога: {str(e)}")


@router.get("/", response_model=PaginatedResponse)
async def get_dialogs(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    language: Optional[str] = Query(None, description="Filter by language"),
    date_from: Optional[datetime] = Query(None, description="From date"),
    date_to: Optional[datetime] = Query(None, description="To date"),
    search: Optional[str] = Query(None, description="Search in filename"),
    seller_name: Optional[str] = Query(None, description="Filter by seller name"),
    min_score: Optional[float] = Query(None, ge=0, le=10, description="Min overall score"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
) -> PaginatedResponse:
    """
    Retrieve paginated list of dialogs with filtering.

    Only returns dialogs accessible to the authenticated user.
    """
    try:
        # Get user's organization IDs
        org_ids = await get_user_org_ids(user, db)
        active_org_id = org_ctx.organization.id if org_ctx else None

        query = select(db_models.Dialog).options(
            selectinload(db_models.Dialog.analyses)
        )
        count_query = select(func.count(db_models.Dialog.id))
        conditions = []

        if status:
            conditions.append(db_models.Dialog.status == status)
        if language:
            conditions.append(db_models.Dialog.language == language)
        if date_from:
            conditions.append(db_models.Dialog.created_at >= date_from)
        if date_to:
            conditions.append(db_models.Dialog.created_at <= date_to)
        if search:
            conditions.append(db_models.Dialog.filename.ilike(f"%{search}%"))
        if seller_name:
            conditions.append(db_models.Dialog.seller_name.ilike(f"%{seller_name}%"))

        # Score filter requires joining with analysis
        if min_score is not None:
            query = query.join(
                db_models.DialogAnalysis,
                db_models.Dialog.id == db_models.DialogAnalysis.dialog_id
            )
            count_query = count_query.join(
                db_models.DialogAnalysis,
                db_models.Dialog.id == db_models.DialogAnalysis.dialog_id
            )
            conditions.append(
                db_models.DialogAnalysis.scores['overall'].astext.cast(Float) >= min_score
            )

        # Apply auth filter
        access_conditions = await get_accessible_dialog_filter(user, org_ids, active_org_id)
        # Combine: (access_filter) AND (other conditions)
        query = query.where(or_(*access_conditions))
        count_query = count_query.where(or_(*access_conditions))
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = (await db.execute(count_query)).scalar() or 0

        offset = (page - 1) * limit
        query = query.order_by(db_models.Dialog.created_at.desc())
        query = query.offset(offset).limit(limit)

        result = await db.execute(query)
        dialogs = result.scalars().unique().all()

        items = []
        for dialog in dialogs:
            has_analysis = bool(dialog.analyses)
            overall_score = None
            if has_analysis:
                overall_score = dialog.analyses[0].scores.get('overall')

            company_id = getattr(dialog, 'company_id', None)
            items.append({
                "id": str(dialog.id),
                "filename": dialog.filename,
                "duration": dialog.duration,
                "status": dialog.status,
                "language": dialog.language,
                "seller_name": getattr(dialog, 'seller_name', None),
                "company_id": str(company_id) if company_id else None,
                "created_at": dialog.created_at.isoformat(),
                "has_analysis": has_analysis,
                "overall_score": overall_score,
            })

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            per_page=limit,
            total_pages=(total + limit - 1) // limit
        )

    except Exception as e:
        logger.error(f"Failed to get dialogs: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки диалогов: {str(e)}")


@router.get("/debug/zai-last")
async def get_zai_debug_last():
    """Return the last z.ai diarization debug info (in-memory, dev only)."""
    data = get_last_zai_debug()
    if data is None:
        return {"message": "No z.ai debug data yet. Transcribe a dialog first."}
    return data


@router.get("/{dialog_id}", response_model=DialogDetail)
async def get_dialog_detail(
    dialog_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth)
) -> DialogDetail:
    """
    Retrieve complete dialog details including transcription and analysis.

    User must have access to the dialog.
    """
    try:
        # Get user's organization IDs
        org_ids = await get_user_org_ids(user, db)

        try:
            dialog_uuid = UUID(dialog_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid dialog ID format")

        query = select(db_models.Dialog).where(
            db_models.Dialog.id == dialog_uuid
        ).options(
            selectinload(db_models.Dialog.transcriptions),
            selectinload(db_models.Dialog.analyses),
            selectinload(db_models.Dialog.company),
        )

        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if not dialog:
            raise HTTPException(status_code=404, detail="Dialog not found")

        # Check access
        if not dialog.is_accessible_by_user(user.id, org_ids):
            raise HTTPException(status_code=403, detail="Access denied to this dialog")

        segments = []
        if dialog.transcriptions:
            transcription = dialog.transcriptions[0]
            for segment_data in transcription.segments:
                segments.append({
                    "start": segment_data.get("start", 0),
                    "end": segment_data.get("end", 0),
                    "text": segment_data.get("text", ""),
                    "speaker": segment_data.get("speaker", "SPEAKER_00")
                })

        analysis = None
        if dialog.analyses:
            analysis_data = dialog.analyses[0]
            analysis = DialogAnalysisResponse(
                scores=analysis_data.scores,
                status=dialog.status,
                key_moments=analysis_data.key_moments,
                recommendations=analysis_data.recommendations,
                summary=analysis_data.summary,
                speaking_time=analysis_data.speaking_time,
                confidence=0.85,
                reasoning="Analysis completed successfully",
                created_at=analysis_data.created_at
            )

        company = getattr(dialog, 'company', None)
        return DialogDetail(
            id=str(dialog.id),
            filename=dialog.filename,
            duration=dialog.duration,
            status=dialog.status,
            language=dialog.language,
            seller_name=getattr(dialog, 'seller_name', None),
            company_id=str(dialog.company_id) if getattr(dialog, 'company_id', None) else None,
            company_name=company.name if company else None,
            created_at=dialog.created_at,
            transcription=dialog.transcriptions[0].text if dialog.transcriptions else None,
            segments=segments,
            analysis=analysis
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get dialog {dialog_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve dialog: {str(e)}")


@router.delete("/{dialog_id}", status_code=204)
async def delete_dialog(
    dialog_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth)
) -> None:
    """
    Delete a dialog and all associated data.

    User must have access to the dialog.
    """
    try:
        # Get user's organization IDs
        org_ids = await get_user_org_ids(user, db)

        try:
            dialog_uuid = UUID(dialog_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid dialog ID format")

        query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if not dialog:
            raise HTTPException(status_code=404, detail="Dialog not found")

        # Check access
        if not dialog.is_accessible_by_user(user.id, org_ids):
            raise HTTPException(status_code=403, detail="Access denied to this dialog")

        if dialog.file_path:
            file_path = Path(dialog.file_path)
            if file_path.exists():
                file_path.unlink()

        await db.delete(dialog)
        await db.commit()

        logger.info(f"Deleted dialog {dialog_id}")
        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete dialog {dialog_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete dialog: {str(e)}")


@router.put("/{dialog_id}/status", response_model=dict)
async def update_dialog_status(
    dialog_id: str,
    status_update: DialogStatusUpdate,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """Manually update dialog status."""
    try:
        try:
            dialog_uuid = UUID(dialog_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid dialog ID format")

        valid_statuses = ["pending", "processing", "failed", "dealed", "in_progress", "rejected"]
        if status_update.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )

        query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if not dialog:
            raise HTTPException(status_code=404, detail="Dialog not found")

        dialog.status = status_update.status
        await db.commit()

        logger.info(f"Updated dialog {dialog_id} status to {status_update.status}")

        return {
            "message": "Status updated successfully",
            "dialog_id": dialog_id,
            "new_status": status_update.status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update status for dialog {dialog_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Status update failed: {str(e)}")


# ---------------------------------------------------------------------------
# Timeline and Audio endpoints
# ---------------------------------------------------------------------------

@router.get("/{dialog_id}/timeline")
async def get_dialog_timeline(
    dialog_id: str,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Retrieve timeline data for visualization."""
    try:
        try:
            dialog_uuid = UUID(dialog_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid dialog ID format")

        query = select(db_models.Dialog).where(
            db_models.Dialog.id == dialog_uuid
        ).options(
            selectinload(db_models.Dialog.transcriptions),
            selectinload(db_models.Dialog.analyses)
        )

        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if not dialog:
            raise HTTPException(status_code=404, detail="Dialog not found")

        timeline = []
        if dialog.transcriptions:
            transcription = dialog.transcriptions[0]
            for segment_data in transcription.segments:
                timeline.append({
                    "id": f"seg_{len(timeline)}",
                    "type": "segment",
                    "start": segment_data.get("start", 0),
                    "end": segment_data.get("end", 0),
                    "text": segment_data.get("text", ""),
                    "speaker": segment_data.get("speaker", "SPEAKER_00"),
                    "duration": segment_data.get("end", 0) - segment_data.get("start", 0)
                })

        key_moments = []
        if dialog.analyses:
            analysis = dialog.analyses[0]
            for moment in (analysis.key_moments or []):
                key_moments.append({
                    "id": f"km_{len(key_moments)}",
                    "type": "key_moment",
                    "time": moment.get("time", 0),
                    "text": moment.get("text", ""),
                    "category": moment.get("type", "general")
                })

        return {
            "dialog_id": str(dialog.id),
            "duration": dialog.duration,
            "segments": timeline,
            "key_moments": key_moments,
            "speakers": list(set([s["speaker"] for s in timeline]))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get timeline for dialog {dialog_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve timeline: {str(e)}")


@router.get("/{dialog_id}/audio")
async def get_dialog_audio(
    dialog_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Stream audio file for the dialog."""
    try:
        try:
            dialog_uuid = UUID(dialog_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid dialog ID format")

        query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        result = await db.execute(query)
        dialog = result.scalar_one_or_none()

        if not dialog or not dialog.file_path:
            raise HTTPException(status_code=404, detail="Audio file not found")

        file_path = Path(dialog.file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Audio file not found on disk")

        # Determine media type from extension
        ext = file_path.suffix.lower()
        media_types = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.m4a': 'audio/mp4',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac',
            '.mp4': 'video/mp4',
            '.webm': 'audio/webm',
        }
        media_type = media_types.get(ext, 'audio/mpeg')

        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=dialog.filename
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve audio for dialog {dialog_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to serve audio: {str(e)}")


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

async def process_transcription_and_analysis(
    task_id: str,
    file_path: str,
    language: Optional[str],
    db: AsyncSession
):
    """Background task to process transcription and LLM analysis."""
    dialog = None
    try:
        dialog_uuid = UUID(task_id)
        dialog_query = select(db_models.Dialog).where(db_models.Dialog.id == dialog_uuid)
        dialog_result = await db.execute(dialog_query)
        dialog = dialog_result.scalar_one_or_none()

        if not dialog:
            logger.error(f"Dialog {task_id} not found for processing")
            return

        dialog.status = "processing"
        await db.commit()

        # Perform transcription (returns dict)
        service = get_whisper_service()
        transcription_result = service.transcribe(file_path, language=language, with_speakers=True)

        # Save transcription to DB
        transcription = db_models.Transcription(
            dialog_id=dialog_uuid,
            text=transcription_result["text"],
            language=transcription_result["language"],
            language_probability=transcription_result["language_probability"],
            segments=[
                {
                    "start": s["start"],
                    "end": s["end"],
                    "text": s["text"],
                    "speaker": s.get("speaker", "SPEAKER_00")
                } for s in transcription_result["segments"]
            ]
        )

        db.add(transcription)

        # Perform LLM analysis if available
        analysis = None
        llm = get_llm_analyzer()
        if llm:
            try:
                segment_objects = [
                    Segment(
                        start=s["start"],
                        end=s["end"],
                        text=s["text"],
                        speaker=s.get("speaker", "SPEAKER_00")
                    ) for s in transcription_result["segments"]
                ]
                analysis_result = await llm.analyze_dialog(segments=segment_objects)

                analysis = db_models.DialogAnalysis(
                    dialog_id=dialog_uuid,
                    scores=analysis_result.scores,
                    key_moments=analysis_result.key_moments,
                    recommendations=analysis_result.recommendations,
                    summary=analysis_result.summary,
                    speaking_time=analysis_result.speaking_time
                )

                db.add(analysis)
            except Exception as e:
                logger.error(f"Analysis failed for dialog {task_id}: {e}")

        # Set status from AI analysis (dealed/in_progress/rejected)
        # Fall back to "in_progress" if analysis didn't provide a status
        if analysis and hasattr(analysis_result, 'status') and analysis_result.status in ('dealed', 'in_progress', 'rejected'):
            dialog.status = analysis_result.status
        else:
            dialog.status = "in_progress"
        await db.commit()
        logger.info(f"Completed processing for dialog {task_id}, status={dialog.status}")

    except Exception as e:
        logger.error(f"Background task failed for {task_id}: {e}")
        try:
            if dialog:
                dialog.status = "failed"
                await db.commit()
        except Exception:
            pass
