from __future__ import annotations

import base64
import hmac
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests

import pandas as pd
import streamlit as st

from lotto_core import (
    DEFAULT_WEIGHTS,
    build_score_table,
    fetch_lotto_history,
    generate_portfolio,
    parse_uploaded_csv,
)

st.set_page_config(
    page_title="로또 5게임 분산 생성기",
    page_icon="🎯",
    layout="centered",
)

st.title("로또 5게임 분산 생성기")
st.caption(
    "전체 누적 + 최근 1년 + 최근 20회 출현빈도를 합산하고, "
    "5게임 사이에서 같은 번호가 반복될수록 패널티를 적용합니다."
)

with st.sidebar:
    st.header("점수 가중치")
    all_w = st.slider("전체 누적", 0, 100, int(DEFAULT_WEIGHTS["all"] * 100), 5)
    year_w = st.slider("최근 1년", 0, 100, int(DEFAULT_WEIGHTS["year"] * 100), 5)
    recent_w = st.slider("최근 20회", 0, 100, int(DEFAULT_WEIGHTS["recent20"] * 100), 5)

    total = all_w + year_w + recent_w
    if total == 0:
        st.warning("가중치 합계가 0일 수는 없습니다.")
        st.stop()

    weights = {
        "all": all_w / total,
        "year": year_w / total,
        "recent20": recent_w / total,
    }

    st.divider()
    st.header("게임 간 중복")
    repeat_factor = st.slider(
        "같은 번호 재사용 배율",
        min_value=0.05,
        max_value=1.00,
        value=0.25,
        step=0.05,
        help=(
            "한 번 사용된 번호의 다음 게임 선택 점수에 곱하는 값입니다. "
            "0.25면 두 번째 사용 시 점수가 25%로 감소합니다."
        ),
    )
    max_usage = st.selectbox(
        "번호당 최대 사용 게임 수",
        options=[1, 2, 3],
        index=1,
        help="1이면 5게임 전체 30개 자리를 모두 서로 다른 번호로 구성합니다.",
    )
    randomness = st.slider(
        "랜덤성",
        min_value=0.00,
        max_value=0.50,
        value=0.12,
        step=0.02,
        help="0에 가까울수록 점수 순위 중심, 높을수록 결과가 다양해집니다.",
    )


def get_github_config():
    """Streamlit Secrets에서 GitHub 저장 설정을 읽습니다."""
    try:
        if "github" not in st.secrets:
            return None
        cfg = st.secrets["github"]
        required = ("token", "owner", "repo", "branch", "password")
        if any(key not in cfg or not str(cfg[key]).strip() for key in required):
            return None
        return {key: str(cfg[key]).strip() for key in required}
    except (FileNotFoundError, KeyError):
        return None


