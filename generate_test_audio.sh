#!/bin/bash
# generate_test_audio.sh
# Генерация тестовых аудиофайлов для QA тестирования VOICEcheck

set -e

echo "=== Генерация тестовых аудиофайлов для VOICEcheck ==="

# Создать директорию для тестовых файлов
TEST_DIR="test_audio"
mkdir -p "$TEST_DIR"

echo "Создание файлов в директории: $TEST_DIR"

# Проверить наличие ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Ошибка: ffmpeg не установлен. Установите: sudo apt install ffmpeg"
    exit 1
fi

# 1. TC-FUNC-001: 1 минута тишины (для базового теста транскрибации)
echo "[1/5] Генерация test_1min_silence.mp3 (1 минута тишины)..."
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 60 -q:a 9 -acodec libmp3lame "$TEST_DIR/test_1min_silence.mp3" -y 2>/dev/null
echo "Создан: test_1min_silence.mp3"

# 2. TC-FUNC-002: 2 минуты синусоиды 1kHz (для теста diarization)
echo "[2/5] Генерация test_2min_sine.mp3 (2 минуты синусоиды)..."
ffmpeg -f lavfi -i sine=frequency=1000:duration=120 -q:a 9 -acodec libmp3lame "$TEST_DIR/test_2min_sine.mp3" -y 2>/dev/null
echo "Создан: test_2min_sine.mp3"

# 3. TC-FUNC-003: 30 секунд белого шума (для теста обработки шумов)
echo "[3/5] Генерация test_30s_noise.mp3 (30 секунд шума)..."
ffmpeg -f lavfi -i anoisesrc=duration=30:color=white:r=44100 -q:a 9 -acodec libmp3lame "$TEST_DIR/test_30s_noise.mp3" -y 2>/dev/null
echo "Создан: test_30s_noise.mp3"

# 4. TC-FUNC-004: Пустой файл (5 секунд тишины для теста ошибок)
echo "[4/5] Генерация test_empty.mp3 (5 секунд тишины)..."
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 5 -q:a 9 -acodec libmp3lame "$TEST_DIR/test_empty.mp3" -y 2>/dev/null
echo "Создан: test_empty.mp3"

# 5. TC-FUNC-005: Большой файл (~5MB, для проверки размера)
echo "[5/5] Генерация test_large.mp3 (больной файл ~5MB)..."
# Создаем файл с высоким bitrate для увеличения размера
ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo -t 300 -b:a 320k -acodec libmp3lame -ar 44100 -ac 2 "$TEST_DIR/test_large.mp3" -y 2>/dev/null
echo "Создан: test_large.mp3"

# Показать информацию о файлах
echo ""
echo "=== Созданные файлы ==="
ls -lh "$TEST_DIR"

echo ""
echo "=== Информация о файлах ==="
for file in "$TEST_DIR"/*.mp3; do
    if [ -f "$file" ]; then
        echo ""
        echo "Файл: $(basename $file)"
        ffprobe -v quiet -show_entries format=duration,size -show_entries stream=codec_name,sample_rate -of default=noprint_wrappers=1 "$file" 2>/dev/null || echo "  (метаданные недоступны)"
    fi
done

echo ""
echo "=== Тестовые файлы успешно созданы ==="
echo "Используйте их для тестирования:"
echo "  - test_1min_silence.mp3 (базовый тест)"
echo "  - test_2min_sine.mp3 (диаризация)"
echo "  - test_30s_noise.mp3 (шумоподавление)"
echo "  - test_empty.mp3 (обработка пустых файлов)"
echo "  - test_large.mp3 (проверка размера)"
