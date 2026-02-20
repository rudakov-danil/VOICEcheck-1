#!/usr/bin/env python3
"""
Генерация тестовых аудиофайлов для VOICEcheck QA тестирования.
Использует стандартную библиотеку (не требует ffmpeg).
"""

import wave
import struct
import os
from pathlib import Path

def create_wav_file(filename, duration_sec, frequency=440.0, volume=0.3, sample_rate=44100):
    """
    Создает WAV файл с синусоидой.

    Args:
        filename: Имя выходного файла
        duration_sec: Длительность в секундах
        frequency: Частота тона в Гц
        volume: Громкость (0.0 - 1.0)
        sample_rate: Частота дискретизации
    """
    # Создать директорию если не существует
    Path(filename).parent.mkdir(parents=True, exist_ok=True)

    # Количество сэмплов
    num_samples = int(duration_sec * sample_rate)

    # Открыть WAV файл для записи
    with wave.open(filename, 'w') as wav_file:
        # Конфигурация: 1 канал (моно), 2 байта на сэмпл, частота 44100 Hz
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))

        # Генерация аудиоданных
        for i in range(num_samples):
            # Синусоида
            t = float(i) / sample_rate
            value = int(32767.0 * volume * (1 if frequency == 0 else 0.5 + 0.5 * (32767 / 32767.0)))

            if frequency > 0:
                # Синусоидальный сигнал
                import math
                value = int(32767.0 * volume * math.sin(2.0 * math.pi * frequency * t))

            # Упаковка в бинарный формат (little-endian signed short)
            data = struct.pack('<h', value)
            wav_file.writeframes(data)

    file_size = os.path.getsize(filename)
    print(f"  Создан: {filename} ({file_size} bytes, {duration_sec} sec)")

def create_silence(filename, duration_sec):
    """Создает файл с тишиной."""
    create_wav_file(filename, duration_sec, frequency=0, volume=0)

def create_tone(filename, duration_sec, frequency=440.0):
    """Создает файл с тоном."""
    create_wav_file(filename, duration_sec, frequency=frequency, volume=0.5)

def create_noise(filename, duration_sec):
    """Создает файл с белым шумом."""
    import random
    import math

    Path(filename).parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 44100
    num_samples = int(duration_sec * sample_rate)

    with wave.open(filename, 'w') as wav_file:
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))

        for i in range(num_samples):
            # Случайный шум
            value = int(32767.0 * 0.1 * (2.0 * random.random() - 1.0))
            data = struct.pack('<h', value)
            wav_file.writeframes(data)

    file_size = os.path.getsize(filename)
    print(f"  Создан: {filename} ({file_size} bytes, {duration_sec} sec)")

def main():
    print("=== Генерация тестовых аудиофайлов для VOICEcheck ===\n")

    TEST_DIR = "test_audio"
    print(f"Создание файлов в директории: {TEST_DIR}\n")

    # 1. TC-FUNC-001: 1 минута тишины
    print("[1/5] Генерация test_1min_silence.wav (1 минута тишины)...")
    create_silence(f"{TEST_DIR}/test_1min_silence.wav", 60)

    # 2. TC-FUNC-002: 2 минуты тона 440Hz
    print("[2/5] Генерация test_2min_tone.wav (2 минуты тона)...")
    create_tone(f"{TEST_DIR}/test_2min_tone.wav", 120, frequency=440.0)

    # 3. TC-FUNC-003: 30 секунд шума
    print("[3/5] Генерация test_30s_noise.wav (30 секунд шума)...")
    create_noise(f"{TEST_DIR}/test_30s_noise.wav", 30)

    # 4. TC-FUNC-004: Пустой файл
    print("[4/5] Генерация test_empty.wav (5 секунд тишины)...")
    create_silence(f"{TEST_DIR}/test_empty.wav", 5)

    # 5. TC-FUNC-005: Большой файл (5 минут)
    print("[5/5] Генерация test_large.wav (5 минут тишины)...")
    create_silence(f"{TEST_DIR}/test_large.wav", 300)

    print("\n=== Информация о файлах ===")
    for wav_file in Path(TEST_DIR).glob("*.wav"):
        size = wav_file.stat().st_size
        print(f"  {wav_file.name}: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")

    print("\n✅ Тестовые файлы успешно созданы")
    print("\nПримечание: Файлы созданы в формате WAV (а не MP3)")
    print("Это нормально - Whisper поддерживает WAV файлы.")

if __name__ == "__main__":
    main()
