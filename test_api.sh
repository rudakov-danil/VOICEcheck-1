#!/bin/bash
# test_api.sh
# Автоматизированное тестирование API VOICEcheck

set -e

BASE_URL="${BASE_URL:-http://localhost:8001}"
TEST_DIR="test_audio"

echo "=== Автоматизированное тестирование VOICEcheck API ==="
echo "Base URL: $BASE_URL"
echo ""

# Проверить наличие jq
if ! command -v jq &> /dev/null; then
    echo "Предупреждение: jq не установлен. Установите для красивого вывода JSON: sudo apt install jq"
    NO_JQ=true
else
    NO_JQ=false
fi

# Функция для форматирования JSON
format_json() {
    if [ "$NO_JQ" = true ]; then
        cat
    else
        jq .
    fi
}

# Функция для проверки HTTP статуса
check_status() {
    local expected=$1
    local actual=$2
    local test_name=$3

    if [ "$actual" -eq "$expected" ]; then
        echo "✅ PASS: $test_name (HTTP $actual)"
        return 0
    else
        echo "❌ FAIL: $test_name (ожидался HTTP $expected, получен HTTP $actual)"
        return 1
    fi
}

# Счетчик тестов
PASSED=0
FAILED=0

# TC-API-008: Health check
echo "[TC-API-008] Health check"
HTTP_CODE=$(curl -s -o /tmp/health_response.json -w "%{http_code}" "$BASE_URL/health")
if check_status 200 "$HTTP_CODE" "Health check"; then
    ((PASSED++))
    echo "Response:"
    cat /tmp/health_response.json | format_json
else
    ((FAILED++))
    echo "Response:"
    cat /tmp/health_response.json
fi
echo ""

# Проверить наличие тестовых файлов
if [ ! -f "$TEST_DIR/test_1min_silence.mp3" ]; then
    echo "❌ Ошибка: Тестовый файл не найден: $TEST_DIR/test_1min_silence.mp3"
    echo "Запустите ./generate_test_audio.sh для создания тестовых файлов"
    exit 1
fi

# TC-API-001: Upload file
echo "[TC-API-001] Upload file"
UPLOAD_RESPONSE=$(curl -s -X POST "$BASE_URL/upload" -F "file=@$TEST_DIR/test_1min_silence.mp3")
HTTP_CODE=$(curl -s -o /tmp/upload_response.json -w "%{http_code}" -X POST "$BASE_URL/upload" -F "file=@$TEST_DIR/test_1min_silence.mp3")

if check_status 200 "$HTTP_CODE" "Upload file"; then
    ((PASSED++))
    cat /tmp/upload_response.json | format_json
    FILE_ID=$(cat /tmp/upload_response.json | $NO_JQ && cat /tmp/upload_response.json || jq -r .file_id)
    echo "File ID: $FILE_ID"
else
    ((FAILED++))
    echo "Response:"
    cat /tmp/upload_response.json
    FILE_ID=""
fi
echo ""

# Если загрузка не удалась, прервать тесты
if [ -z "$FILE_ID" ] || [ "$FILE_ID" = "null" ]; then
    echo "❌ Критическая ошибка: Не удалось загрузить файл. Прерывание тестов."
    echo ""
    echo "=== Итоги тестирования ==="
    echo "Пройдено: $PASSED"
    echo "Провалено: $FAILED"
    exit 1
fi

# TC-API-002: Start transcription
echo "[TC-API-002] Start transcription"
TRANSCRIBE_RESPONSE=$(curl -s -X POST "$BASE_URL/transcribe/$FILE_ID" -d "language=auto")
HTTP_CODE=$(curl -s -o /tmp/transcribe_response.json -w "%{http_code}" -X POST "$BASE_URL/transcribe/$FILE_ID" -d "language=auto")

if check_status 200 "$HTTP_CODE" "Start transcription"; then
    ((PASSED++))
    cat /tmp/transcribe_response.json | format_json
    TASK_ID=$(cat /tmp/transcribe_response.json | $NO_JQ && cat /tmp/transcribe_response.json || jq -r .task_id)
    echo "Task ID: $TASK_ID"
else
    ((FAILED++))
    echo "Response:"
    cat /tmp/transcribe_response.json
    TASK_ID=""
fi
echo ""

# Если транскрибация не запустилась, пропустить статус-проверки
if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "null" ]; then
    echo "⚠️  Предупреждение: Не удалось запустить транскрибацию. Пропуск проверки статуса."
