"""
SQLAlchemy models for VOICEcheck database.

This module defines the database schema for the VOICEcheck application,
including models for audio dialogs, transcriptions, and analyses.

Key features:
- UUID-based primary keys for better performance
- PostgreSQL-specific types (UUID, JSONB) for advanced functionality
- Automatic timestamp management with timezone awareness
- Cascade delete for data consistency
- Indexed queries for better performance
- Relationship mapping for ORM operations

Models:
- Dialog: Stores audio file metadata and processing status
- Transcription: Stores transcribed text with segments and speaker info
- DialogAnalysis: Stores analysis results with scores and recommendations
"""

from sqlalchemy import Column, String, DateTime, Float, Text, Integer, ForeignKey, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from typing import Optional



Base = declarative_base()


class Dialog(Base):
    """
    Модель для хранения метаданных аудио диалога.

    Основная модель для отслеживания состояния и метаданных
    каждого аудиофайла в системе.

    Когда FEATURE_FLAG_AUTH включен, диалоги могут принадлежать организациям
    или пользователям (полиморфная связь через owner_type и owner_id).

    Attributes:
        id: Уникальный идентификатор диалога (UUID)
        filename: Исходное имя аудиофайла
        duration: Длительность аудио в секундах
        status: Текущий статус обработки
        file_path: Путь к файлу в файловой системе
        language: Обнаруженный язык аудио
        owner_type: Тип владельца ('organization' или 'user' или None)
        owner_id: ID владельца (UUID организации или пользователя)
        created_by: ID пользователя, создавшего диалог
        created_at: Дата создания записи
        updated_at: Дата последнего обновления
    """
    __tablename__ = "dialogs"

    # Primary key with UUID for performance
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # File metadata
    filename = Column(String(255), nullable=False, index=True,
                     comment="Original audio filename")
    duration = Column(Float, nullable=False,
                     comment="Audio duration in seconds")
    file_path = Column(String(512), nullable=False,
                      comment="Path to audio file in filesystem")

    # Processing status
    status = Column(String(50), nullable=False, default="pending", index=True,
                    comment="Processing status: pending, processing, completed, failed")

    # Language detection
    language = Column(String(10), nullable=True,
                     comment="Detected language code (e.g., 'ru', 'en')")

    # Salesperson
    seller_name = Column(String(255), nullable=True, index=True,
                        comment="Salesperson name for filtering")

    # Organization/User ownership (for multi-tenancy when auth is enabled)
    # These fields are nullable for backward compatibility
    # When FEATURE_FLAG_AUTH=False, these remain NULL (legacy mode)
    owner_type = Column(String(50), nullable=True, index=True,
                       comment="Owner type: 'organization', 'user', or None (legacy)")
    owner_id = Column(UUID(as_uuid=True), nullable=True, index=True,
                     comment="Owner ID (organization_id or user_id when auth enabled)")
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True,
                        comment="User ID who created this dialog")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True,
                       comment="Record creation timestamp")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(),
                       comment="Record last update timestamp")

    # Company link (optional)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"),
                        nullable=True, index=True,
                        comment="Linked company (CRM)")

    # ORM relationships
    transcriptions = relationship("Transcription", back_populates="dialog",
                                 cascade="all, delete-orphan")
    analyses = relationship("DialogAnalysis", back_populates="dialog",
                           cascade="all, delete-orphan")
    company = relationship("Company", back_populates="dialogs")

    def belongs_to_organization(self, organization_id: Optional[uuid.UUID]) -> bool:
        """
        Check if dialog belongs to a specific organization.

        Args:
            organization_id: UUID of the organization to check

        Returns:
            True if dialog belongs to the organization, False otherwise
        """
        if organization_id is None:
            return self.owner_type is None  # Legacy mode match
        return (
            self.owner_type == "organization" and
            self.owner_id == organization_id
        )

    def is_owned_by_user(self, user_id: Optional[uuid.UUID]) -> bool:
        """
        Check if dialog is owned by a specific user.

        Args:
            user_id: UUID of the user to check

        Returns:
            True if dialog is owned by the user, False otherwise
        """
        if user_id is None:
            return self.owner_type is None
        return (
            self.owner_type == "user" and
            self.owner_id == user_id
        )

    def is_accessible_by_user(self, user_id: uuid.UUID, user_organization_ids: list) -> bool:
        """
        Check if dialog is accessible by a user.

        A dialog is accessible if:
        - It's owned by the user directly, OR
        - It's owned by an organization the user is a member of

        Args:
            user_id: UUID of the user
            user_organization_ids: List of organization IDs the user belongs to

        Returns:
            True if user can access this dialog, False otherwise
        """
        if self.owner_type is None:
            return True  # Legacy mode - accessible to all

        if self.owner_type == "user" and self.owner_id == user_id:
            return True

        if self.owner_type == "organization" and self.owner_id in user_organization_ids:
            return True

        return False


