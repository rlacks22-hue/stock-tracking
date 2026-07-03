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
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, DataReturnMode
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
    "EPS성장%", "52주최고", "52주최저", "애널목표가", "적정PER",
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
        cfg = {}

    if "groups" not in cfg:
        # 예전 portfolio/watchlist 구조 → 자유 그룹 구조로 마이그레이션
        groups = []
        if cfg.get("portfolio"):
            groups.append({"name": "포폴1", "items": cfg["portfolio"]})
        if cfg.get("watchlist"):
            groups.append({"name": "관심종목", "items": cfg["watchlist"]})
        if not groups:
            groups = [{"name": "포폴1", "items": []}]
        cfg = {"groups": groups}

    for g in cfg["groups"]:
        g["items"] = [_migrate_item(it) for it in g.get("items", [])]
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

def compute_live(info: dict) -> dict:
    """Values yfinance can actually provide right now. None = not fetchable."""
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    eps = info.get("trailingEps")
    fwd_eps = info.get("forwardEps")
    eps_growth = ((fwd_eps - eps) / abs(eps) * 100) if (fwd_eps and eps) else None
    return {
        "현재가": price,
        "PER": info.get("trailingPE"),
        "Fwd PER": info.get("forwardPE"),
        "PBR": info.get("priceToBook"),
        "PEG": info.get("pegRatio") or info.get("trailingPegRatio"),
        "EPS": eps,
        "Fwd EPS": fwd_eps,
        "EPS성장%": eps_growth,
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

    row = {
        "종목": item.get("name", item["ticker"]),
        "티커": item["ticker"],
        "등락%": chg,
        "애널상승%": upside_an,
        "내목표가": my_tgt,
        "상승여력": upside_my,
        **resolved,
    }
    return row, is_override, error

# ---------- AgGrid helpers ----------
UP_TEXT = "#e03131"    # 상승 = 빨간 글씨
DOWN_TEXT = "#1971c2"  # 하락 = 파란 글씨
POS_BG = "#d3f9d8"     # 상승여력 + = 연두색
NEG_BG = "#ffe3e9"     # 상승여력 - = 분홍색

def _js_fmt(decimals=2, signed=False, market_aware=False, percent=False):
    sign_prefix = "(v >= 0 ? '+' : '') + " if signed else ""
    unit = "'%'" if percent else "''"
    decimals_expr = (
        f"(params.data && params.data['_market'] === 'KR' ? 0 : {decimals})"
        if market_aware else str(decimals)
    )
    return JsCode(f"""
    function(params) {{
        var v = params.value;
        if (v === null || v === undefined || isNaN(v)) return '—';
        var d = {decimals_expr};
        var s = Number(v).toLocaleString(undefined, {{minimumFractionDigits: d, maximumFractionDigits: d}});
        return {sign_prefix}s + {unit};
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

def _js_text_color(pos_color, neg_color):
    return JsCode(f"""
    function(params) {{
        var v = params.value;
        if (v === null || v === undefined || isNaN(v)) return {{}};
        return {{color: v >= 0 ? '{pos_color}' : '{neg_color}'}};
    }}
    """)

def _js_bg_color(pos_color, neg_color):
    return JsCode(f"""
    function(params) {{
        var v = params.value;
        if (v === null || v === undefined || isNaN(v)) return {{}};
        return {{backgroundColor: v >= 0 ? '{pos_color}' : '{neg_color}'}};
    }}
    """)

COLUMN_FORMATS = {
    "현재가": (2, False), "PER": (1, False), "Fwd PER": (1, False),
    "PBR": (2, False), "PEG": (2, False), "EPS": (2, False), "Fwd EPS": (2, False),
    "EPS성장%": (1, True), "등락%": (2, True),
    "52주최고": (2, False), "52주최저": (2, False),
    "애널목표가": (2, False), "애널상승%": (1, True),
    "적정PER": (1, False), "내목표가": (2, False), "상승여력": (1, True),
}

# 원화는 소수점을 쓰지 않으므로 KR 종목은 이 컬럼들만 정수로 표시
PRICE_COLS = {"현재가", "52주최고", "52주최저", "애널목표가", "내목표가"}

COLUMN_ORDER = [
    "종목", "티커", "현재가", "등락%",
    "PER", "Fwd PER", "PBR", "PEG", "EPS", "Fwd EPS", "EPS성장%",
    "52주최고", "52주최저", "애널목표가", "애널상승%",
    "적정PER", "내목표가", "상승여력",
]

def render_table(items, empty_msg, table_key):
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
    df["_market"] = [it.get("market", "US") for it in items]

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, filter=False, sortable=True)
    gb.configure_grid_options(rowDragManaged=True, animateRows=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False, suppressRowClickSelection=False)
    for col in COLUMN_ORDER:
        if col in ("종목", "티커"):
            gb.configure_column(col, editable=False, rowDrag=(col == "종목"))
            continue
        decimals, signed = COLUMN_FORMATS[col]
        editable = col in EDITABLE_COLS
        kwargs = dict(
            editable=editable,
            type=["numericColumn"],
            valueFormatter=_js_fmt(
                decimals, signed,
                market_aware=(col in PRICE_COLS), percent=(col == "상승여력"),
            ),
        )
        if editable:
            kwargs["cellStyle"] = _js_cellstyle(col)
        elif col == "등락%":
            kwargs["cellStyle"] = _js_text_color(UP_TEXT, DOWN_TEXT)
        elif col == "상승여력":
            kwargs["cellStyle"] = _js_bg_color(POS_BG, NEG_BG)
        gb.configure_column(col, **kwargs)
    for col in EDITABLE_COLS:
        gb.configure_column(f"_ov_{col}", hide=True)
    gb.configure_column("_market", hide=True)

    grid_options = gb.build()
    response = AgGrid(
        df, gridOptions=grid_options, key=f"aggrid_{table_key}",
        update_on=["cellValueChanged", "rowDragEnd", "selectionChanged"],
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True, fit_columns_on_grid_load=True,
        reload_data=True,
        height=min(60 + 42 * len(rows), 480),
    )
    st.caption("🟨 노란색 셀 = 수기 입력값 · 더블클릭하면 직접 수정 · 종목명을 드래그하면 순서를 바꿀 수 있습니다 · 행을 클릭하면 아래 차트가 바뀝니다.")

    selected = response.selected_data
    if selected is not None and not selected.empty:
        srow = selected.iloc[0]
        st.session_state["chart_stock_select"] = f"{srow['종목']} ({srow['티커']})"

    edited = response["data"]
    ticker_to_item = {it["ticker"]: it for it in items}
    old_rows_by_ticker = {r["티커"]: r for r in df.to_dict("records")}

    changed = False
    for _, erow in edited.iterrows():
        item = ticker_to_item.get(erow["티커"])
        if item is None:
            continue
        overrides = item.setdefault("overrides", {})
        old_row = old_rows_by_ticker.get(erow["티커"], {})
        for col in EDITABLE_COLS:
            old_val = old_row.get(col)
            new_val = erow[col]
            old_num = None if (old_val is None or pd.isna(old_val)) else float(old_val)
            new_num = None if pd.isna(new_val) else float(new_val)
            if new_num != old_num:
                if new_num is None:
                    overrides.pop(col, None)
                else:
                    overrides[col] = new_num
                changed = True

    new_order = list(edited["티커"])
    old_order = list(df["티커"])
    if new_order != old_order and set(new_order) == set(old_order):
        order_index = {t: i for i, t in enumerate(new_order)}
        items.sort(key=lambda it: order_index.get(it["ticker"], 0))
        changed = True

    if changed:
        save_config(cfg)
        st.rerun()

def run_automation(cfg):
    """실시간으로 가져올 수 있는 값은 자동값으로 되돌리고,
    가져올 수 없는 값은 수기입력값을 그대로 남긴다."""
    st.cache_data.clear()
    for group in cfg["groups"]:
        for item in group["items"]:
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
PERIOD_OPTIONS = {
    "1d": ("1d", "5m"),
    "1w": ("7d", "30m"),
    "1m": ("1mo", "1d"),
    "3m": ("3mo", "1d"),
    "6m": ("6mo", "1wk"),
    "1y": ("1y", "1wk"),
    "3y": ("3y", "1wk"),
    "5y": ("5y", "1wk"),
}
UP_COLOR = "#e74c3c"    # 상승 = 빨간색
DOWN_COLOR = "#2980b9"  # 하락 = 파란색

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_history(ticker: str, market: str, period: str, interval: str) -> pd.DataFrame:
    yf_symbol = f"{ticker}.KS" if market == "KR" else ticker
    try:
        return yf.Ticker(yf_symbol).history(period=period, interval=interval)
    except Exception:
        return pd.DataFrame()

def render_chart_section(cfg):
    st.subheader("📈 차트")
    items = [it for g in cfg["groups"] for it in g["items"]]
    if not items:
        st.info("왼쪽 사이드바에서 종목을 추가하면 차트를 볼 수 있습니다.")
        return

    options = {f"{it.get('name', it['ticker'])} ({it['ticker']})": it for it in items}
    if st.session_state.get("chart_stock_select") not in options:
        st.session_state["chart_stock_select"] = list(options.keys())[0]
    c1, c2 = st.columns([2, 1])
    with c1:
        label = st.selectbox("종목 선택", list(options.keys()), key="chart_stock_select")
    with c2:
        period_label = st.radio("기간", list(PERIOD_OPTIONS.keys()), index=5, horizontal=True)

    item = options[label]
    period, interval = PERIOD_OPTIONS[period_label]
    df = fetch_history(item["ticker"], item.get("market", "US"), period, interval)
    if df.empty:
        st.warning("차트 데이터를 불러오지 못했습니다.")
        return

    ref_key = f"chart_ref_{item['ticker']}_{period_label}"
    ref = st.session_state.get(ref_key)
    cur_price = float(df["Close"].iloc[-1])

    # 장 마감/주말 등 거래 없는 구간이 빈 칸으로 끊겨 보이지 않도록
    # 날짜/시간축을 카테고리(문자열) 축으로 그린다.
    label_fmt = "%m-%d %H:%M" if interval in ("5m", "30m") else "%Y-%m-%d"
    x_labels = df.index.strftime(label_fmt)

    fig = go.Figure(data=[
        go.Candlestick(
            x=x_labels, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name=item["ticker"],
            increasing_line_color=UP_COLOR, increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR, decreasing_fillcolor=DOWN_COLOR,
        ),
        go.Scatter(
            x=x_labels, y=df["Close"], mode="markers",
            marker=dict(size=10, opacity=0), name="", hoverinfo="skip", showlegend=False,
        ),
    ])
    if ref:
        chg = (cur_price / ref["y"] - 1) * 100
        fig.add_hline(
            y=ref["y"], line_dash="dot", line_color="#888",
            annotation_text=f"{ref['x']} · {ref['y']:,.2f} 대비 {chg:+.2f}%",
            annotation_position="top left",
        )
    fig.update_layout(
        xaxis_rangeslider_visible=False, height=450,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_type="category",
    )
    fig.update_xaxes(nticks=12)
    event = st.plotly_chart(
        fig, use_container_width=True, on_select="rerun", selection_mode="points",
        key=f"chart_widget_{item['ticker']}_{period_label}",
    )

    points = (event.get("selection") or {}).get("points") if event else None
    if points:
        pt = points[0]
        new_ref = {"x": str(pt["x"]), "y": float(pt["y"])}
        if new_ref != ref:
            st.session_state[ref_key] = new_ref
            st.rerun()

    if ref:
        chg = (cur_price / ref["y"] - 1) * 100
        st.caption(f"📍 선택 시점({ref['x']}) 종가 {ref['y']:,.2f} → 현재가 {cur_price:,.2f} ({chg:+.2f}%)")
        if st.button("선택 해제", key=f"clear_{ref_key}"):
            del st.session_state[ref_key]
            st.rerun()
    else:
        st.caption("💡 차트 위의 한 지점을 클릭하면 그 시점 대비 현재가 등락률을 볼 수 있습니다.")

# ---------- Sidebar: manage groups & stocks ----------
cfg = load_config()
group_names = [g["name"] for g in cfg["groups"]]

# active_group 위젯이 이미 생성된 뒤에는 st.session_state["active_group"]를
# 직접 바꿀 수 없으므로, pending 값을 위젯 생성 "전"에 반영한다.
if "pending_active_group" in st.session_state:
    st.session_state["active_group"] = st.session_state.pop("pending_active_group")

if st.session_state.get("active_group") not in group_names:
    st.session_state["active_group"] = group_names[0]

with st.sidebar:
    st.header("⚙️ 종목 관리")
    if _github_token():
        st.caption("☁️ 클라우드 자동저장 켜짐")
    else:
        st.caption("💾 로컬 저장만 (재시작 시 초기화될 수 있음)")

    active_name = st.radio("포트폴리오 선택", group_names, key="active_group")
    active_idx = group_names.index(active_name)
    group = cfg["groups"][active_idx]

    for i, item in enumerate(group["items"]):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"**{item.get('name', item['ticker'])}** `{item['ticker']}` ({item.get('market','US')})")
        with c2:
            if st.button("🗑", key=f"del_{active_idx}_{i}"):
                group["items"].pop(i)
                save_config(cfg)
                st.rerun()

    with st.expander(f"➕ {active_name}에 종목 추가"):
        with st.form(f"add_{active_idx}", clear_on_submit=True):
            t = st.text_input("티커 (예: NVDA, 005930)")
            n = st.text_input("표시할 이름 (예: 엔비디아)")
            m = st.radio("시장", ["US", "KR"], horizontal=True, key=f"m_{active_idx}")
            fp = st.number_input("적정PER (없으면 0)", value=0.0, step=0.5, format="%.1f")
            if st.form_submit_button("추가"):
                if t.strip():
                    group["items"].append({
                        "ticker": t.strip().upper() if m == "US" else t.strip(),
                        "name": n.strip() or t.strip(),
                        "market": m,
                        "overrides": {"적정PER": fp} if fp > 0 else {},
                    })
                    save_config(cfg)
                    st.rerun()

    st.divider()
    with st.expander("📁 그룹(포폴) 관리"):
        new_name = st.text_input("이름 변경", value=active_name, key=f"rename_{active_idx}")
        if st.button("이름 저장", key=f"rename_btn_{active_idx}"):
            new_name = new_name.strip()
            if new_name and new_name != active_name and new_name not in group_names:
                group["name"] = new_name
                save_config(cfg)
                st.session_state["pending_active_group"] = new_name
                st.rerun()

        if len(cfg["groups"]) > 1:
            if st.button(f"🗑 '{active_name}' 그룹 전체 삭제"):
                cfg["groups"].pop(active_idx)
                save_config(cfg)
                st.session_state["pending_active_group"] = cfg["groups"][0]["name"]
                st.rerun()
        else:
            st.caption("그룹이 하나뿐이면 삭제할 수 없습니다.")

        st.markdown("---")
        with st.form("add_group", clear_on_submit=True):
            new_group_name = st.text_input("새 그룹 이름 (예: 포폴2)")
            if st.form_submit_button("➕ 그룹 추가"):
                new_group_name = new_group_name.strip()
                if new_group_name and new_group_name not in group_names:
                    cfg["groups"].append({"name": new_group_name, "items": []})
                    save_config(cfg)
                    st.session_state["pending_active_group"] = new_group_name
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

st.subheader(f"💼 {active_name}")
render_table(group["items"], "왼쪽 사이드바에서 종목을 추가하세요.", f"group_{active_idx}")

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