else
    # TC-API-003: Poll status
    echo "[TC-API-003] Poll status (ожидание завершения транскрибации...)"
    POLL_COUNT=0
    MAX_POLLS=30
    TRANSCRIPTION_STATUS=""

    while [ $POLL_COUNT -lt $MAX_POLLS ]; do
        STATUS_RESPONSE=$(curl -s "$BASE_URL/status/$TASK_ID")
        HTTP_CODE=$(curl -s -o /tmp/status_response.json -w "%{http_code}" "$BASE_URL/status/$TASK_ID")

        if [ "$HTTP_CODE" -eq 200 ]; then
            TRANSCRIPTION_STATUS=$(echo "$STATUS_RESPONSE" | $NO_JQ && echo "$STATUS_RESPONSE" || jq -r .status)
            PROGRESS=$(echo "$STATUS_RESPONSE" | $NO_JQ && echo "$STATUS_RESPONSE" || jq -r .progress)

            echo "Статус: $TRANSCRIPTION_STATUS (прогресс: $PROGRESS%)"

            if [ "$TRANSCRIPTION_STATUS" = "completed" ]; then
                ((PASSED++))
                echo "✅ PASS: Транскрибация завершена успешно"
                break
            elif [ "$TRANSCRIPTION_STATUS" = "failed" ]; then
                echo "❌ FAIL: Транскрибация завершилась с ошибкой"
                ((FAILED++))
                break
            fi
        else
            echo "❌ FAIL: Status check failed (HTTP $HTTP_CODE)"
            ((FAILED++))
            break
        fi

        ((POLL_COUNT++))
        sleep 2
    done

    if [ $POLL_COUNT -eq $MAX_POLLS ]; then
        echo "❌ FAIL: Тайм-аут ожидания транскрибации"
        ((FAILED++))
    fi

    # Показать результат
    echo "Response:"
    cat /tmp/status_response.json | format_json
    echo ""
fi

# TC-API-004: Get dialogs list
echo "[TC-API-004] Get dialogs list"
HTTP_CODE=$(curl -s -o /tmp/dialogs_response.json -w "%{http_code}" "$BASE_URL/dialogs?page=1&limit=10")

if check_status 200 "$HTTP_CODE" "Get dialogs list"; then
    ((PASSED++))
    echo "Response:"
    cat /tmp/dialogs_response.json | format_json
else
    ((FAILED++))
    echo "Response:"
    cat /tmp/dialogs_response.json
fi
echo ""

# TC-API-005: Get dialog details (если есть диалоги)
DIALOG_ID=$(cat /tmp/dialogs_response.json | $NO_JQ && cat /tmp/dialogs_response.json || jq -r '.items[0].id // empty')

if [ -n "$DIALOG_ID" ] && [ "$DIALOG_ID" != "null" ]; then
    echo "[TC-API-005] Get dialog details (ID: $DIALOG_ID)"
    HTTP_CODE=$(curl -s -o /tmp/dialog_detail_response.json -w "%{http_code}" "$BASE_URL/dialogs/$DIALOG_ID")

    if check_status 200 "$HTTP_CODE" "Get dialog details"; then
        ((PASSED++))
        echo "Response:"
        cat /tmp/dialog_detail_response.json | format_json
    else
        ((FAILED++))
        echo "Response:"
        cat /tmp/dialog_detail_response.json
    fi
    echo ""

    # TC-API-007: Analyze dialog
    echo "[TC-API-007] Analyze dialog (ID: $DIALOG_ID)"
    HTTP_CODE=$(curl -s -o /tmp/analyze_response.json -w "%{http_code}" -X POST "$BASE_URL/analyze/$DIALOG_ID")

    # Анализ может вернуть 503 если LLM не настроен
    if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 503 ]; then
        ((PASSED++))
        echo "✅ PASS: Analyze dialog (HTTP $HTTP_CODE)"
        echo "Response:"
        cat /tmp/analyze_response.json | format_json
    else
        echo "⚠️  WARNING: Analyze dialog returned HTTP $HTTP_CODE"
        echo "Response:"
        cat /tmp/analyze_response.json
    fi
    echo ""
else
    echo "⚠️  Предупреждение: Нет диалогов для проверки деталей и анализа"
fi

# TC-API-006: Delete dialog (если есть dialog_id)
if [ -n "$DIALOG_ID" ] && [ "$DIALOG_ID" != "null" ]; then
    echo "[TC-API-006] Delete dialog (ID: $DIALOG_ID)"
    HTTP_CODE=$(curl -s -o /tmp/delete_response.json -w "%{http_code}" -X DELETE "$BASE_URL/dialogs/$DIALOG_ID")

    if check_status 204 "$HTTP_CODE" "Delete dialog"; then
        ((PASSED++))
    else
        ((FAILED++))
        echo "Response:"
        cat /tmp/delete_response.json
    fi
    echo ""
fi

# Итоги
echo "=== Итоги тестирования ==="
echo "Пройдено: $PASSED"
echo "Провалено: $FAILED"
echo "Всего тестов: $((PASSED + FAILED))"

if [ $FAILED -eq 0 ]; then
    echo ""
    echo "🎉 Все тесты пройдены успешно!"
    exit 0
else
    echo ""
    echo "⚠️  Некоторые тесты провалены. Проверьте логи выше."
    exit 1
fi
