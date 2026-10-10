import re, time
from datetime import datetime
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="하따레이더 v2.0", page_icon="📡", layout="wide")
st.markdown("""<style>.block-container{padding-top:1rem;max-width:1400px} div[data-testid="stMetric"]{border:1px solid #8885;padding:10px;border-radius:12px}</style>""", unsafe_allow_html=True)
st.title("📡 찍찍 하따레이더 v2.0")
st.caption("급등 전 1~3일 후보 + 장중 거래량 확장 + SEC 희석 신호 | 관찰 우선순위 도구")

with st.sidebar:
    st.header("레이더 설정")
    pmin=st.number_input("최저 주가 ($)",.01,10000.0,.20,.10)
    pmax=st.number_input("최고 주가 ($)",.01,10000.0,20.0,1.0)
    min_dv=st.number_input("최소 20일 평균 거래대금 ($)",0,1000000000,150000,50000)
    limit=st.slider("최대 티커 수",5,150,40,5)
    period=st.selectbox("일봉 기간",["3mo","6mo","1y"],1)
    intraday=st.checkbox("5분봉 장중 분석",True)
    sec_on=st.checkbox("SEC 공시 키워드 탐지",True)
    email=st.text_input("SEC 연락 이메일(권장)",placeholder="you@example.com")

starter="""ALBT
CLDI
QNRX
PHIO
DYAI
SCNX
VCIG
FGI
PLAG
OCGN
XCUR
ATXG
WAFU
BYAH
HWH
JZXN
AIHS"""
st.subheader("1. 스캔 대상")
left,right=st.columns([1.4,1])
with left:
    ticktext=st.text_area("티커 목록 (줄바꿈/쉼표)",starter,height=200)
    csvfile=st.file_uploader("선택: ticker 또는 symbol 열이 있는 CSV",type=["csv"])
with right:
    st.markdown("**기준점 v2.0**")
    st.markdown("- 일봉 RVOL 및 거래량 축적\n- 5일 가격 압축\n- 20일 고점 접근\n- 당일 과열 감점\n- 장중 5분봉 누적 거래량 비교\n- SEC 최근 공시/희석 키워드")

def tickers():
    vals=re.split(r"[,;\s]+",ticktext or "")
    if csvfile:
        try:
            d=pd.read_csv(csvfile); c=next((x for x in d.columns if str(x).lower() in ["ticker","symbol","tic"]),d.columns[0])
            vals += d[c].dropna().astype(str).tolist()
        except Exception: st.warning("CSV를 읽지 못했어.")
    out=[]
    for x in vals:
        x=x.strip().upper().replace("$","").replace(".","-")
        if re.fullmatch(r"[A-Z0-9-]{1,12}",x) and x not in out: out.append(x)
    return out[:limit]

@st.cache_data(ttl=300,show_spinner=False)
def daily(t,period):
    try:
        d=yf.download(t,period=period,interval="1d",auto_adjust=True,progress=False,threads=False)
        if d is None or d.empty:return pd.DataFrame()
        if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
        cols=["Open","High","Low","Close","Volume"]
        return d[cols].dropna(subset=["Close"]) if set(cols).issubset(d.columns) else pd.DataFrame()
    except Exception:return pd.DataFrame()

@st.cache_data(ttl=180,show_spinner=False)
def bars5(t):
    try:
        d=yf.download(t,period="5d",interval="5m",auto_adjust=True,progress=False,threads=False,prepost=False)
        if d is None or d.empty:return pd.DataFrame()
        if isinstance(d.columns,pd.MultiIndex):d.columns=d.columns.get_level_values(0)
        return d[["Close","Volume"]].dropna()
    except Exception:return pd.DataFrame()

def num(x,default=0):
    try:return default if pd.isna(x) else float(x)
    except:return default

def tech(t,d):
    if d.empty or len(d)<22:return None
    c,h,l,v=[d[x].astype(float) for x in ["Close","High","Low","Volume"]]
    price=num(c.iloc[-1]); prev=num(c.iloc[-2]); ch=(price/prev-1)*100 if prev else 0
    avgv=num(v.iloc[-21:-1].mean()); rvol=num(v.iloc[-1])/avgv if avgv else 0
    dollar=num((c.iloc[-21:-1]*v.iloc[-21:-1]).mean())
    h20=num(h.iloc[-21:-1].max()); dist=(h20-price)/h20*100 if h20 else 999
    ret5=(price/num(c.iloc[-6])-1)*100 if num(c.iloc[-6]) else 0
    ret20=(price/num(c.iloc[-21])-1)*100 if num(c.iloc[-21]) else 0
    rng=(num(h.iloc[-5:].max())/max(num(l.iloc[-5:].min()),.0001)-1)*100
    pts=min(max((rvol-.8)*12,0),24)+ (max(0,18-rng*1.2) if rng<=15 else 0)
    pts += max(0,20-max(dist,0)*1.5) if dist>=0 else 20
    pts += 12 if ret5>0 and ret20>-8 else (7 if ret5>-2 else 0)
    pts += 10 if dollar>=1e6 else (6 if dollar>=300000 else (3 if dollar>=100000 else 0))
    pts += 8 if .5<=price<=10 else (5 if .2<=price<=20 else 0)
    pts -= min(max(ch-12,0)*1.5,20)+(8 if ch < -15 else 0)
    return {"티커":t,"기술점수":max(0,min(100,round(pts))),"종가($)":round(price,4),"당일변동(%)":round(ch,2),
            "일봉RVOL":round(rvol,2),"20일고점거리(%)":round(dist,2),"5일변동(%)":round(ret5,2),
            "5일변동폭(%)":round(rng,2),"평균거래대금($)":round(dollar),"거래량":int(num(v.iloc[-1]))}

