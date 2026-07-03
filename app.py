"""
나만의 주식 대시보드
- yfinance 기반 (미국/한국 통합)
- 새로고침 버튼으로 실시간 갱신
- 적정PER 수기입력 → 내 목표가/상승여력 자동계산
"""
import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os
import base64
import requests
from datetime import datetime

st.set_page_config(page_title="주식 대시보드", layout="wide", page_icon="📊")

CONFIG_PATH = "config.json"
GITHUB_REPO = "rlacks22-hue/stock-tracking"
GITHUB_BRANCH = "chance-home"

def _github_token():
    try:
        return st.secrets.get("GITHUB_TOKEN")
    except Exception:
        return None

# ---------- Config I/O ----------
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"portfolio": [], "watchlist": []}

def _push_config_to_github(cfg, token):
    """Best-effort: commit config.json back to GitHub so changes survive
    Streamlit Cloud restarts (the container filesystem resets from git)."""
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CONFIG_PATH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(api, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {
            "message": "config.json 자동 업데이트 (대시보드에서 저장)",
            "content": base64.b64encode(
                json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
            ).decode("utf-8"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            body["sha"] = sha
        requests.put(api, headers=headers, json=body, timeout=10)
    except Exception:
        pass  # local file is already saved; cloud sync is best-effort

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    token = _github_token()
    if token:
        _push_config_to_github(cfg, token)

# ---------- Data fetch ----------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_one(ticker: str, market: str) -> dict:
    """Fetch raw fields for one ticker. Cached 5 min; clear cache to refetch."""
    yf_symbol = f"{ticker}.KS" if market == "KR" else ticker
    try:
        info = yf.Ticker(yf_symbol).info or {}
        return info
    except Exception as e:
        return {"_error": str(e)}

def pct(v):
    """Return v as percent. yfinance returns fractions for some fields."""
    if v is None:
        return None
    # if already >1 assume already in percent form
    return v * 100 if abs(v) < 1 else v

def build_row(item: dict) -> dict:
    info = fetch_one(item["ticker"], item.get("market", "US"))
    if "_error" in info:
        return {"종목": item.get("name", item["ticker"]), "오류": info["_error"][:60]}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev = info.get("previousClose")
    chg = ((price - prev) / prev * 100) if (price and prev) else None

    eps = info.get("trailingEps")
    fwd_eps = info.get("forwardEps")
    prev_eps = info.get("epsCurrentYear") or info.get("epsTrailingTwelveMonths")
    eps_growth = ((fwd_eps - eps) / abs(eps) * 100) if (fwd_eps and eps) else None

    tgt = info.get("targetMeanPrice")
    fair_per = item.get("fair_per")
    my_tgt = fair_per * eps if (fair_per and eps) else None
    upside_an = ((tgt / price - 1) * 100) if (tgt and price) else None
    upside_my = ((my_tgt / price - 1) * 100) if (my_tgt and price) else None

    div = info.get("dividendYield")
    div_pct = pct(div) if div is not None else None

    mcap = info.get("marketCap")
    mcap_str = f"{mcap/1e12:.2f}T" if mcap and mcap > 1e12 else (f"{mcap/1e9:.1f}B" if mcap else None)

    return {
        "국가": "🇰🇷" if item.get("market") == "KR" else "🇺🇸",
        "종목": item.get("name", item["ticker"]),
        "티커": item["ticker"],
        "현재가": price,
        "등락%": chg,
        "시총": mcap_str,
        "PER": info.get("trailingPE"),
        "Fwd PER": info.get("forwardPE"),
        "PBR": info.get("priceToBook"),
        "PEG": info.get("pegRatio") or info.get("trailingPegRatio"),
        "EPS": eps,
        "Fwd EPS": fwd_eps,
        "EPS성장%": eps_growth,
        "배당%": div_pct,
        "52주최고": info.get("fiftyTwoWeekHigh"),
        "52주최저": info.get("fiftyTwoWeekLow"),
        "애널목표가": tgt,
        "애널상승%": upside_an,
        "적정PER": fair_per,
        "내목표가": my_tgt,
        "내상승%": upside_my,
    }

def render_table(items, title, empty_msg):
    st.subheader(title)
    if not items:
        st.info(empty_msg)
        return
    rows = [build_row(it) for it in items]
    df = pd.DataFrame(rows)

    # Column formatting
    num_fmt = {
        "현재가": "{:,.2f}", "PER": "{:.1f}", "Fwd PER": "{:.1f}",
        "PBR": "{:.2f}", "PEG": "{:.2f}", "EPS": "{:.2f}", "Fwd EPS": "{:.2f}",
        "EPS성장%": "{:+.1f}%", "배당%": "{:.2f}%", "등락%": "{:+.2f}%",
        "52주최고": "{:,.2f}", "52주최저": "{:,.2f}",
        "애널목표가": "{:,.2f}", "애널상승%": "{:+.1f}%",
        "적정PER": "{:.1f}", "내목표가": "{:,.2f}", "내상승%": "{:+.1f}%",
    }
    st.dataframe(
        df.style.format(num_fmt, na_rep="—"),
        use_container_width=True, hide_index=True,
    )

# ---------- Sidebar: manage stocks ----------
cfg = load_config()

with st.sidebar:
    st.header("⚙️ 종목 관리")
    if _github_token():
        st.caption("☁️ 클라우드 자동저장 켜짐")
    else:
        st.caption("💾 로컬 저장만 (재시작 시 초기화될 수 있음)")
    tabs = st.tabs(["포트폴리오", "관심종목"])

    for tab, key, label in [(tabs[0], "portfolio", "포트폴리오"), (tabs[1], "watchlist", "관심종목")]:
        with tab:
            # 기존 종목 편집
            for i, item in enumerate(cfg[key]):
                with st.container(border=True):
                    st.markdown(f"**{item.get('name', item['ticker'])}** `{item['ticker']}` ({item.get('market','US')})")
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        new_fp = st.number_input(
                            "적정PER", value=float(item.get("fair_per") or 0),
                            step=0.5, format="%.1f", key=f"fp_{key}_{i}",
                            label_visibility="collapsed",
                        )
                        if new_fp != (item.get("fair_per") or 0):
                            cfg[key][i]["fair_per"] = new_fp if new_fp > 0 else None
                            save_config(cfg)
                    with c2:
                        if st.button("🗑", key=f"del_{key}_{i}"):
                            cfg[key].pop(i)
                            save_config(cfg)
                            st.rerun()

            # 종목 추가
            with st.expander(f"➕ {label}에 추가"):
                with st.form(f"add_{key}", clear_on_submit=True):
                    t = st.text_input("티커 (예: NVDA, 005930)")
                    n = st.text_input("표시할 이름 (예: 엔비디아)")
                    m = st.radio("시장", ["US", "KR"], horizontal=True, key=f"m_{key}")
                    fp = st.number_input("적정PER (없으면 0)", value=0.0, step=0.5, format="%.1f")
                    if st.form_submit_button("추가"):
                        if t.strip():
                            cfg[key].append({
                                "ticker": t.strip().upper() if m == "US" else t.strip(),
                                "name": n.strip() or t.strip(),
                                "market": m,
                                "fair_per": fp if fp > 0 else None,
                            })
                            save_config(cfg)
                            st.rerun()

# ---------- Main ----------
st.title("📊 나만의 주식 대시보드")

c1, c2 = st.columns([1, 5])
with c1:
    if st.button("🔄 새로고침", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with c2:
    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 캐시 유효시간 5분")

render_table(cfg["portfolio"], "💼 포트폴리오", "왼쪽 사이드바에서 종목을 추가하세요.")
st.divider()
render_table(cfg["watchlist"], "👀 관심종목", "왼쪽 사이드바에서 종목을 추가하세요.")

with st.expander("ℹ️ 데이터 안내"):
    st.markdown("""
- **데이터 출처**: Yahoo Finance (yfinance 라이브러리, 무료)
- **한국 종목** 티커는 6자리 숫자 (예: 삼성전자 `005930`, SK하이닉스 `000660`)
- **누락 가능 항목**: 한국 종목의 Forward PER, 애널리스트 목표주가, EPS 추정치는 일부 종목에서 값이 없거나 부정확할 수 있음
- **적정PER × EPS = 내 목표가**, **내 목표가 / 현재가 - 1 = 내 상승여력**
- 지연 시간: Yahoo Finance 무료 데이터는 15~20분 지연 가능
""")
