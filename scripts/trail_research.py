import sys; sys.path[:0]=['scripts','.']
import numpy as np, inspect
import profit3_research as P3, indicator_research as R, profit2_research as Q, challenge_research as C, profit_research as P
from goldbot.data import load_mt5_csv, resample, PIP
src=inspect.getsource(P.simulate)
src=src.replace("def simulate(D, ctx, op: Opt = Opt()):","def simulate(D, ctx, op: Opt = Opt()):\n    TK, TR, TPM = TRAIL")
src=src.replace("            tp = e + d * 3.0 * dist\n","            tr_on = k in TK\n            tp = e + d * (TPM if tr_on else 3.0) * dist\n            best = e\n")
src=src.replace("                if new_stop is not None:\n                    stop, new_stop = new_stop, None\n",
"                if new_stop is not None:\n                    stop, new_stop = new_stop, None\n                if tr_on and part_done:\n                    ts = best - d * TR * dist\n                    if (ts - stop) * d > 0: stop = ts\n")
src=src.replace("                cl = c[j] + (spr[j] if d == -1 else 0.0)\n","                best = max(best, h[j]) if d == 1 else min(best, l[j])\n                cl = c[j] + (spr[j] if d == -1 else 0.0)\n")
assert src.count('TRAIL')==1 and 'best = max' in src and 'ts = best' in src
g=P.__dict__; exec(src,g); P.TRAIL=((),0,3.0)
D0,df=R.setup(); D,_,pin=R.prepare(D0,df); E=P3.extras(df)
m=load_mt5_csv(); k=2*m.close.mean(); m=m.assign(open=k-m.open,high=k-m.low,low=k-m.high,close=k-m.close)
dfm=resample(m,'15min'); Dm,_,pinm=R.prepare(C.load(mirror=True),dfm); Em=P3.extras(dfm)
def run(tr):
  P.TRAIL=tr
  r=Q.run2(D,df,pin,E); rs=Q.run2(D,df,pin,E,slip=.3); rm=Q.run2(Dm,dfm,pinm,Em); return r,rs,rm
b,bs,bm=run(((),0,3.0))
print('base',round(b['tot']),round(b['dd'],1),round(b['a']),round(b['b']),round(bs['tot']),round(bm['tot']))
TREND=('donchian_h1','days5','squeeze')
ALL=('squeeze','donchian','fvg_m15','liq_m15','amd','asia','donchian_h1','days5')
for keys,name in ((TREND,'trend3'),(ALL,'all')):
  for trk,tpm in ((99,4.0),(99,5.0),(99,6.0),(2.5,6.0),(3.0,5.0),(3.0,8.0),(4.0,6.0),(4.0,8.0)):
      r,rs,rm=run((keys,trk,tpm))
      ok=r['tot']>b['tot'] and r['a']>b['a'] and r['b']>b['b'] and rs['tot']>bs['tot'] and rm['tot']>bm['tot']
      print(name,trk,tpm,'ok' if ok else '--',round(r['tot']),round(r['dd'],1),round(r['worst'],1),round(r['a']),round(r['b']),round(rs['tot']),round(rm['tot']),flush=True)