@st.cache_data(ttl=3600,show_spinner=False)
def cik_map():
    h={"User-Agent":"HattaRadar/2.0 contact: user@example.com"}
    r=requests.get("https://www.sec.gov/files/company_tickers.json",headers=h,timeout=20);r.raise_for_status()
    return {str(x["ticker"]).upper():str(x["cik_str"]).zfill(10) for x in r.json().values()}

terms=[
("ATM",r"at[- ]the[- ]market|ATM offering"),("등록/재판매",r"S-1|S-3|F-1|F-3|424B|resale registration|selling stockholders"),
("워런트",r"warrant|pre-funded warrant"),("전환증권",r"convertible note|convertible debenture|conversion price"),
("ELOC/주식한도",r"equity line|committed equity|purchase agreement"),("공모/사모",r"registered direct offering|private placement|underwritten offering"),
("역병합",r"reverse stock split|reverse split"),("희석/발행",r"dilut|issuance of shares|shares of common stock")]
@st.cache_data(ttl=3600,show_spinner=False)
def sec_scan(t,email):
    h={"User-Agent":f"HattaRadar/2.0 contact: {email if '@' in email else 'user@example.com'}"}
    try:
        cik=cik_map().get(t)
        if not cik:return {"SEC위험":"확인불가","최근공시":"CIK 매핑 없음","희석신호":"","공시페널티":0,"SEC링크":f"https://www.sec.gov/edgar/search/#/q={t}"}
        j=requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",headers=h,timeout=20).json()["filings"]["recent"]
        rec=[]
        for i,f in enumerate(j.get("form",[])[:100]):
            if f in {"S-1","S-3","F-1","F-3","424B3","424B5","EFFECT","8-K","6-K","10-Q","10-K","DEF 14A","PRE 14A"}:
                rec.append((f,j["filingDate"][i],j["accessionNumber"][i],j["primaryDocument"][i]))
            if len(rec)>=5:break
        signals=[];pen=0;links=[]
        for f,date,acc,doc in rec:
            if f in {"S-1","S-3","F-1","F-3","424B3","424B5","EFFECT"}:
                signals.append(f"{f} 등록/효력 공시");pen=max(pen,10)
            elif f in {"8-K","6-K"}:signals.append(f"{f} 중요사항(본문 확인 필요)");pen=max(pen,4)
            if acc and doc:links.append(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{doc}")
        for link in links[:3]:
            try:
                rr=requests.get(link,headers=h,timeout=15)
                if rr.ok:
                    body=re.sub(r"<[^>]+>"," ",rr.text);body=re.sub(r"\s+"," ",body)
                    for label,pat in terms:
                        if re.search(pat,body,re.I) and label not in signals:signals.append(label);pen=min(20,pen+2)
            except Exception:pass
            time.sleep(.1)
        risk="높음" if pen>=14 else ("주의" if pen>=5 else "낮음/미탐지")
        latest="; ".join(f"{f} {date}" for f,date,_,_ in rec[:4]) or "대상 공시 없음"
        return {"SEC위험":risk,"최근공시":latest,"희석신호":", ".join(signals) or "자동 탐지 신호 없음","공시페널티":pen,"SEC링크":links[0] if links else f"https://www.sec.gov/edgar/search/#/q={t}"}
    except Exception as e:return {"SEC위험":"조회오류","최근공시":type(e).__name__,"희석신호":"SEC 조회 실패 — 원문 확인 필요","공시페널티":0,"SEC링크":f"https://www.sec.gov/edgar/search/#/q={t}"}

def intraday(t):
    d=bars5(t)
    if d.empty or len(d)<5:return {"장중RVOL":None,"장중변동(%)":None,"장중상태":"5분봉 없음"}
    w=d.copy();w["_date"]=pd.to_datetime(w.index).date;ds=sorted(w["_date"].unique());today=w[w["_date"]==ds[-1]];n=len(today)
    prior=[]
    for day in ds[:-1][-5:]:
        x=w[w["_date"]==day]
        if len(x)>=min(n,3):prior.append(num(x["Volume"].iloc[:n].sum()))
    base=sum(prior)/len(prior) if prior else 0
    vol=num(today["Volume"].sum());first=num(today["Close"].iloc[0]);last=num(today["Close"].iloc[-1])
    return {"장중RVOL":round(vol/base,2) if base else None,"장중변동(%)":round((last/first-1)*100,2) if first else None,"장중상태":f"{n}개 5분봉 / 비교 {len(prior)}세션"}

if st.button("🚀 레이더 실행",type="primary",use_container_width=True):
    ts=tickers()
    if not ts:st.error("티커를 입력하거나 CSV를 올려줘.")
    elif pmin>pmax:st.error("최저가가 최고가보다 높아.")
    else:
        rows=[];errors=[];prog=st.progress(0);status=st.empty()
        for i,t in enumerate(ts,1):
            status.write(f"분석 중: {t} ({i}/{len(ts)})")
            d=daily(t,period);r=tech(t,d)
            if not r:errors.append(f"{t}: 일봉 데이터 부족/조회 실패");prog.progress(i/len(ts));continue
            if not pmin<=r["종가($)"]<=pmax:errors.append(f"{t}: 주가 필터 제외");prog.progress(i/len(ts));continue
            if r["평균거래대금($)"]<min_dv:errors.append(f"{t}: 거래대금 필터 제외");prog.progress(i/len(ts));continue
            r.update(intraday(t) if intraday else {"장중RVOL":None,"장중변동(%)":None,"장중상태":"미실행"})
            r.update(sec_scan(t,email) if sec_on else {"SEC위험":"미실행","최근공시":"","희석신호":"","공시페널티":0,"SEC링크":""})
            r["레이더점수"]=max(0,r["기술점수"]-r["공시페널티"])
            s=r["레이더점수"];r["등급"]="🔥 85+" if s>=85 else ("🔥 75–84" if s>=75 else ("🟢 65–74" if s>=65 else "관찰"))
            ir=r.get("장중RVOL")
            r["장중경보"]="⚡ 장중 거래량 확장" if ir is not None and ir>=2 and r["당일변동(%)"]<20 else ("👀 고점 접근 + 거래량" if r["일봉RVOL"]>=1.8 and r["20일고점거리(%)"]<=8 else "—")
            rows.append(r);prog.progress(i/len(ts))
        status.empty();prog.empty();st.session_state["rows"]=rows;st.session_state["errors"]=errors

if "rows" in st.session_state:
    df=pd.DataFrame(st.session_state["rows"])
    st.subheader("2. 결과")
    if not df.empty:
        df=df.sort_values(["레이더점수","장중RVOL","일봉RVOL"],ascending=False,na_position="last")
        a,b,c,d=st.columns(4);a.metric("분석 결과",len(df));b.metric("85점+",int((df["레이더점수"]>=85).sum()));c.metric("75점+",int((df["레이더점수"]>=75).sum()));d.metric("SEC 주의/높음",int(df["SEC위험"].isin(["주의","높음"]).sum()))
        cols=["티커","레이더점수","등급","장중경보","종가($)","당일변동(%)","일봉RVOL","장중RVOL","20일고점거리(%)","5일변동폭(%)","평균거래대금($)","SEC위험","최근공시","희석신호","공시페널티"]
        st.dataframe(df[[c for c in cols if c in df]],use_container_width=True,hide_index=True)
        st.download_button("📥 CSV 다운로드",df.to_csv(index=False).encode("utf-8-sig"),"hatta_radar_v2.csv","text/csv")
        sel=st.selectbox("종목별 상세",df["티커"].tolist());r=df[df["티커"]==sel].iloc[0]
        a,b,c,d=st.columns(4);a.metric("최종 점수",f"{int(r['레이더점수'])}/100",r["등급"]);b.metric("일봉 RVOL",f"{r['일봉RVOL']}x");c.metric("장중 RVOL","—" if pd.isna(r["장중RVOL"]) else f"{r['장중RVOL']}x");d.metric("SEC 위험",r["SEC위험"])
        st.write("**최근 공시:**",r["최근공시"]);st.write("**희석 키워드:**",r["희석신호"])
        st.link_button("SEC 원문/검색 열기",r["SEC링크"])
        st.warning("SEC 키워드 탐지는 단서일 뿐 현재 매도 가능 물량이나 확정 희석 판정이 아닙니다. EFFECT, 424B, 계약 조건, 잔여 한도, 워런트/전환가, 실제 발행주식 수를 원문으로 확인하세요.")
    else:st.warning("조건을 통과한 티커가 없어. 필터를 완화해 봐.")
    if st.session_state["errors"]:
        with st.expander(f"제외/오류 ({len(st.session_state['errors'])})"):st.write("\\n".join(st.session_state["errors"]))

st.markdown("---")
st.subheader("점수 기준")
st.markdown("""
| 요소 | 최대/처리 |
|---|---:|
| 일봉 상대거래량 | 24점 |
| 5일 가격 압축 | 18점 |
| 20일 고점 접근 | 20점 |
| 단기 추세 | 12점 |
| 평균 거래대금 | 10점 |
| 가격대 | 8점 |
| 당일 과열 | 최대 -20점 |
| SEC 등록/희석 키워드 페널티 | 최대 -20점 |
""")
st.caption("한계: 입력/CSV 티커만 분석. 미국 전체 종목 전수검색은 아님. 5분봉·Yahoo Finance 데이터는 지연/누락 가능. SEC 키워드 검색은 제한적이며 수동 원문 검증 필수. 점수는 급등 확률이나 매수 추천이 아님.")
