# Рекламный ролик (код)

Вертикальное видео 1080×1920 для бота @FOREXCFD_BOT: анимация в `promo.html`, озвучка RHVoice, музыка синтезом.

```bash
sudo apt-get install rhvoice rhvoice-russian ffmpeg
python3 voice.py out/            # озвучка по сценам + out/timings.json
cp out/timings.json .
D=$(python3 -c "import json;print(sum(t['dur'] for t in json.load(open('timings.json'))))")
python3 music.py out/music.wav $D
python3 mix.py out out/music.wav out/audio.wav
node render.js out/frames 30     # нужен playwright
ffmpeg -framerate 30 -i out/frames/f%05d.jpg -i out/audio.wav -c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -shortest promo.mp4
```

Текст озвучки — словарь `LINES` в `voice.py`; длительность сцен подстраивается под голос.
