"""
Companies API Router.

CMP-001..CMP-005  CSV Import
CMP-010..CMP-013  Company CRUD / list / card
CMP-021           Link/relink company from dialog card
CMP-022           Auto-suggest company from transcript (LLM)
"""

import base64
import csv
import io
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import Float, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth.dependencies import require_auth, get_current_organization
from ..auth.models import Membership, User
from ..auth.dependencies import OrganizationContext
from ..config import AUTH_ENABLED
from ..database import models as db_models
from ..database.connection import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["companies"])

# ─────────────────────────────────────────────
# System field names (used in mapping)
# ─────────────────────────────────────────────
SYSTEM_FIELDS = [
    "name",           # обязательное
    "inn",
    "contact_person",
    "phone",
    "email",
    "address",
    "responsible",
    "custom_1",
    "custom_2",
    "custom_3",
    "custom_4",
    "custom_5",
    # special: skip
    "__skip__",
]

# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    inn: Optional[str] = Field(None, max_length=20)
    external_id: Optional[str] = Field(None, max_length=255)
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    responsible: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=255)
    funnel_stage: Optional[str] = Field(None, max_length=100)
    custom_fields: Optional[Dict[str, str]] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    inn: Optional[str] = Field(None, max_length=20)
    external_id: Optional[str] = Field(None, max_length=255)
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    responsible: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=255)
    funnel_stage: Optional[str] = Field(None, max_length=100)
    custom_fields: Optional[Dict[str, str]] = None


class CompanyResponse(BaseModel):
    id: str
    name: str
    inn: Optional[str] = None
    external_id: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    funnel_stage: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    meetings_count: int = 0
    last_meeting_date: Optional[str] = None
    avg_score: Optional[float] = None
    created_at: str

    class Config:
        from_attributes = True


class SaveMappingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    mapping: Dict[str, str]  # {csv_column: system_field}


class ImportProcessRequest(BaseModel):
    file_content: str = Field(..., description="Base64-encoded CSV content")
    encoding: str = Field(default="utf-8", description="File encoding: utf-8 or cp1251")
    mapping: Dict[str, str] = Field(..., description="{csv_column: system_field}")
    duplicate_action: str = Field(
        default="skip",
        description="Action for duplicates: update | skip | create_new"
    )
    # Per-duplicate overrides: {row_index_str: action}
    duplicate_overrides: Optional[Dict[str, str]] = None


# ─────────────────────────────────────────────
# Helper: ownership filter
# ─────────────────────────────────────────────

async def _get_owner_filter(user: User, db: AsyncSession, active_org_id=None):
    """Return SQLAlchemy conditions to filter companies by ownership.
    If active_org_id is provided, filter by that single org only.
    """
    if not AUTH_ENABLED:
        return []

    if active_org_id:
        return [
            and_(
                db_models.Company.owner_type == "organization",
                db_models.Company.owner_id == active_org_id,
            )
        ]

    result = await db.execute(
        select(Membership.organization_id).where(
            and_(Membership.user_id == user.id, Membership.is_active == True)
        )
    )
    org_ids = [r[0] for r in result.all()]

    conds = [
        db_models.Company.owner_type.is_(None),
        and_(db_models.Company.owner_type == "user", db_models.Company.owner_id == user.id),
    ]
    if org_ids:
        conds.append(
            and_(
                db_models.Company.owner_type == "organization",
                db_models.Company.owner_id.in_(org_ids),
            )
        )
    return conds


async def _get_user_owner(user: User, db: AsyncSession, active_org_id=None) -> tuple:
    """Return (owner_type, owner_id) for a new company."""
    if not AUTH_ENABLED:
        return None, None

    if active_org_id:
        return "organization", active_org_id

    # Prefer first active organization the user belongs to
    result = await db.execute(
        select(Membership.organization_id).where(
            and_(Membership.user_id == user.id, Membership.is_active == True)
        ).limit(1)
    )
    row = result.fetchone()
    if row:
        return "organization", row[0]
    return "user", user.id


