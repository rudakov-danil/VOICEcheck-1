#!/usr/bin/env python3
"""Создание минимальных тестовых WAV файлов."""
import wave
import struct
import os
from pathlib import Path

def create_wav(filename, duration=5, freq=440):
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000  # Уменьшаем для быстроты
    num_samples = int(duration * sample_rate)

    with wave.open(filename, 'w') as f:
        f.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
        for i in range(num_samples):
            import math
            if freq == 0:  # тишина
                value = 0
            else:
                value = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
            f.writeframes(struct.pack('<h', value))

    print(f"Создан: {filename} ({os.path.getsize(filename)} bytes)")

os.chdir("/home/gas/my_project/VOICEcheck")
create_wav("test_audio/test_5s_silence.wav", 5, 0)
create_wav("test_audio/test_10s_tone.wav", 10, 440)
create_wav("test_audio/test_empty.wav", 1, 0)
print("Готово!")
