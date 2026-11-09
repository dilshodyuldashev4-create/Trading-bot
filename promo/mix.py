"""Сводит озвучку (v_<key>.wav по timings.json) с фоновой музыкой: python mix.py <vo_dir> <music.wav> <out.wav>"""
import json, subprocess, sys, wave, numpy as np
vo, music, out = sys.argv[1:4]; sr = 44100
T = json.load(open(f"{vo}/timings.json")); total = sum(t["dur"] for t in T)
def load(p):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", p, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, "<i2").astype(np.float32) / 32768
voice = np.zeros(int(sr * (total + 1))); start = 0.0
for t in T:
    v = load(f"{vo}/v_{t['key']}.wav"); i = int(sr * (start + (0.4 if t["key"] == "intro" else 0.2)))
    voice[i:i + len(v)] += v[:len(voice) - i]; start += t["dur"]
voice = voice[:int(sr * total)]; voice *= 0.95 / max(1e-6, np.abs(voice).max())
m = load(music)[:len(voice)]; m = np.pad(m, (0, len(voice) - len(m)))
# приглушаем музыку, пока звучит голос
env = np.convolve((np.abs(voice) > 0.02).astype(np.float32), np.ones(sr // 3) / (sr // 3), "same")
duck = 0.30 - 0.18 * np.clip(env * 4, 0, 1)
mixd = voice + m * duck; mixd *= 0.95 / np.abs(mixd).max()
d = (np.repeat(mixd[:, None], 2, 1) * 32767).astype("<i2")
with wave.open(out, "wb") as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(d.tobytes())
print("ok", total)