class Transcription(Base):
    """
    Модель для хранения результатов транскрипции аудиодиалога.

    Содержит полный текст транскрипции с детальной информацией
    о каждом сегменте речи, включая временные метки и метки спикеров.

    Attributes:
        id: Уникальный идентификатор транскрипции (UUID)
        dialog_id: ID связанного диалога
        text: Полный текст транскрипции
        language: Язык транскрипции
        language_probability: Уверенность в определении языка
        segments: Массив сегментов с таймкодами и спикерами
        created_at: Дата создания записи
    """
    __tablename__ = "transcriptions"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Foreign key to Dialog
    dialog_id = Column(UUID(as_uuid=True), ForeignKey("dialogs.id"),
                      nullable=False, index=True,
                      comment="Reference to parent dialog")

    # Transcription content
    text = Column(Text, nullable=False,
                  comment="Complete transcribed text")
    language = Column(String(10), nullable=False,
                     comment="Language code of transcription")
    language_probability = Column(Float,
                                 comment="Confidence score for language detection (0.0-1.0)")

    # Segments data
    segments = Column(JSONB, nullable=False,
                      comment="Array of transcription segments with timing and speaker info")

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       comment="Transcription creation timestamp")

    # Relationship
    dialog = relationship("Dialog", back_populates="transcriptions")


class DialogAnalysis(Base):
    """
    Модель для хранения результатов анализа аудиодиалога.

    Содержит комплексный анализ диалога с оценками по категориям,
    ключевыми моментами и рекомендациями.

    Attributes:
        id: Уникальный идентификатор анализа (UUID)
        dialog_id: ID связанного диалога
        scores: Оценки по 8 категориям качества
        key_moments: Ключевые моменты диалога
        recommendations: Рекомендации по улучшению
        speaking_time: Статистика времени речи
        created_at: Дата создания записи
    """
    __tablename__ = "dialog_analyses"

    # Primary key with unique constraint per dialog
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Foreign key to Dialog (one analysis per dialog)
    dialog_id = Column(UUID(as_uuid=True), ForeignKey("dialogs.id"),
                      nullable=False, unique=True, index=True,
                      comment="Reference to parent dialog (one-to-one relationship)")

    # Analysis results (stored as JSONB for flexible data structure)
    scores = Column(JSONB, nullable=False,
                    comment="Quality scores across 8 categories")
    key_moments = Column(JSONB, nullable=False,
                        comment="Important moments in the dialog")
    recommendations = Column(JSONB, nullable=False,
                           comment="Recommendations for improvement")
    summary = Column(Text, nullable=True,
                     comment="Brief dialogue summary (2-3 sentences)")
    speaking_time = Column(JSONB, nullable=False,
                          comment="Speaking time statistics")

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       comment="Analysis creation timestamp")

    # Relationship
    dialog = relationship("Dialog", back_populates="analyses")


class Company(Base):
    """
    Модель компании (CRM-контакт).

    Хранит информацию о компаниях-клиентах с привязкой к организации-владельцу.
    Может быть создана вручную или импортирована из CSV.

    Attributes:
        id: UUID компании
        owner_type: Тип владельца ('organization'|'user'|None)
        owner_id: ID владельца
        created_by: ID пользователя, создавшего запись
        name: Название компании (обязательное)
        inn: ИНН (российский налоговый идентификатор)
        external_id: ID во внешней системе (1С и т.п.)
        contact_person: Контактное лицо
        phone: Телефон
        email: Email
        address: Адрес
        industry: Отрасль
        funnel_stage: Этап воронки
        custom_fields: Произвольные поля (JSONB, до 5 ключей)
    """
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Multi-tenancy ownership
    owner_type = Column(String(50), nullable=True, index=True,
                        comment="Owner type: 'organization'|'user'|None")
    owner_id = Column(UUID(as_uuid=True), nullable=True, index=True,
                      comment="Owner ID")
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True,
                        comment="User who created this company")

    # Core fields
    name = Column(String(255), nullable=False, index=True)
    inn = Column(String(20), nullable=True, index=True,
                 comment="Russian tax ID (ИНН)")
    external_id = Column(String(255), nullable=True, index=True,
                         comment="ID in external system (e.g. 1C)")
    contact_person = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    responsible = Column(String(255), nullable=True,
                         comment="Responsible seller name")
    industry = Column(String(255), nullable=True)
    funnel_stage = Column(String(100), nullable=True)
    custom_fields = Column(JSONB, nullable=True,
                           comment="Up to 5 custom fields {key: value}")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    dialogs = relationship("Dialog", back_populates="company")


class CsvImportMapping(Base):
    """
    Сохранённый маппинг колонок CSV для повторного импорта.

    Позволяет запоминать соответствие колонок CSV полям системы
    для конкретной организации/пользователя.
    """
    __tablename__ = "csv_import_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_type = Column(String(50), nullable=True, index=True)
    owner_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    name = Column(String(255), nullable=False,
                  comment="Mapping name (e.g. 'Из 1С-Бухгалтерии')")
    mapping = Column(JSONB, nullable=False,
                     comment="Column mapping: {csv_column_name: system_field_name}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

