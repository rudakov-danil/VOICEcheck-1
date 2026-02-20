# VOICEcheck - Архитектура системы

## Обзор

VOICEcheck - веб-приложение для транскрибации аудиодиалогов с AI-анализом качества продаж.

```
┌─────────────────────────────────────────────────────────────────────┐
│                            USER BROWSER                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────────┐  │
│  │   Upload    │  │   History   │  │      Evaluation           │  │
│  │    Page     │  │    Page     │  │        Page               │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬───────────────┘  │
│         │                │                     │                   │
│         └────────────────┴─────────────────────┘                   │
│                           │                                         │
└───────────────────────────┼─────────────────────────────────────────┘
                            │ HTTP/JSON
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FASTAPI APPLICATION                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      API Layer (main.py)                     │  │
│  │  POST /api/dialogs  GET /api/dialogs  GET /api/dialogs/{id} │  │
│  └───────────────────────┬──────────────────────────────────────┘  │
│                          │                                          │
│  ┌───────────────────────┴──────────────────────────────────────┐  │
│  │                    Business Logic Layer                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │  │
│  │  │ Transcriber  │  │ LLMAnalyzer  │  │    Exporter      │   │  │
│  │  │   Service    │  │    (z.ai)    │  │  (PDF/DOCX)      │   │  │
│  │  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │  │
│  └─────────┼─────────────────┼──────────────────┼──────────────┘  │
│            │                 │                  │                 │
└────────────┼─────────────────┼──────────────────┼─────────────────┘
             │                 │                  │
             │                 │                  │
    ┌────────▼────────┐   ┌───▼──────┐    ┌──────▼───────┐
    │  Deepgram API   │   │ z.ai API │    │ ReportLab/   │
    │   (Whisper)     │   │ (Claude) │    │ python-docx  │
    │  + pyannote     │   │          │    │              │
    │   (diarization) │   │          │    │              │
    └─────────────────┘   └──────────┘    └──────────────┘
             │
    ┌────────▼────────┐
    │  PostgreSQL DB  │
    │  ┌────────────┐ │
    │  │  Dialog   │ │
    │  │  Transcr  │ │
    │  │ Analysis  │ │
    │  └───────────┘ │
    └────────────────┘
```

## Компоненты системы

### 1. Frontend Layer

**Стек:** Vanilla HTML5, JavaScript (ES6+), CSS3

**Страницы:**
```
/ (index.html)
├── Upload form (drag & drop)
├── Language selector
├── Progress indicator
└── Transcription result

/dialogs
├── Tab navigation
├── Dialogs list (table/cards)
├── Filters (status, dates, search)
├── Pagination
└── Actions (view, delete)

/dialogs/{id}/evaluate
├── Header (filename, date, duration)
├── Transcription (with speaker labels)
├── Scores (8 categories, 0-10)
├── Deal status badge
├── Speaking time chart (pie)
├── Key moments timeline
└── Recommendations
```

**JavaScript модули:**
- `app.js` - главная логика загрузки
- `dialogs.js` - история диалогов
- `evaluation.js` - страница оценки
- `api.js` - HTTP клиент (fetch wrapper)
- `chart.js` - визуализация данных

**Библиотеки:**
- Chart.js - графики
- html2pdf.js - экспорт в PDF

### 2. Backend Layer

**Стек:** Python 3.11, FastAPI, SQLAlchemy 2.0

**Структура:**
```
app/
├── main.py                 # FastAPI app, middleware
├── database.py             # DB connection, session
├── models.py               # Pydantic + SQLAlchemy models
├── transcriber.py          # Whisper + Diarization service
├── llm_analyzer.py         # LLM analysis service
├── prompts.py              # LLM prompts
├── export.py               # PDF/DOCX generation
├── routers/
│   └── dialogs.py          # Dialog endpoints
└── tests/
    ├── test_transcriber.py
    ├── test_llm_analyzer.py
    ├── test_api.py
    └── test_database.py
```

**API Endpoints:**

```
POST   /api/dialogs
       Загрузить аудио, транскрибировать, проанализировать
       Input: multipart/form-data (file, language?)
       Output: DialogResponse

GET    /api/dialogs
       Получить список диалогов
       Query: page, limit, status, date_from, date_to, search
       Output: PaginatedDialogList

GET    /api/dialogs/{id}
       Получить полный диалог
       Output: DialogDetail (transcription + analysis)

PUT    /api/dialogs/{id}/status
       Изменить статус сделки
       Input: {"status": "dealed"|"in_progress"|"rejected"}
       Output: DialogStatus

DELETE /api/dialogs/{id}
       Удалить диалог
       Output: {"message": "deleted"}

GET    /api/dialogs/{id}/export
       Экспорт в PDF/DOCX
       Query: format=pdf|docx
       Output: File download
```

### 3. AI/ML Layer

**DeepgramService (transcriber.py)**
```python
class DeepgramService:
    def transcribe(file_path, language) -> Transcription
    def transcribe_with_speakers(file_path) -> TranscriptionWithSpeakers
    def detect_roles(segments) -> SpeakerRoles
```

**Компоненты:**
- Deepgram API: транскрибация (Whisper модель)
- pyannote.audio: speaker diarization (опционально)
- Ролевая детекция: определение продавца/клиента

