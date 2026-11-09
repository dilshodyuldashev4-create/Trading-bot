"""Узбекская озвучка из одного mp3 (ElevenLabs читает и номера строк «1.», «2.»…):
режем по паузам на 9 фраз без номеров, пишем v_<key>.wav, timings.json и subs.json (субтитры).
python voice_uz.py <mp3> <outdir>"""
import json, re, subprocess, sys
src, out = sys.argv[1:3]
KEYS = ["intro", "signal", "strats", "rr", "lot", "calendar", "features", "price", "cta"]
LINES = [l.split(". ", 1)[1].strip() for l in open(__file__.replace("voice_uz.py", "ovoz_matni_uz.md"), encoding="utf-8") if re.match(r"\d\. ", l)]
PAD = 0.55
log = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-af", "silencedetect=noise=-40dB:d=0.3", "-f", "null", "-"], capture_output=True, text=True).stderr
starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True).stdout)
# речевые куски между паузами
chunks, prev = [], 0.0
for s, e in zip(starts, ends):
    chunks.append([prev, s]); prev = e
if prev < total - 0.05: chunks.append([prev, total])
# номер строки — короткое слово (<0.8 с) в начале каждой фразы: ищем 9 таких кусков
short = [i for i, (a, b) in enumerate(chunks) if b - a < 0.8 and i > 0]
# у номера строки перед ним самая длинная пауза (конец предыдущей фразы)
short.sort(key=lambda i: chunks[i][0] - chunks[i - 1][1], reverse=True)
nums = [0] + sorted(short[:8])
assert len(nums) == 9 and nums[0] == 0, (nums, chunks)
timings, subs, t0 = [], [], 0.0
for n, key in enumerate(KEYS):
    body = chunks[nums[n] + 1: nums[n + 1] if n < 8 else len(chunks)]
    a, b = body[0][0] - 0.05, body[-1][1] + 0.05
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-ss", f"{a:.3f}", "-to", f"{b:.3f}", f"{out}/v_{key}.wav"], check=True)
    d = b - a
    lead = 0.4 if key == "intro" else 0.2  # как в mix.py
    timings.append({"key": key, "voice": round(d, 3), "dur": round(d + PAD + (0.5 if key == "intro" else 0), 3)})
    # субтитры: позиция символа в тексте ∝ «время речи» (без пауз), так паузы голоса учитываются
    text = LINES[n]
    pieces = [(c[0] - a, c[1] - a) for c in body]
    speech = sum(q - p for p, q in pieces)
    def at(frac):
        left = frac * speech
        for p, q in pieces:
            if left <= q - p: return p + left
            left -= q - p
        return pieces[-1][1]
    caps, cur = [], []
    for w in text.split():
        line = " ".join(cur + [w])
        if cur and (len(line) > 56 or (re.search(r"[.:]$", cur[-1]) and len(" ".join(cur)) >= 16)):
            caps.append(" ".join(cur)); cur = [w]
        else: cur.append(w)
    caps.append(" ".join(cur))
    if len(caps) > 1 and len(caps[-1]) < 16:
        last = caps.pop(); caps[-1] += " " + last
    pos = 0
    for c in caps:
        f0, f1 = pos / len(text), min(1, (pos + len(c)) / len(text)); pos += len(c) + 1
        subs.append({"s": round(t0 + lead + at(f0), 3), "e": round(t0 + lead + at(f1) + 0.15, 3), "text": c})
    t0 += timings[-1]["dur"]
json.dump(timings, open(f"{out}/timings.json", "w"), indent=1)
json.dump(subs, open(f"{out}/subs.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(timings), t0)
for s in subs: print(s)