def save_weekly_csv_to_github(
    csv_bytes: bytes,
    path: str,
    commit_message: str,
    cfg: dict,
) -> tuple[bool, str]:
    """
    GitHub Contents API로 CSV를 생성/갱신합니다.
    같은 path가 이미 있으면 SHA를 읽어 update 합니다.
    """
    api_url = (
        f"https://api.github.com/repos/"
        f"{cfg['owner']}/{cfg['repo']}/contents/{path}"
    )
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lucky-lotto-streamlit",
    }

    sha = None
    check = requests.get(
        api_url,
        headers=headers,
        params={"ref": cfg["branch"]},
        timeout=15,
    )

    if check.status_code == 200:
        sha = check.json().get("sha")
    elif check.status_code != 404:
        return False, (
            f"GitHub 파일 확인 실패: HTTP {check.status_code} - "
            f"{check.text[:300]}"
        )

    payload = {
        "message": commit_message,
        "content": base64.b64encode(csv_bytes).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(
        api_url,
        headers=headers,
        json=payload,
        timeout=20,
    )

    if response.status_code not in (200, 201):
        return False, (
            f"GitHub 저장 실패: HTTP {response.status_code} - "
            f"{response.text[:500]}"
        )

    action = "갱신" if sha else "생성"
    return True, f"`{path}` 파일을 GitHub에 {action}했습니다."


@st.cache_data(ttl="1h", show_spinner=False)
def load_online_history() -> pd.DataFrame:
    return fetch_lotto_history()

source = "online"
history = None
load_error = None

try:
    with st.spinner("최신 당첨 데이터를 불러오는 중입니다..."):
        history = load_online_history()
except Exception as exc:
    load_error = str(exc)

if history is None or history.empty:
    source = "csv"
    st.error("온라인 당첨 데이터 자동 수집에 실패했습니다.")
    if load_error:
        st.code(load_error)
    st.info(
        "아래 CSV를 업로드하면 같은 방식으로 사용할 수 있습니다. "
        "필수 열: draw,date,n1,n2,n3,n4,n5,n6 (bonus는 선택)"
    )
    upload = st.file_uploader("로또 당첨 이력 CSV", type=["csv"])
    if upload is None:
        st.stop()
    history = parse_uploaded_csv(upload.getvalue())

latest = history.iloc[-1]
latest_draw = int(latest["draw"])
latest_date = pd.Timestamp(latest["date"]).date()

score_table = build_score_table(history, weights=weights)

# 상단 요약 영역: Streamlit metric 대신 고정 비율 카드로 표시
data_label = "자동 수집" if source == "online" else "CSV"

st.markdown(
    f"""
    <style>
    .lotto-summary-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin: 0.45rem 0 1.45rem 0;
    }}
    .lotto-summary-card {{
        border: 1px solid rgba(49, 51, 63, 0.16);
        border-radius: 10px;
        padding: 12px 14px;
        min-width: 0;
        background: rgba(250, 250, 250, 0.35);
    }}
    .lotto-summary-label {{
        font-size: 0.78rem;
        line-height: 1.2;
        color: rgba(49, 51, 63, 0.68);
        margin-bottom: 6px;
        white-space: nowrap;
    }}
    .lotto-summary-value {{
        font-size: 1.42rem;
        line-height: 1.2;
        font-weight: 600;
        letter-spacing: -0.02em;
        white-space: nowrap;
    }}
    .lotto-formula-note {{
        font-size: 0.92rem;
        line-height: 1.65;
        margin: 0.15rem 0 0.9rem 0;
        color: rgba(49, 51, 63, 0.88);
    }}
    @media (max-width: 700px) {{
        .lotto-summary-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
        .lotto-summary-value {{
            font-size: 1.28rem;
        }}
    }}
    </style>

    <div class="lotto-summary-grid">
        <div class="lotto-summary-card">
            <div class="lotto-summary-label">최신 회차</div>
            <div class="lotto-summary-value">{latest_draw:,}회</div>
        </div>
        <div class="lotto-summary-card">
            <div class="lotto-summary-label">최신 추첨일</div>
            <div class="lotto-summary-value">{latest_date.isoformat()}</div>
        </div>
        <div class="lotto-summary-card">
            <div class="lotto-summary-label">분석 회차</div>
            <div class="lotto-summary-value">{len(history):,}회</div>
        </div>
        <div class="lotto-summary-card">
            <div class="lotto-summary-label">데이터</div>
            <div class="lotto-summary-value">{data_label}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.subheader("현재 점수 공식")

st.latex(
    r"S(n)="
    + f"{weights['all']:.2f}A(n)+"
    + f"{weights['year']:.2f}Y(n)+"
    + f"{weights['recent20']:.2f}R_{{20}}(n)"
)
st.markdown(
    """
    <div class="lotto-formula-note">
    <b>A</b>, <b>Y</b>, <b>R20</b>은 각각
    <b>전체 누적 / 최근 1년 / 최근 20회</b>의 출현빈도를
    1-45번 내 상대 백분위 점수(0-1)로 변환한 값입니다.
    </div>
    """,
    unsafe_allow_html=True,
)

st.latex(
    r"S_{\mathrm{select}}(n)=S(n)\times "
    + f"{repeat_factor:.2f}"
    + r"^{u(n)}"
)
st.markdown(
    f"""
    <div class="lotto-formula-note">
    <b>u(n)</b>은 앞선 게임에서 해당 번호를 사용한 횟수입니다.
    현재 설정에서는 같은 번호를 최대 <b>{max_usage}게임</b>까지 사용할 수 있습니다.
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

left, right = st.columns([1.15, 0.85])

with left:
    st.subheader("이번 주 5게임")
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = None

    if st.button("5게임 생성", type="primary", use_container_width=True):
        games, meta = generate_portfolio(
            score_table,
            games=5,
            numbers_per_game=6,
            repeat_factor=repeat_factor,
            max_usage=max_usage,
            randomness=randomness,
        )
        st.session_state.portfolio = (games, meta)

    if st.session_state.portfolio is None:
        st.info("`5게임 생성` 버튼을 누르세요.")
    else:
        games, meta = st.session_state.portfolio

        game_rows = []
        for idx, game in enumerate(games, 1):
            game_rows.append(
                {
                    "게임": f"{idx}게임",
                    **{f"N{i}": n for i, n in enumerate(game, 1)},
                }
            )
        game_df = pd.DataFrame(game_rows)
        st.dataframe(game_df, hide_index=True, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("사용한 서로 다른 번호", f"{meta['unique_numbers']} / 45")
        c2.metric("중복 사용 자리", f"{meta['repeat_slots']}개")
        c3.metric("평균 기본 점수", f"{meta['mean_base_score']:.1f}")

        repeated = meta["repeated_numbers"]
        if repeated:
            repeated_text = ", ".join(
                f"{num}({count}회)" for num, count in repeated.items()
            )
            st.caption(f"중복 번호: {repeated_text}")
        else:
            st.caption("5게임 전체에서 중복 번호가 없습니다.")

        export_rows = []
        for idx, game in enumerate(games, 1):
            export_rows.append(
                {
                    "latest_draw": latest_draw,
                    "latest_date": latest_date.isoformat(),
                    "game": idx,
                    "numbers": " ".join(map(str, game)),
                }
            )
        export_df = pd.DataFrame(export_rows)

        # 저장 시점과 생성 조건도 함께 남깁니다.
        generated_date = pd.Timestamp.now(tz=ZoneInfo("Asia/Seoul")).date()
        export_df.insert(0, "generated_date", generated_date.isoformat())
        export_df["all_weight"] = round(weights["all"], 4)
        export_df["year_weight"] = round(weights["year"], 4)
        export_df["recent20_weight"] = round(weights["recent20"], 4)
        export_df["repeat_factor"] = repeat_factor
        export_df["max_usage"] = max_usage
        export_df["randomness"] = randomness

        csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
        iso_year, iso_week, _ = generated_date.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        weekly_filename = f"{week_key}_based_on_draw_{latest_draw}.csv"
        github_path = f"history/{weekly_filename}"

        dl_col, git_col = st.columns(2)

        with dl_col:
            st.download_button(
                "이번 주 번호 CSV 저장",
                data=csv_bytes,
                file_name=weekly_filename,
                mime="text/csv",
                use_container_width=True,
            )

        with git_col:
            github_cfg = get_github_config()

            if github_cfg is None:
                st.button(
                    "GitHub에 저장",
                    disabled=True,
                    use_container_width=True,
                    help="Streamlit Secrets에 GitHub 설정을 먼저 등록해야 합니다.",
                )
            else:
                save_password = st.text_input(
                    "GitHub 저장 비밀번호",
                    type="password",
                    key="github_save_password",
                    placeholder="저장 비밀번호",
                    label_visibility="collapsed",
                )

                if st.button(
                    "GitHub에 저장",
                    use_container_width=True,
                    type="secondary",
                ):
                    if not hmac.compare_digest(
                        save_password,
                        github_cfg["password"],
                    ):
                        st.error("저장 비밀번호가 맞지 않습니다.")
                    else:
                        commit_message = (
                            f"Save lotto games for {week_key} "
                            f"(based on draw {latest_draw})"
                        )
                        try:
                            ok, message = save_weekly_csv_to_github(
                                csv_bytes=csv_bytes,
                                path=github_path,
                                commit_message=commit_message,
                                cfg=github_cfg,
                            )
                        except requests.RequestException as exc:
                            ok = False
                            message = f"GitHub 연결 오류: {exc}"

                        if ok:
                            st.success(message)
                        else:
                            st.error(message)

with right:
    st.subheader("번호 점수 TOP 15")
    top = score_table.sort_values(
        ["score", "year_count", "recent20_count", "all_count"],
        ascending=False,
    ).head(15).copy()

    show = top[
        [
            "number",
            "score",
            "all_count",
            "year_count",
            "recent20_count",
        ]
    ].rename(
        columns={
            "number": "번호",
            "score": "종합점수",
            "all_count": "전체",
            "year_count": "최근1년",
            "recent20_count": "최근20회",
        }
    )
    show["종합점수"] = show["종합점수"].round(1)
    st.dataframe(show, hide_index=True, use_container_width=True)

st.divider()

with st.expander("전체 1~45 번호 통계 보기"):
    full = score_table.sort_values("number").copy()
    display = full[
        [
            "number",
            "score",
            "all_count",
            "year_count",
            "recent20_count",
            "all_percentile",
            "year_percentile",
            "recent20_percentile",
        ]
    ].rename(
        columns={
            "number": "번호",
            "score": "종합점수",
            "all_count": "전체횟수",
            "year_count": "1년횟수",
            "recent20_count": "20회횟수",
            "all_percentile": "전체백분위",
            "year_percentile": "1년백분위",
            "recent20_percentile": "20회백분위",
        }
    )
    for col in ["종합점수", "전체백분위", "1년백분위", "20회백분위"]:
        display[col] = display[col].round(2)
    st.dataframe(display, hide_index=True, use_container_width=True)

st.caption(
    "주의: 이 점수는 과거 출현빈도를 이용한 선택 규칙이며, "
    "공정한 로또 추첨에서 특정 조합의 실제 1등 확률을 높인다는 의미는 아닙니다."
)
