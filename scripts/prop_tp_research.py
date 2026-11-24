import sys, inspect; sys.path[:0]=['scripts','.']
import numpy as np
import challenge_research as C, profit2_research as Q
from goldbot.data import load_mt5_csv, resample
from goldbot.strategies.popular import days_breakout, donchian_h1
from goldbot.strategies.sessions import asian_breakout_day
from goldbot.strategies.research import htf_trend
src=inspect.getsource(C.attempt).replace("tp_d = cfg.tp_r * dist if cfg.tp_r else tp_a[i] * PIP",
  "tp_d = TPK.get(k, 0) * dist or (cfg.tp_r * dist if cfg.tp_r else tp_a[i] * PIP)")
assert 'TPK' in src
g=C.__dict__; exec(src,g); C.TPK={}
KEYS8=("squeeze","donchian","fvg_m15","liq_m15","amd","asia","donchian_h1","days5")
def mk(mirror):
  D=C.load(mirror)
  m5=load_mt5_csv()
  if mirror:
    k=2*m5.close.mean(); m5=m5.assign(open=k-m5.open,high=k-m5.low,low=k-m5.high,close=k-m5.close)
  df=resample(m5,'15min'); tr=htf_trend(df,'1D',50)
  D['sig']['asia']=asian_breakout_day(df).astype(np.int8)
  for kk,s in (('donchian_h1',donchian_h1(df)),('days5',days_breakout(df,5))):
    D['sig'][kk]=np.where(s==tr,s,0).astype(np.int8)
  return D
base=C.Cfg(keys=KEYS8, day_losses=1, dd_cut=2, dd_mult=0.25)
import dataclasses
VAR=[("как сейчас: тейк 1.5R у всех",{}),
     ("тренд-стратегии (squeeze, donchian_h1, days5) тейк 2R",{k:2.0 for k in ("squeeze","donchian_h1","days5")}),
     ("тренд-стратегии тейк 2.5R",{k:2.5 for k in ("squeeze","donchian_h1","days5")}),
     ("тренд-стратегии тейк 3R",{k:3.0 for k in ("squeeze","donchian_h1","days5")}),
     ("все стратегии тейк 2R",{k:2.0 for k in KEYS8})]
from multiprocessing import Pool
def row(arg):
  name,tpk,which=arg
  C.TPK=tpk; D=DS[which]; out=[]
  for cfg in (base, dataclasses.replace(base,cost_r=0.1)):
    for sl in ((None,"2025-07-01"),("2025-07-01",None)):
      st=C.starts(D,since=sl[0],until=sl[1],every=2)
      r=C.summary(D,C.PLANS["2step1"],cfg,st); r1=C.summary(D,C.PLANS["1step"],cfg,st)
      lost,_,med=C.funded(D,cfg,st,90)
      out.append(f"{r['pass']:.0f}/{r['fail']:.1f}/{r['days']:.0f}д; 1st {r1['fail']:.1f}% {r1['days']:.0f}д; фин {lost:.1f}% {med:+.1f}%")
  return name,which,out
DS={'real':mk(False),'mirror':mk(True)}
if __name__=='__main__':
  with Pool() as p:
    for name,which,out in p.imap(row,[(n,t,w) for n,t in VAR for w in ('real','mirror')]):
      print(name,which); [print('   ',lbl,o) for lbl,o in zip(('до07.25','после07.25','стресс до','стресс после'),out)]
