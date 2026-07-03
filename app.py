"""
챠니의 주식 check~♬
- yfinance 기반 (미국/한국 통합)
- 새로고침 버튼으로 실시간 갱신
- 표에서 더블클릭으로 값 직접 수정 (수기 입력값은 노란색으로 표시)
- 정보 자동화 버튼: 실시간으로 가져올 수 있는 값은 자동값으로 되돌리고,
  가져올 수 없는 값은 수기입력값을 그대로 둠
"""
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode
import json
import os
import base64
import requests
from datetime import datetime

st.set_page_config(page_title="챠니의 주식 check~♬", layout="wide", page_icon="📊")

CONFIG_PATH = "config.json"
GITHUB_REPO = "rlacks22-hue/stock-tracking"
GITHUB_BRANCH = "chance-home"

# 표에서 직접 수정 가능한 항목 (수기입력값은 overrides 에 저장됨)
EDITABLE_COLS = [
    "현재가", "PER", "Fwd PER", "PBR", "PEG", "EPS", "Fwd EPS",
    "EPS성장%", "배당%", "52주최고", "52주최저", "애널목표가", "적정PER",
]

def _github_token():
    try:
        return st.secrets.get("GITHUB_TOKEN")
    except Exception:
        return None

# ---------- Config I/O ----------
def _migrate_item(item: dict) -> dict:
    item.setdefault("overrides", {})
    fair_per = item.pop("fair_per", None)
    if fair_per is not None and "적정PER" not in item["overrides"]:
        item["overrides"]["적정PER"] = fair_per
    return item

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {"portfolio": [], "watchlist": []}
    for key in ("portfolio", "watchlist"):
        cfg[key] = [_migrate_item(it) for it in cfg.get(key, [])]
    return cfg

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
    return v * 100 if abs(v) < 1 else v

def compute_live(info: dict) -> dict:
    """Values yfinance can actually provide right now. None = not fetchable."""
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    eps = info.get("trailingEps")
    fwd_eps = info.get("forwardEps")
    eps_growth = ((fwd_eps - eps) / abs(eps) * 100) if (fwd_eps and eps) else None
    div = info.get("dividendYield")
    return {
        "현재가": price,
        "PER": info.get("trailingPE"),
        "Fwd PER": info.get("forwardPE"),
        "PBR": info.get("priceToBook"),
        "PEG": info.get("pegRatio") or info.get("trailingPegRatio"),
        "EPS": eps,
        "Fwd EPS": fwd_eps,
        "EPS성장%": eps_growth,
        "배당%": pct(div) if div is not None else None,
        "52주최고": info.get("fiftyTwoWeekHigh"),
        "52주최저": info.get("fiftyTwoWeekLow"),
        "애널목표가": info.get("targetMeanPrice"),
    }

def resolve_values(item: dict, live: dict):
    """Merge live-fetched values with manual overrides. Override wins."""
    overrides = item.get("overrides", {})
    resolved, is_override = {}, {}
    for col in EDITABLE_COLS:
        ov = overrides.get(col)
        if ov is not None:
            resolved[col] = ov
            is_override[col] = True
        else:
            resolved[col] = live.get(col)
            is_override[col] = False
    return resolved, is_override

def build_row(item: dict):
    info = fetch_one(item["ticker"], item.get("market", "US"))
    error = "_error" in info
    live = {} if error else compute_live(info)
    resolved, is_override = resolve_values(item, live)

    price = resolved.get("현재가")
    prev = info.get("previousClose")
    chg = ((price - prev) / prev * 100) if (price and prev) else None

    eps = resolved.get("EPS")
    fair_per = resolved.get("적정PER")
    my_tgt = fair_per * eps if (fair_per and eps) else None

    tgt = resolved.get("애널목표가")
    upside_an = ((tgt / price - 1) * 100) if (tgt and price) else None
    upside_my = ((my_tgt / price - 1) * 100) if (my_tgt and price) else None

    mcap = info.get("marketCap")
    mcap_str = f"{mcap/1e12:.2f}T" if mcap and mcap > 1e12 else (f"{mcap/1e9:.1f}B" if mcap else None)

    row = {
        "국가": "🇰🇷" if item.get("market") == "KR" else "🇺🇸",
        "종목": item.get("name", item["ticker"]),
        "티커": item["ticker"],
        "등락%": chg,
        "시총": mcap_str,
        "애널상승%": upside_an,
        "내목표가": my_tgt,
        "내상승%": upside_my,
        **resolved,
    }
    return row, is_override, error

