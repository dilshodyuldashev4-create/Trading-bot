"""Объём, час входа и тейк трендовых стратегий: проверка на истории поверх бота с 10 стратегиями.

    python scripts/edge_research.py
"""
from __future__ import annotations
import inspect, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")
import challenge_research as C
import day_guard_research as G
import indicator_research as R
import news_research as N
from goldbot.data import load_mt5_csv, resample
from challenge_research import KEYS

KEYS10 = N.KEYS10
# simulate с тейком по стратегии
_src = inspect.getsource(N.simulate).replace("e + d * 3.0 * dist", "e + d * TP.get(k, 3.0) * dist")
assert "TP.get" in _src
_g = dict(N.__dict__); _g["TP"] = {}
exec(_src, _g)
sim = _g["simulate"]


def feats(df):
    v = df.volume.astype(float)
    rv = (v / v.rolling(20).mean().shift(1)).fillna(1).to_numpy()
    nxt = lambda h: np.r_[np.asarray(h)[1:], 0]  # noqa: E731 — час бара входа (следующий после сигнала)
    out = dict(rv=rv, hn=nxt(df.index.hour), lon=nxt(df.index.tz_localize("UTC").tz_convert("Europe/London").hour))
    for n in (10, 50, 96):
        out[f"rv{n}"] = (v / v.rolling(n).mean().shift(1)).fillna(1).to_numpy()
    return out


def run(D, df, pin, E, F, sigmask=None, size=None, tp=None, slip=0.0):
    """sigmask(key, F) -> bool-массив: где сигнал оставить. size(x, F) -> множитель лота."""
    D2 = dict(D); D2["sig"] = {**D["sig"], **E}
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS10:
        opp = np.where(opp == 0, D2["sig"][k], opp)
    if sigmask:
        D2["sig"] = {k: (np.where(sigmask(k, F), v, 0).astype(np.int8) if k in KEYS10 else v) for k, v in D2["sig"].items()}
    _g["TP"] = tp or {}
    trades = sim(D2, dict(c=df.close.to_numpy(), opp=opp), KEYS10)
    for x in trades:
        x["r"] -= slip / x["dist"]
    sigs = np.stack([D2["sig"][k] for k in KEYS10])
    trades = [x for x in trades if pin[x["sig"]] != -x["d"]]
    hot = F["hot"]
    trades = [x for x in trades if not hot[x["i"]]]
    sizes = {}
    for x in trades:
        ki = KEYS10.index(x["key"]); lo = max(0, x["sig"] - 3)
        k = int((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any(axis=1).sum())
        sizes[id(x)] = (0.75 if k == 0 else 1.5) * (size(x, F) if size else 1.0)
    G.KEYS = KEYS10
    t, _ = G.portfolio(trades, df.index, G.Guard(day_sl=4), sizes)
    G.KEYS = KEYS
    rep = G.report(t, df.index)
    y = df.index[[x["i"] for x in t]].year
    pnl = np.array([x["pnl"] for x in t])
    rep["y24"], rep["y25"], rep["y26"] = pnl[y == 2024].sum(), pnl[y == 2025].sum(), pnl[y == 2026].sum()
    rep["sl"] = sum(1 for x in t if x["r"] < -0.5)
    return rep


def load_all():
    D0, df = R.setup(); D, _, pin = R.prepare(D0, df)
    m5 = load_mt5_csv(); k = 2 * m5.close.mean()
    m5 = m5.assign(open=k - m5.open, high=k - m5.low, low=k - m5.high, close=k - m5.close)
    dfm = resample(m5, "15min"); Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    out = []
    for D_, df_, pin_ in ((D, df, pin), (Dm, dfm, pinm)):
        F = feats(df_); F["hot"] = N.window_mask(df_.index, N.high_approx(df_.index), 10, 15)
        out.append((D_, df_, pin_, N.extras(df_), F))
    return out


M15 = {"squeeze", "donchian", "fvg_m15", "liq_m15", "amd", "asia"}


TREND5 = ("squeeze", "donchian_h1", "days5", "kama_h4", "klinger_h4")


def vol(lo, hi, cut=0.75, boost=1.25, col="rv"):
    return lambda x, F: cut if F[col][x["sig"]] < lo else (boost if F[col][x["sig"]] > hi else 1.0)


def no_hours(col, hrs):
    return lambda k, F: ~np.isin(F[col], hrs)


def variants():
    V = [("**как сейчас**", {})]
    for th in (0.5, 0.7, 0.9):
        V.append((f"фильтр: пропуск, если объём сигнальной свечи < {th} от среднего за 20", dict(sigmask=lambda k, F, th=th: F["rv"] >= th)))
    V += [
        ("лот ×0.75 при объёме < 1.0, ×1.25 при > 1.5 (20 свечей) ✅", dict(size=vol(1.0, 1.5))),
        ("то же, ×0.85 / ×1.15", dict(size=vol(1.0, 1.5, 0.85, 1.15))),
        ("то же, пороги 0.9 / 1.4", dict(size=vol(0.9, 1.4))),
        ("то же, пороги 0.7 / 2.0", dict(size=vol(0.7, 2.0))),
        ("то же, среднее за 10 свечей", dict(size=vol(1.0, 1.5, col="rv10"))),
        ("то же, среднее за 50 свечей", dict(size=vol(1.0, 1.5, col="rv50"))),
        ("то же, среднее за 96 свечей (сутки)", dict(size=vol(1.0, 1.5, col="rv96"))),
        ("без входа 9:00–10:59 UTC", dict(sigmask=no_hours("hn", (9, 10)))),
        ("без входа 9:00–10:59 по Лондону", dict(sigmask=no_hours("lon", (9, 10)))),
        ("без входа 10:00–11:59 по Лондону", dict(sigmask=no_hours("lon", (10, 11)))),
        ("тейк 4R у squeeze, donchian_h1, days5", dict(tp={k: 4.0 for k in TREND5[:3]})),
        ("тейк 5R у squeeze, donchian_h1, days5", dict(tp={k: 5.0 for k in TREND5[:3]})),
        ("тейк 4R у 5 трендовых (+ kama_h4, klinger_h4) ✅", dict(tp={k: 4.0 for k in TREND5})),
        ("**лот по объёму + тейк 4R у 5 трендовых (внедрено)**", dict(size=vol(1.0, 1.5), tp={k: 4.0 for k in TREND5})),
    ]
    return V


HEAD = ("| Вариант | Сделок | Стопов | Итог | Просадка | Итог/просадка | 2024 | 2025 | 2026 | до 07.2025 | после 07.2025 "
        "| Стресс +0.30 $ | Зеркало |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def row(n, s, ss, sm):
    return (f"| {n} | {s['n']} | {s['sl']} | {s['tot']:+.0f} % | {s['dd']:.1f} % | {s['ratio']:.1f} | {s['y24']:+.0f} % "
            f"| {s['y25']:+.0f} % | {s['y26']:+.0f} % | {s['a']:+.0f} % | {s['b']:+.0f} % | {ss['tot']:+.0f} % | {sm['tot']:+.0f} % |")


def main(vs=None):
    real, mir = load_all()
    L = [HEAD]
    print(HEAD)
    for name, kw in (vs or variants()):
        s = run(*real, **kw); ss = run(*real, slip=R.SLIP, **kw); sm = run(*mir, **kw)
        L.append(row(name, s, ss, sm))
        print(L[-1], flush=True)
    if vs is None:
        out = Path(__file__).resolve().parent.parent / "reports" / "edge_table.md"
        out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