def _serialize_company(c: db_models.Company, meetings_count=0,
                        last_meeting_date=None, avg_score=None) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "inn": c.inn,
        "external_id": c.external_id,
        "contact_person": c.contact_person,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "responsible": c.responsible,
        "industry": c.industry,
        "funnel_stage": c.funnel_stage,
        "custom_fields": c.custom_fields,
        "meetings_count": meetings_count,
        "last_meeting_date": last_meeting_date,
        "avg_score": avg_score,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ─────────────────────────────────────────────
# CMP-012  Create company manually
# ─────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_company(
    payload: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_type, owner_id = await _get_user_owner(user, db, active_org_id)
    company = db_models.Company(
        owner_type=owner_type,
        owner_id=owner_id,
        created_by=user.id if AUTH_ENABLED else None,
        name=payload.name,
        inn=payload.inn,
        external_id=payload.external_id,
        contact_person=payload.contact_person,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        responsible=payload.responsible,
        industry=payload.industry,
        funnel_stage=payload.funnel_stage,
        custom_fields=payload.custom_fields,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return _serialize_company(company)


# ─────────────────────────────────────────────
# CMP-010  List companies
# ─────────────────────────────────────────────

@router.get("/")
async def list_companies(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search in name, INN, contact"),
    industry: Optional[str] = Query(None),
    funnel_stage: Optional[str] = Query(None),
    sort_by: str = Query("created_at", description="name|created_at|meetings_count|avg_score"),
    sort_dir: str = Query("desc", description="asc|desc"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_conds = await _get_owner_filter(user, db, active_org_id)
    conditions = []
    if owner_conds:
        conditions.append(or_(*owner_conds))

    if search:
        like = f"%{search}%"
        conditions.append(
            or_(
                db_models.Company.name.ilike(like),
                db_models.Company.inn.ilike(like),
                db_models.Company.contact_person.ilike(like),
                db_models.Company.email.ilike(like),
            )
        )
    if industry:
        conditions.append(db_models.Company.industry.ilike(f"%{industry}%"))
    if funnel_stage:
        conditions.append(db_models.Company.funnel_stage == funnel_stage)

    where_clause = and_(*conditions) if conditions else True

    # Count
    total = (await db.execute(
        select(func.count(db_models.Company.id)).where(where_clause)
    )).scalar() or 0

    # Query with meeting stats via subquery
    meetings_subq = (
        select(
            db_models.Dialog.company_id,
            func.count(db_models.Dialog.id).label("meetings_count"),
            func.max(db_models.Dialog.created_at).label("last_meeting"),
        )
        .where(db_models.Dialog.company_id.isnot(None))
        .group_by(db_models.Dialog.company_id)
        .subquery()
    )

    score_subq = (
        select(
            db_models.Dialog.company_id,
            func.avg(
                func.cast(
                    db_models.DialogAnalysis.scores["overall"].astext,
                    Float,
                )
            ).label("avg_score"),
        )
        .join(db_models.DialogAnalysis, db_models.Dialog.id == db_models.DialogAnalysis.dialog_id)
        .where(db_models.Dialog.company_id.isnot(None))
        .group_by(db_models.Dialog.company_id)
        .subquery()
    )

    q = (
        select(
            db_models.Company,
            func.coalesce(meetings_subq.c.meetings_count, 0).label("meetings_count"),
            meetings_subq.c.last_meeting,
            score_subq.c.avg_score,
        )
        .outerjoin(meetings_subq, db_models.Company.id == meetings_subq.c.company_id)
        .outerjoin(score_subq, db_models.Company.id == score_subq.c.company_id)
        .where(where_clause)
    )

    # Sorting
    sort_map = {
        "name": db_models.Company.name,
        "created_at": db_models.Company.created_at,
        "meetings_count": func.coalesce(meetings_subq.c.meetings_count, 0),
        "avg_score": score_subq.c.avg_score,
    }
    sort_col = sort_map.get(sort_by, db_models.Company.created_at)
    q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    q = q.offset((page - 1) * limit).limit(limit)

    rows = (await db.execute(q)).all()

    items = []
    for row in rows:
        c, cnt, last_dt, avg = row
        items.append(_serialize_company(
            c,
            meetings_count=cnt or 0,
            last_meeting_date=last_dt.isoformat() if last_dt else None,
            avg_score=round(float(avg), 1) if avg is not None else None,
        ))

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": limit,
        "total_pages": max(1, (total + limit - 1) // limit),
    }


# ─────────────────────────────────────────────
# Autocomplete search (CMP-021)
# ─────────────────────────────────────────────

@router.get("/search")
async def search_companies(
    q: str = Query("", description="Search query"),
    limit: int = Query(10, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_conds = await _get_owner_filter(user, db, active_org_id)
    conditions = []
    if owner_conds:
        conditions.append(or_(*owner_conds))
    if q:
        like = f"%{q}%"
        conditions.append(
            or_(
                db_models.Company.name.ilike(like),
                db_models.Company.inn.ilike(like),
            )
        )
    where_clause = and_(*conditions) if conditions else True
    result = await db.execute(
        select(db_models.Company.id, db_models.Company.name, db_models.Company.inn)
        .where(where_clause)
        .order_by(db_models.Company.name)
        .limit(limit)
    )
    return [
        {"id": str(r[0]), "name": r[1], "inn": r[2]}
        for r in result.all()
    ]


# ─────────────────────────────────────────────
# CMP-011  Company detail card
# ─────────────────────────────────────────────

@router.get("/{company_id}")
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    try:
        cid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid company ID")

    owner_conds = await _get_owner_filter(user, db)
    conds = [db_models.Company.id == cid]
    if owner_conds:
        conds.append(or_(*owner_conds))

    c = (await db.execute(
        select(db_models.Company).where(and_(*conds))
    )).scalar_one_or_none()

    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    # Load meetings with analysis
    dialogs_q = (
        select(db_models.Dialog)
        .options(selectinload(db_models.Dialog.analyses))
        .where(db_models.Dialog.company_id == cid)
        .order_by(db_models.Dialog.created_at.desc())
    )
    dialogs = (await db.execute(dialogs_q)).scalars().all()

    meetings = []
    scores_by_date = []
    status_counts: Dict[str, int] = {}
    objections_raw: List[str] = []

    for d in dialogs:
        score = None
        if d.analyses:
            a = d.analyses[0]
            score = a.scores.get("overall") if a.scores else None
            scores_by_date.append({
                "date": d.created_at.strftime("%Y-%m-%d"),
                "score": score,
            })
            # Collect objections from key_moments
            for km in (a.key_moments or []):
                if isinstance(km, dict) and km.get("type") in ("objection", "возражение"):
                    objections_raw.append(km.get("text", ""))

        meetings.append({
            "id": str(d.id),
            "filename": d.filename,
            "status": d.status,
            "seller_name": d.seller_name,
            "overall_score": score,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    avg_score = None
    if scores_by_date:
        valid = [s["score"] for s in scores_by_date if s["score"] is not None]
        if valid:
            avg_score = round(sum(valid) / len(valid), 1)

    last_meeting_date = (
        dialogs[0].created_at.isoformat() if dialogs else None
    )

    return {
        **_serialize_company(c, len(meetings), last_meeting_date, avg_score),
        "meetings": meetings,
        "score_trend": scores_by_date,
        "status_counts": status_counts,
        "objections": list(set(objections_raw))[:20],
    }


# ─────────────────────────────────────────────
# CMP-013  Update company
# ─────────────────────────────────────────────

@router.put("/{company_id}")
async def update_company(
    company_id: str,
    payload: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    try:
        cid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid company ID")

    owner_conds = await _get_owner_filter(user, db)
    conds = [db_models.Company.id == cid]
    if owner_conds:
        conds.append(or_(*owner_conds))

    c = (await db.execute(select(db_models.Company).where(and_(*conds)))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    for field, val in payload.dict(exclude_unset=True).items():
        setattr(c, field, val)

    await db.commit()
    await db.refresh(c)
    return _serialize_company(c)


# ─────────────────────────────────────────────
# CMP-013  Delete company
# ─────────────────────────────────────────────

@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    try:
        cid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid company ID")

    owner_conds = await _get_owner_filter(user, db)
    conds = [db_models.Company.id == cid]
    if owner_conds:
        conds.append(or_(*owner_conds))

    c = (await db.execute(select(db_models.Company).where(and_(*conds)))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    # Dialogs remain but company_id is set to NULL by FK ON DELETE SET NULL
    await db.delete(c)
    await db.commit()


# ─────────────────────────────────────────────
# CMP-001  CSV Upload → preview
# ─────────────────────────────────────────────

def _decode_csv(raw: bytes) -> Tuple[str, str]:
    """Try UTF-8 then Windows-1251. Returns (decoded_text, encoding_used)."""
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    # Fallback: replace errors
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _parse_csv(text: str) -> Tuple[List[str], List[List[str]]]:
    """Return (headers, rows). Handles , and ; delimiters."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # default comma

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return [], []
    headers = [h.strip() for h in rows[0]]
    data = [[cell.strip() for cell in r] for r in rows[1:] if any(cell.strip() for cell in r)]
    return headers, data


@router.post("/import/upload")
async def import_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """
    CMP-001: Upload CSV, return preview + column names.
    Supports UTF-8 and Windows-1251 (1C exports).
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Ожидается CSV файл")

    raw = await file.read()

    MAX_SIZE = 10 * 1024 * 1024  # 10 MB guard
    if len(raw) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 10 МБ)")

    text, encoding = _decode_csv(raw)
    headers, rows = _parse_csv(text)

    if not headers:
        raise HTTPException(status_code=400, detail="CSV файл пуст или не содержит заголовков")

    if len(rows) > 10_000:
        raise HTTPException(status_code=400, detail="Файл содержит более 10 000 строк")

    preview = rows[:5]
    # Pad/truncate preview rows to header length
    normalized_preview = []
    for r in preview:
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        normalized_preview.append(r[:len(headers)])

    # Auto-guess mapping based on common column names
    auto_mapping = _auto_guess_mapping(headers)

    # Load saved mappings for this user
    saved = await _load_saved_mappings(user, db)

    return {
        "filename": file.filename,
        "encoding": encoding,
        "total_rows": len(rows),
        "headers": headers,
        "preview": normalized_preview,
        "auto_mapping": auto_mapping,
        "system_fields": SYSTEM_FIELDS,
        "saved_mappings": saved,
        # Return base64 content so client can submit for processing
        "file_content_b64": base64.b64encode(raw).decode(),
    }


def _auto_guess_mapping(headers: List[str]) -> Dict[str, str]:
    """Guess system field names from CSV column names (case-insensitive)."""
    guesses = {
        # name
        "название": "name", "наименование": "name", "компания": "name",
        "name": "name", "company": "name", "organization": "name",
        "организация": "name", "фирма": "name",
        # inn
        "инн": "inn", "inn": "inn", "tax_id": "inn",
        # contact
        "контакт": "contact_person", "контактное лицо": "contact_person",
        "contact": "contact_person", "contact_person": "contact_person",
        "фио": "contact_person",
        # phone
        "телефон": "phone", "phone": "phone", "тел": "phone",
        "тел.": "phone", "номер": "phone",
        # email
        "email": "email", "почта": "email", "e-mail": "email",
        # address
        "адрес": "address", "address": "address",
        # responsible
        "ответственный": "responsible", "ответственная": "responsible",
        "менеджер": "responsible", "продавец": "responsible",
        "responsible": "responsible", "manager": "responsible",
    }
    mapping = {}
    for h in headers:
        key = h.lower().strip()
        if key in guesses:
            mapping[h] = guesses[key]
        else:
            mapping[h] = "__skip__"
    return mapping


async def _load_saved_mappings(user: User, db: AsyncSession) -> List[dict]:
    """Return saved CSV import mappings for the user."""
    if not AUTH_ENABLED:
        result = await db.execute(
            select(db_models.CsvImportMapping)
            .where(db_models.CsvImportMapping.owner_type.is_(None))
            .order_by(db_models.CsvImportMapping.created_at.desc())
        )
    else:
        orgs_q = await db.execute(
            select(Membership.organization_id).where(
                and_(Membership.user_id == user.id, Membership.is_active == True)
            )
        )
        org_ids = [r[0] for r in orgs_q.all()]
        conds = [
            and_(db_models.CsvImportMapping.owner_type == "user",
                 db_models.CsvImportMapping.owner_id == user.id),
        ]
        if org_ids:
            conds.append(
                and_(db_models.CsvImportMapping.owner_type == "organization",
                     db_models.CsvImportMapping.owner_id.in_(org_ids))
            )
        result = await db.execute(
            select(db_models.CsvImportMapping)
            .where(or_(*conds))
            .order_by(db_models.CsvImportMapping.created_at.desc())
        )
    rows = result.scalars().all()
    return [{"id": str(r.id), "name": r.name, "mapping": r.mapping} for r in rows]


# ─────────────────────────────────────────────
# CMP-002  Save mapping
# ─────────────────────────────────────────────

@router.post("/import/mappings", status_code=201)
async def save_mapping(
    payload: SaveMappingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_type, owner_id = await _get_user_owner(user, db, active_org_id)
    m = db_models.CsvImportMapping(
        owner_type=owner_type,
        owner_id=owner_id,
        name=payload.name,
        mapping=payload.mapping,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return {"id": str(m.id), "name": m.name, "mapping": m.mapping}


@router.get("/import/mappings")
async def list_mappings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    return await _load_saved_mappings(user, db)


# ─────────────────────────────────────────────
# CMP-003 / CMP-004 / CMP-005  Process import
# ─────────────────────────────────────────────

@router.post("/import/process")
async def import_process(
    payload: ImportProcessRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    """
    Process CSV import with field mapping and duplicate handling.

    duplicate_action: "update" | "skip" | "create_new"
    duplicate_overrides: {row_index: action} for per-row override
    """
    try:
        raw = base64.b64decode(payload.file_content)
    except Exception:
        raise HTTPException(status_code=400, detail="Невалидный base64 контент файла")

    enc = payload.encoding if payload.encoding in ("utf-8", "cp1251", "utf-8-sig") else "utf-8"
    try:
        text = raw.decode(enc)
    except UnicodeDecodeError:
        text, _ = _decode_csv(raw)

    headers, rows = _parse_csv(text)
    if not headers or not rows:
        raise HTTPException(status_code=400, detail="CSV файл пуст")

    mapping = payload.mapping  # {csv_col: system_field}
    duplicate_action = payload.duplicate_action
    overrides = payload.duplicate_overrides or {}

    # Use active org from JWT so companies land in the right organisation
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_type, owner_id = await _get_user_owner(user, db, active_org_id)
    created_by = user.id if AUTH_ENABLED else None

    # Pre-load existing companies for dup detection scoped to active org only
    owner_conds = await _get_owner_filter(user, db, active_org_id)
    where = and_(*[or_(*owner_conds)]) if owner_conds else True
    existing_q = await db.execute(
        select(db_models.Company.id, db_models.Company.name, db_models.Company.inn)
        .where(where)
    )
    # {name_lower: id, inn: id}
    existing_by_name: Dict[str, uuid.UUID] = {}
    existing_by_inn: Dict[str, uuid.UUID] = {}
    for row in existing_q.all():
        eid, ename, einn = row
        if ename:
            existing_by_name[ename.lower()] = eid
        if einn:
            existing_by_inn[einn.strip()] = eid

    imported = 0
    updated = 0
    skipped = 0
    errors = []

    col_index = {h: i for i, h in enumerate(headers)}

    for row_idx, row_data in enumerate(rows):
        # Pad row
        if len(row_data) < len(headers):
            row_data = row_data + [""] * (len(headers) - len(row_data))

        # Build record dict from mapping
        record: Dict[str, str] = {}
        custom_fields: Dict[str, str] = {}
        for col, field in mapping.items():
            if field == "__skip__":
                continue
            idx = col_index.get(col)
            if idx is None:
                continue
            val = row_data[idx].strip()
            if not val:
                continue
            if field.startswith("custom_"):
                custom_fields[field] = val
            else:
                record[field] = val

        # Validate required field
        name = record.get("name", "").strip()
        if not name:
            errors.append({
                "row": row_idx + 2,  # +2 for 1-based + header
                "error": "Отсутствует обязательное поле: название компании",
                "data": row_data,
            })
            continue

        inn = record.get("inn", "").strip() or None

        # Detect duplicate
        dup_id: Optional[uuid.UUID] = None
        if inn and inn in existing_by_inn:
            dup_id = existing_by_inn[inn]
        elif name.lower() in existing_by_name:
            dup_id = existing_by_name[name.lower()]

        action = overrides.get(str(row_idx), duplicate_action) if dup_id else "create"

        if dup_id:
            if action == "skip":
                skipped += 1
                continue
            elif action == "create_new":
                dup_id = None  # force creation
            # else: "update" — fall through

        if dup_id:
            # Update existing
            c = (await db.execute(
                select(db_models.Company).where(db_models.Company.id == dup_id)
            )).scalar_one_or_none()
            if c:
                for f in ("name", "inn", "external_id", "contact_person",
                          "phone", "email", "address", "responsible",
                          "industry", "funnel_stage"):
                    v = record.get(f)
                    if v:
                        setattr(c, f, v)
                if custom_fields:
                    existing_cf = c.custom_fields or {}
                    existing_cf.update(custom_fields)
                    c.custom_fields = existing_cf
                updated += 1
                # Update lookup caches
                existing_by_name[name.lower()] = dup_id
                if inn:
                    existing_by_inn[inn] = dup_id
        else:
            # Create new
            c = db_models.Company(
                owner_type=owner_type,
                owner_id=owner_id,
                created_by=created_by,
                name=name,
                inn=inn,
                external_id=record.get("external_id"),
                contact_person=record.get("contact_person"),
                phone=record.get("phone"),
                email=record.get("email"),
                address=record.get("address"),
                responsible=record.get("responsible"),
                industry=record.get("industry"),
                funnel_stage=record.get("funnel_stage"),
                custom_fields=custom_fields or None,
            )
            db.add(c)
            imported += 1
            # Update lookup caches (after flush we'll have id)
            existing_by_name[name.lower()] = None  # placeholder
            if inn:
                existing_by_inn[inn] = None

    await db.commit()

    total_processed = imported + updated + skipped + len(errors)
    return {
        "total_rows": len(rows),
        "processed": total_processed,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors_count": len(errors),
        "errors": errors[:100],  # cap for response size
        "message": (
            f"Импортировано {imported}, обновлено {updated}, "
            f"пропущено {skipped}. "
            f"{'Ошибок: ' + str(len(errors)) + '.' if errors else ''}"
        ),
    }


# ─────────────────────────────────────────────
# CMP-021  Link / unlink company to dialog
# ─────────────────────────────────────────────

class LinkCompanyRequest(BaseModel):
    company_id: Optional[str] = None  # None = unlink


@router.patch("/link-dialog/{dialog_id}")
async def link_company_to_dialog(
    dialog_id: str,
    payload: LinkCompanyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Attach or detach a company from a dialog (CMP-021)."""
    try:
        did = UUID(dialog_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid dialog ID")

    dialog = (await db.execute(
        select(db_models.Dialog).where(db_models.Dialog.id == did)
    )).scalar_one_or_none()
    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")

    if payload.company_id:
        try:
            cid = UUID(payload.company_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid company ID")

        # Verify company ownership
        owner_conds = await _get_owner_filter(user, db)
        c_conds = [db_models.Company.id == cid]
        if owner_conds:
            c_conds.append(or_(*owner_conds))
        c = (await db.execute(
            select(db_models.Company).where(and_(*c_conds))
        )).scalar_one_or_none()
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        dialog.company_id = cid
        company_info = {"id": str(c.id), "name": c.name}
    else:
        dialog.company_id = None
        company_info = None

    await db.commit()
    return {"dialog_id": dialog_id, "company": company_info}


# ─────────────────────────────────────────────
# CMP-022  Auto-suggest company from transcript
# ─────────────────────────────────────────────

@router.get("/suggest/{dialog_id}")
async def suggest_company(
    dialog_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
    org_ctx: Optional[OrganizationContext] = Depends(get_current_organization),
):
    """
    CMP-022: Use LLM to extract company mentions from transcript,
    then match against user's companies database.
    Returns up to 3 suggestions with confidence scores.
    """
    try:
        did = UUID(dialog_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid dialog ID")

    # Load dialog + transcription
    dialog = (await db.execute(
        select(db_models.Dialog)
        .options(selectinload(db_models.Dialog.transcriptions))
        .where(db_models.Dialog.id == did)
    )).scalar_one_or_none()

    if not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")

    if not dialog.transcriptions:
        return {"suggestions": [], "message": "Транскрипция отсутствует"}

    transcript_text = dialog.transcriptions[0].text[:3000]  # cap for LLM

    # Extract mentions via LLM
    mentions = await _extract_company_mentions(transcript_text)

    if not mentions:
        return {"suggestions": [], "message": "Упоминания компаний не найдены"}

    # Load user's companies for matching
    active_org_id = org_ctx.organization.id if org_ctx else None
    owner_conds = await _get_owner_filter(user, db, active_org_id)
    where = or_(*owner_conds) if owner_conds else True
    companies = (await db.execute(
        select(db_models.Company.id, db_models.Company.name, db_models.Company.inn)
        .where(where)
        .limit(1000)
    )).all()

    suggestions = _match_companies(mentions, companies)

    return {"suggestions": suggestions[:3], "dialog_id": dialog_id}


async def _extract_company_mentions(text: str) -> List[str]:
    """Call LLM to extract company/organization names from transcript."""
    import os
    import aiohttp

    api_key = os.getenv("ZAI_API_KEY", "")
    if not api_key:
        # Fallback: simple heuristic keyword extraction
        return _heuristic_extract_companies(text)

    prompt = (
        "Из следующего текста переговоров извлеки все упоминания названий компаний, "
        "организаций, фирм и проектов. Верни только список названий в формате JSON-массива строк. "
        "Если компаний нет — верни пустой массив []. "
        "Пример ответа: [\"Альфа Системс\", \"Газпром\", \"ООО Ромашка\"] \n\n"
        f"Текст:\n{text}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                "https://api.z.ai/api/anthropic/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
            if resp.status != 200:
                return _heuristic_extract_companies(text)
            data = await resp.json()
            raw = data.get("content", [{}])[0].get("text", "[]")
            # Extract JSON array from response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
    except Exception as e:
        logger.warning(f"Company extraction LLM error: {e}")

    return _heuristic_extract_companies(text)


def _heuristic_extract_companies(text: str) -> List[str]:
    """Heuristic: find company names using common patterns."""
    import re
    patterns = [
        # Legal forms with name
        r'(?:ООО|АО|ЗАО|ОАО|ПАО|ИП|НКО|ГУП|МУП)\s+[«"]?([А-ЯЁA-Z][^"«»\n,\.]{1,50})[»"]?',
        # "компания X", "фирма X", "организация X"
        r'(?:компани[яию]|фирм[аы]|организаци[яию])\s+[«"]?([А-ЯЁA-Z][^"«»\n,\.]{1,50})[»"]?',
        # Quoted names
        r'«([^»]{2,50})»',
        r'"([^"]{2,50})"',
        # "из компании X", "от компании X", "в компании X"
        r'(?:из|от|в|с)\s+(?:компани[ияю]|фирмы|организации)\s+[«"]?([А-ЯЁA-Z][^"«»\n,\.]{1,50})[»"]?',
        # "представляю X", "работаю в X"
        r'(?:представляю|работаю в|работаем в|звоню из)\s+[«"]?([А-ЯЁA-Z][^"«»\n,\.]{1,50})[»"]?',
    ]
    found = []
    for p in patterns:
        found.extend(re.findall(p, text, re.IGNORECASE))
    # Clean up results
    cleaned = []
    for name in found:
        name = name.strip().rstrip('.')
        if len(name) >= 2 and name not in cleaned:
            cleaned.append(name)
    return cleaned[:10]


def _normalize_company_name(name: str) -> str:
    """Strip legal form prefixes/suffixes and normalize for matching."""
    import re
    n = name.lower().strip()
    # Remove quotes and brackets
    n = re.sub(r'[«»""\'"\(\)\[\]]', '', n)
    # Remove common legal forms
    legal_forms = [
        r'\bооо\b', r'\bоао\b', r'\bзао\b', r'\bпао\b', r'\bао\b',
        r'\bип\b', r'\bнко\b', r'\bгуп\b', r'\bмуп\b',
        r'\bllc\b', r'\binc\b', r'\bltd\b', r'\bgmbh\b',
        r'\bкомпания\b', r'\bфирма\b', r'\bгруппа\b', r'\bхолдинг\b',
    ]
    for form in legal_forms:
        n = re.sub(form, '', n)
    # Collapse whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _match_companies(mentions: List[str], companies) -> List[dict]:
    """Fuzzy match between LLM-extracted names and DB companies."""
    results = []
    for mention in mentions:
        m_lower = mention.lower().strip()
        m_norm = _normalize_company_name(mention)
        for cid, cname, cinn in companies:
            if not cname:
                continue
            cn_lower = cname.lower()
            cn_norm = _normalize_company_name(cname)

            score = 0.0

            # 1. Exact match (original)
            if m_lower == cn_lower:
                score = 1.0
            # 2. Exact match (normalized — strips ООО etc.)
            elif m_norm and cn_norm and m_norm == cn_norm:
                score = 0.95
            # 3. Substring match (original)
            elif m_lower in cn_lower or cn_lower in m_lower:
                score = 0.85
            # 4. Substring match (normalized)
            elif m_norm and cn_norm and (m_norm in cn_norm or cn_norm in m_norm):
                score = 0.8
            else:
                # 5. Token overlap (normalized)
                m_tokens = set(m_norm.split()) if m_norm else set()
                c_tokens = set(cn_norm.split()) if cn_norm else set()
                # Remove very short tokens (articles, etc.)
                m_tokens = {t for t in m_tokens if len(t) > 2}
                c_tokens = {t for t in c_tokens if len(t) > 2}
                overlap = m_tokens & c_tokens
                if overlap and len(overlap) / max(len(m_tokens), len(c_tokens), 1) >= 0.4:
                    score = 0.6
                else:
                    continue

            results.append({
                "company_id": str(cid),
                "company_name": cname,
                "mentioned_as": mention,
                "confidence": score,
            })

    # Deduplicate by company_id, keep highest score
    seen: Dict[str, dict] = {}
    for r in results:
        cid_str = r["company_id"]
        if cid_str not in seen or r["confidence"] > seen[cid_str]["confidence"]:
            seen[cid_str] = r

    return sorted(seen.values(), key=lambda x: x["confidence"], reverse=True)