# ---------- AgGrid helpers ----------
def _js_fmt(decimals=2, signed=False):
    sign_prefix = "(v >= 0 ? '+' : '') + " if signed else ""
    return JsCode(f"""
    function(params) {{
        var v = params.value;
        if (v === null || v === undefined || isNaN(v)) return '—';
        var s = Number(v).toLocaleString(undefined, {{minimumFractionDigits: {decimals}, maximumFractionDigits: {decimals}}});
        return {sign_prefix}s;
    }}
    """)

def _js_cellstyle(col_key):
    return JsCode(f"""
    function(params) {{
        if (params.data['_ov_{col_key}']) {{
            return {{backgroundColor: '#fff3b0'}};
        }}
        return {{}};
    }}
    """)

COLUMN_FORMATS = {
    "현재가": (2, False), "PER": (1, False), "Fwd PER": (1, False),
    "PBR": (2, False), "PEG": (2, False), "EPS": (2, False), "Fwd EPS": (2, False),
    "EPS성장%": (1, True), "배당%": (2, False), "등락%": (2, True),
    "52주최고": (2, False), "52주최저": (2, False),
    "애널목표가": (2, False), "애널상승%": (1, True),
    "적정PER": (1, False), "내목표가": (2, False), "내상승%": (1, True),
}

COLUMN_ORDER = [
    "국가", "종목", "티커", "현재가", "등락%", "시총",
    "PER", "Fwd PER", "PBR", "PEG", "EPS", "Fwd EPS", "EPS성장%", "배당%",
    "52주최고", "52주최저", "애널목표가", "애널상승%",
    "적정PER", "내목표가", "내상승%",
]

def render_table(items, title, empty_msg, table_key):
    st.subheader(title)
    if not items:
        st.info(empty_msg)
        return

    rows, flags, errors = [], [], []
    for it in items:
        row, is_override, error = build_row(it)
        rows.append(row)
        flags.append(is_override)
        if error:
            errors.append(row["종목"])

    if errors:
        st.warning(f"데이터를 불러오지 못한 종목: {', '.join(errors)}")

    df = pd.DataFrame(rows)[COLUMN_ORDER]
    for col in EDITABLE_COLS:
        df[f"_ov_{col}"] = [f.get(col, False) for f in flags]

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, filter=False, sortable=True)
    for col in COLUMN_ORDER:
        if col in ("국가", "종목", "티커", "시총"):
            gb.configure_column(col, editable=False)
            continue
        decimals, signed = COLUMN_FORMATS[col]
        editable = col in EDITABLE_COLS
        kwargs = dict(
            editable=editable,
            type=["numericColumn"],
            valueFormatter=_js_fmt(decimals, signed),
        )
        if editable:
            kwargs["cellStyle"] = _js_cellstyle(col)
        gb.configure_column(col, **kwargs)
    for col in EDITABLE_COLS:
        gb.configure_column(f"_ov_{col}", hide=True)

    grid_options = gb.build()
    response = AgGrid(
        df, gridOptions=grid_options, key=f"aggrid_{table_key}",
        update_mode=GridUpdateMode.VALUE_CHANGED,
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True, fit_columns_on_grid_load=True,
        height=min(60 + 42 * len(rows), 480),
    )
    st.caption("🟨 노란색 셀 = 수기 입력값 · 셀을 더블클릭하면 직접 수정할 수 있습니다.")

    edited = response["data"]
    changed = False
    for i, item in enumerate(items):
        overrides = item.setdefault("overrides", {})
        for col in EDITABLE_COLS:
            old_val = df.iloc[i][col]
            new_val = edited.iloc[i][col]
            old_num = None if pd.isna(old_val) else float(old_val)
            new_num = None if pd.isna(new_val) else float(new_val)
            if new_num != old_num:
                if new_num is None:
                    overrides.pop(col, None)
                else:
                    overrides[col] = new_num
                changed = True
    if changed:
        save_config(cfg)
        st.rerun()

def run_automation(cfg):
    """실시간으로 가져올 수 있는 값은 자동값으로 되돌리고,
    가져올 수 없는 값은 수기입력값을 그대로 남긴다."""
    st.cache_data.clear()
    for key in ("portfolio", "watchlist"):
        for item in cfg[key]:
            info = fetch_one(item["ticker"], item.get("market", "US"))
            if "_error" in info:
                continue
            live = compute_live(info)
            overrides = item.get("overrides", {})
            for col in EDITABLE_COLS:
                if live.get(col) is not None and col in overrides:
                    del overrides[col]
    save_config(cfg)
    st.rerun()

