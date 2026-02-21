"""
LLM prompts for VOICEcheck dialogue analysis.

This module contains structured prompts for analyzing sales dialogues
using Large Language Models (LLMs). The prompts are designed to:

1. Evaluate dialogue quality across multiple categories
2. Extract key moments and identify important interactions
3. Generate actionable recommendations for improvement
4. Detect deal status and progress
5. Analyze speaking time distribution

The prompts follow a consistent JSON format structure for reliable
parsing and integration with the analysis pipeline. All prompts are
optimized for Russian language sales conversations.
"""

import json
from typing import Dict, List


class DialogueAnalysisPrompts:
    """
    Collection of structured prompts for sales dialogue analysis.

    Provides comprehensive analysis prompts for evaluating sales conversations
    across multiple dimensions including quality scoring, key moment extraction,
    status detection, and recommendation generation.

    Features:
    - Consistent JSON response format for reliable parsing
    - Optimized for Russian language sales dialogues
    - Comprehensive evaluation across 8 quality categories
    - Support for speaker identification and time-based analysis
    - Actionable recommendations for sales improvement

    Usage:
        prompt = DialogueAnalysisPrompts.get_analysis_prompt()
        formatted_prompt = prompt.format(transcript=transcription_text)
    """

    @staticmethod
    def get_analysis_prompt() -> str:
        """
        Main comprehensive prompt for sales dialogue analysis.

        Evaluates dialogue quality across 8 key categories, extracts important moments,
        generates actionable recommendations, and detects deal status.

        Categories evaluated:
        - Greeting and contact establishment
        - Needs discovery depth
        - Solution presentation relevance
        - Objection handling quality
        - Closing effectiveness
        - Active listening techniques
        - Empathy and tone
        - Overall meeting score

        Key moments tracked:
        - Objections, price questions, interest signals
        - Promises, next steps, agreements

        Returns:
            str: Complete analysis prompt formatted for LLM response in JSON structure
        """
        return """Анализируй аудиодиалог между продавцом и клиентом. Транскрипция содержит метки спикеров (SPEAKER_00 и SPEAKER_01).

Твоя задача:
1. Оцени качество диалога по 8 категориям (0-10 баллов)
2. Выяви ключевые моменты с таймлайнами
3. Дай 2-3 рекомендации по улучшению диалога
4. Определи статус сделки
5. Составь краткое резюме диалога (2-3 предложения)

Категории оценки (0-10 баллов):
1. greeting - Приветствие и установление контакта: как продавец представился, создал доверие
2. needs_discovery - Выявление потребностей: глубина вопросов о потребностях клиента
3. presentation - Презентация решения: релевантность предложенного решения
4. objection_handling - Работа с возражениями: качество обработки возражений
5. closing - Закрытие / call-to-action: качество завершения диалога
6. active_listening - Активное слушание: использование активных техник слушания
7. empathy - Эмпатия и тон: теплота, уважение и эмпатия в общении
8. overall - Общий балл встречи: среднее по всем категориям

Типы ключевых моментов:
- objection - возражения клиента ("дорого", "подумаю" и т.д.)
- price_question - вопросы о стоимости
- interest - сигналы интереса (позитивные реплики, уточнения)
- promise - обещания клиента ("вернусь", "обзвоню")
- next_steps - следующие шаги ("звоните завтра", "пришлите предложение")
- agreement - договоренности ("согласен", "заключим", "будем сотрудничать")

Твой ответ должен быть валидным JSON в следующем формате:
```json
{{
  "scores": {{
    "greeting": 0,
    "needs_discovery": 0,
    "presentation": 0,
    "objection_handling": 0,
    "closing": 0,
    "active_listening": 0,
    "empathy": 0,
    "overall": 0.0
  }},
  "status": "dealed|in_progress|rejected",
  "key_moments": [
    {{
      "type": "objection|price_question|interest|promise|next_steps|agreement",
      "time": 0,
      "text": "текст момента"
    }}
  ],
  "recommendations": [
    {{
      "text": "текст рекомендации",
      "time_range": [0, 0]
    }}
  ],
  "summary": "краткое резюме диалога (2-3 предложения)",
  "speaking_time": {{
    "sales": 0,
    "customer": 0
  }}
}}
```

Транскрипция:
{transcript}

Анализируй внимательно и предоставь объективную оценку."""

    @staticmethod
    def get_speaking_time_prompt(transcript: str) -> str:
        """
        Prompt for analyzing speaking time distribution between speakers.

        Calculates the total speaking time for sales representative and customer
        to analyze dialogue balance and engagement patterns.

        Args:
            transcript: The complete transcript with speaker labels (SPEAKER_00, SPEAKER_01)

        Returns:
            str: Prompt for speaking time analysis returning JSON format with:
                 - sales: Total speaking time in seconds for sales representative
                 - customer: Total speaking time in seconds for customer
        """
        return f"""Анализируй транскрипцию и подсчитай распределение времени между спикерами.
SPEAKER_00 = продавец (sales), SPEAKER_01 = клиент (customer).
Суммируй длительность каждого сегмента по спикерам.

Верни ТОЛЬКО JSON без пояснений:
```json
{{
  "speaking_time": {{
    "sales": 0,
    "customer": 0
  }}
}}
```

Транскрипция:
{transcript}"""

    @staticmethod
    def get_status_detection_prompt() -> str:
        """
        Prompt for detecting deal status based on conversation indicators.

        Analyzes dialogue patterns and key phrases to determine the current
        status of the sales opportunity with confidence scoring.

        Status definitions:
        - dealed: Client agreed to offer, clear purchase/cooperation agreements made
        - in_progress: Interest shown but no decision, next steps agreed upon
        - rejected: Explicit rejection, no interest or doubts expressed

        Returns:
            str: Prompt for status detection with JSON response containing:
                 - status: Current deal status
                 - confidence: Confidence level (0.0-1.0)
                 - reason: Brief justification for the status determination
        """
        return """Определи статус диалога на основе следующих критериев:

dealed: клиент согласился на предложение, есть явные договоренности о покупке/сотрудничестве
in_progress: интерес проявлен, но решения нет, договоренности о следующих шагах
rejected: явный отказ, нет интереса или сомнения

Ключевые индикаторы для определения статуса:
- dealed: позитивные соглашения ("согласен", "заключим", "куплю", "принимаю", "давайте начнем")
- in_progress: неопределенные ответы ("подумаю", "вернусь", "рассмотрю", "интересно", "дайте время")
- rejected: явные отказы ("не интересно", "отказ", "не нужно", "спасибо", "другое предложение")

Ответ в формате:
```json
{{
  "status": "dealed|in_progress|rejected",
  "confidence": 0.0,
  "reason": "краткое обоснование"
}}
```"""

    @staticmethod
    def get_extract_key_moments_prompt() -> str:
        """
        Prompt for extracting significant moments from sales dialogue.

        Identifies and categorizes key interaction points that are critical
        for sales process analysis and improvement opportunities.

        Key moment types identified:
        - objection: Customer objections about price, competitors, timing
        - price_question: Inquiries about costs, payment terms, pricing
        - interest: Positive signals showing customer engagement
        - promise: Commitments from customer for follow-up actions
        - next_steps: Agreed upon future actions and timelines
        - agreement: Final agreements and purchase decisions

        Returns:
            str: Prompt for key moments extraction with JSON response containing
                 array of moments with type, timestamp, and text content
        """
        return """Выдели ключевые моменты в диалоге со следующими типами:
- objection: возражения клиента ("дорого", "подумаю", "у конкурентов дешевле")
- price_question: вопросы о стоимости
- interest: сигналы интереса ("интересно", "расскажите подробнее")
- promise: обещания клиента ("вернусь", "обзвоню")
- next_steps: следующие шаги ("звоните завтра", "пришлите предложение")
- agreement: договоренности ("согласен", "заключим", "будем сотрудничать")

Для каждого момента укажи точный таймкод (в секундах) и текст отрывка.

Формат ответа:
```json
{{
  "key_moments": [
    {{
      "type": "objection|price_question|interest|promise|next_steps|agreement",
      "time": 0,
      "text": "текст момента"
    }}
  ]
}}
```

Транскрипция:
{transcript}"""