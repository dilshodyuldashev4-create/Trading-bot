"""Простая фоновая музыка для ролика (синтез numpy): бас-бочка, хэт, аккорды. python music.py out.wav 27"""
import sys, wave, numpy as np
out, dur = sys.argv[1], float(sys.argv[2]); sr = 44100; bpm = 110; beat = 60 / bpm
t = np.arange(int(sr * dur)) / sr; mix = np.zeros_like(t)
def note(f): return 440 * 2 ** ((f - 69) / 12)
chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
bar = beat * 4
for i in range(int(dur / bar) + 1):
    st = i * bar; ch = chords[i % 4]; m = (t >= st) & (t < st + bar); tt = t[m] - st
    env = np.minimum(tt / 0.3, 1) * np.exp(-tt * 0.5)
    for n in ch:
        f = note(n); mix[m] += 0.07 * env * (np.sin(2*np.pi*f*tt) + 0.3*np.sin(2*np.pi*2*f*tt + 0.5))
    fb = note(ch[0] - 12)
    for b in range(4):
        mb = (tt >= b*beat) & (tt < (b+1)*beat); tb = tt[mb] - b*beat
        mix[np.where(m)[0][mb]] += 0.12 * np.exp(-tb*4) * np.sign(np.sin(2*np.pi*fb*tb)) * 0.6
for k in range(int(dur / beat) + 1):  # kick
    st = k * beat; m = (t >= st) & (t < st + 0.35); tt = t[m] - st
    mix[m] += 0.5 * np.exp(-tt * 12) * np.sin(2*np.pi*(50 + 90*np.exp(-tt*30))*tt)
rng = np.random.default_rng(1)
for k in range(int(dur / beat * 2) + 1):  # hi-hat on off-beats
    if k % 2 == 0: continue
    st = k * beat / 2; m = (t >= st) & (t < st + 0.06); tt = t[m] - st
    mix[m] += 0.06 * np.exp(-tt * 60) * rng.standard_normal(m.sum())
fade = np.minimum(1, np.minimum(t / 0.5, (dur - t) / 1.5)); mix *= fade
mix = mix / np.max(np.abs(mix)) * 0.8
d = (np.repeat(mix[:, None], 2, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(d.tobytes())