# ---------- Chart ----------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_history(ticker: str, market: str, period: str) -> pd.DataFrame:
    yf_symbol = f"{ticker}.KS" if market == "KR" else ticker
    try:
        return yf.Ticker(yf_symbol).history(period=period, interval="1wk")
    except Exception:
        return pd.DataFrame()

def render_chart_section(cfg):
    st.subheader("📈 주간 차트")
    items = cfg["portfolio"] + cfg["watchlist"]
    if not items:
        st.info("왼쪽 사이드바에서 종목을 추가하면 차트를 볼 수 있습니다.")
        return

    options = {f"{it.get('name', it['ticker'])} ({it['ticker']})": it for it in items}
    c1, c2 = st.columns([2, 1])
    with c1:
        label = st.selectbox("종목 선택", list(options.keys()))
    with c2:
        period_map = {"6개월": "6mo", "1년": "1y", "3년": "3y", "5년": "5y"}
        period_label = st.radio("기간", list(period_map.keys()), index=1, horizontal=True)

    item = options[label]
    df = fetch_history(item["ticker"], item.get("market", "US"), period_map[period_label])
    if df.empty:
        st.warning("차트 데이터를 불러오지 못했습니다.")
        return

    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name=item["ticker"],
    )])
    fig.update_layout(
        xaxis_rangeslider_visible=False, height=450,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------- Sidebar: manage stocks ----------
cfg = load_config()

with st.sidebar:
    st.header("⚙️ 종목 관리")
    if _github_token():
        st.caption("☁️ 클라우드 자동저장 켜짐")
    else:
        st.caption("💾 로컬 저장만 (재시작 시 초기화될 수 있음)")

    show_watchlist = st.toggle("👀 관심종목 탭 보이기", value=st.session_state.get("show_watchlist", True))
    st.session_state["show_watchlist"] = show_watchlist

    tab_labels = ["포트폴리오", "관심종목"] if show_watchlist else ["포트폴리오"]
    tabs = st.tabs(tab_labels)
    tab_defs = [(tabs[0], "portfolio", "포트폴리오")]
    if show_watchlist:
        tab_defs.append((tabs[1], "watchlist", "관심종목"))

    for tab, key, label in tab_defs:
        with tab:
            for i, item in enumerate(cfg[key]):
                with st.container(border=True):
                    st.markdown(f"**{item.get('name', item['ticker'])}** `{item['ticker']}` ({item.get('market','US')})")
                    if st.button("🗑 삭제", key=f"del_{key}_{i}"):
                        cfg[key].pop(i)
                        save_config(cfg)
                        st.rerun()

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
                                "overrides": {"적정PER": fp} if fp > 0 else {},
                            })
                            save_config(cfg)
                            st.rerun()

# ---------- Main ----------
st.title("📊 챠니의 주식 check~♬")

c1, c2, c3 = st.columns([1, 1, 4])
with c1:
    if st.button("🔄 새로고침", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with c2:
    if st.button("🤖 정보 자동화", use_container_width=True,
                 help="실시간으로 가져올 수 있는 값은 최신값으로 되돌리고, 가져올 수 없는 값은 수기입력값을 유지합니다."):
        run_automation(cfg)
with c3:
    st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 시세 캐시 5분")

render_table(cfg["portfolio"], "💼 포트폴리오", "왼쪽 사이드바에서 종목을 추가하세요.", "portfolio")
if st.session_state.get("show_watchlist", True):
    st.divider()
    render_table(cfg["watchlist"], "👀 관심종목", "왼쪽 사이드바에서 종목을 추가하세요.", "watchlist")

st.divider()
render_chart_section(cfg)

with st.expander("ℹ️ 데이터 안내"):
    st.markdown("""
- **데이터 출처**: Yahoo Finance (yfinance 라이브러리, 무료)
- **한국 종목** 티커는 6자리 숫자 (예: 삼성전자 `005930`, SK하이닉스 `000660`)
- **표 편집**: 노란색 셀은 수기 입력값입니다. 셀을 더블클릭하면 값을 직접 수정할 수 있습니다.
- **정보 자동화 버튼**: 실시간으로 가져올 수 있는 값은 최신값으로 되돌리고, Yahoo Finance에서 제공하지 않는 값(수기입력값)은 그대로 남깁니다.
- **적정PER × EPS = 내 목표가**, **내 목표가 / 현재가 - 1 = 내 상승여력**
- 지연 시간: Yahoo Finance 무료 데이터는 15~20분 지연 가능
""")