**LLMAnalyzer (llm_analyzer.py)**
```python
class LLMAnalyzer:
    async def analyze_dialog(transcription, segments) -> DialogAnalysis:
        # Вызывает z.ai через MCP
        # Промпты: скоринг, моменты, рекомендации
```

**Промпты (prompts.py):**
- SCORING_PROMPT: анализ 8 категорий
- MOMENTS_PROMPT: извлечение ключевых моментов
- RECOMMENDATIONS_PROMPT: генерация советов
- STATUS_PROMPT: определение статуса сделки

**Выход LLM:**
```json
{
  "scores": {
    "greeting": 8,
    "needs_discovery": 7,
    "presentation": 6,
    "objection_handling": 9,
    "closing": 5,
    "active_listening": 8,
    "empathy": 7,
    "overall": 7.1
  },
  "status": "in_progress",
  "key_moments": [
    {"type": "objection", "time": 120, "text": "Дорого"},
    {"type": "interest", "time": 180, "text": "Интересно"}
  ],
  "recommendations": [
    {"text": "Улучшить закрытие", "time_range": [300, 350]}
  ],
  "speaking_time": {
    "sales": 45.2,
    "customer": 54.8
  }
}
```

### 4. Data Layer

**PostgreSQL Schema:**
```sql
CREATE TABLE dialogs (
    id UUID PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    duration FLOAT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'in_progress',
    file_path VARCHAR(500)
);

CREATE TABLE transcriptions (
    dialog_id UUID REFERENCES dialogs(id),
    text TEXT NOT NULL,
    language VARCHAR(10),
    segments JSONB NOT NULL,
    PRIMARY KEY (dialog_id)
);

CREATE TABLE dialog_analyses (
    dialog_id UUID REFERENCES dialogs(id),
    scores JSONB NOT NULL,
    key_moments JSONB,
    recommendations JSONB,
    speaking_time JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (dialog_id)
);

CREATE INDEX idx_dialogs_created ON dialogs(created_at DESC);
CREATE INDEX idx_dialogs_status ON dialogs(status);
```

**Connection Pool:**
```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=15,
    pool_pre_ping=True
)
```

## Data Flow

### Flow 1: Создание диалога

```
1. User uploads audio
   └─> POST /api/dialogs
       ├─> Save file to /app/uploads
       ├─> Create Dialog record (status=processing)
       └─> Return dialog_id

2. Background processing
   ├─> DeepgramService.transcribe_with_speakers()
   │   ├─> Deepgram API: текст + сегменты
   │   └─> pyannote: speaker labels (опционально)
   ├─> Save Transcription record
   ├─> LLMAnalyzer.analyze_dialog()
   │   └─> z.ai API: анализ
   ├─> Save DialogAnalysis record
   └─> Update Dialog status

3. User polls or receives result
   └─> GET /api/dialogs/{id}
       └─> Return full dialog
```

### Flow 2: Просмотр истории

```
1. User opens /dialogs
   └─> GET /api/dialogs?page=1&limit=20
       └─> PostgreSQL query with pagination
       └─> Return dialogs list

2. User filters by status
   └─> GET /api/dialogs?status=dealed
       └─> Filtered query

3. User opens dialog
   └─> GET /api/dialogs/{id}
       └─> Join Dialog + Transcription + Analysis
       └─> Return full detail
```

### Flow 3: Экспорт

```
1. User clicks "Export PDF"
   └─> GET /api/dialogs/{id}/export?format=pdf

2. Backend generates PDF
   ├─> Fetch Dialog + Transcription + Analysis
   ├─> ReportLab: render PDF
   ├─> Cache generated file (TTL=1h)
   └─> Return file stream

3. Browser downloads file
   └─> {original_filename}_analysis.pdf
```

## Scaling Considerations

### Текущие ограничения (MVP)
- Single instance FastAPI
- CPU-based inference (no GPU)
- In-memory caching
- Direct DB connection

### Пути масштабирования

**Горизонтальное:**
```yaml
# docker-compose.yml (scaled)
services:
  voicecheck:
    deploy:
      replicas: 3
    environment:
      REDIS_URL: redis://redis:6379

  nginx:
    # Load balancer

  redis:
    # Session storage + cache

  postgres:
    # Shared storage
```

**Вертикальное:**
- GPU для Whisper (CUDA)
- GPU для LLM inference
- Увеличение RAM для моделей

**Оптимизации:**
- Async LLM calls (concurrent)
- Queue system (Celery/Redis)
- CDN для статики
- DB read replicas

## Security

### Текущая (MVP)
- CORS ограничен
- Max file size: 50MB
- Валидация расширений

### Будущие улучшения
- JWT authentication
- Rate limiting
- File content validation
- HTTPS only
- API key management
- Audit logging

## Monitoring

### Логи
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger.info(f"Task {task_id} completed")
logger.error(f"LLM API error: {e}")
```

### Метрики (будущее)
- API response times
- LLM call duration
- Transcription duration
- Error rates
- DB query times

### Health Checks
```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "db": check_db_connection(),
        "llm": check_llm_connection(),
        "whisper": check_whisper_loaded()
    }
```

## Deployment

### Docker Compose (Development)
```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```

### Production (future)
- Kubernetes deployment
- CI/CD pipeline
- Blue-green deployment
- Auto-scaling
- Backup/restore

---

**Документ обновлен:** 2025-02-16
**Версия:** 1.0
