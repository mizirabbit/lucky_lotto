from __future__ import annotations

from collections import Counter
from io import BytesIO
from typing import Mapping

import numpy as np
import pandas as pd
import requests

# Streamlit Community Cloud에서는 동행복권 서버가 연결 타임아웃/차단될 수 있어
# GitHub Pages의 공개 미러를 1차 데이터 소스로 사용합니다.
MIRROR_ALL_URL = "https://smok95.github.io/lotto/results/all.json"

# 동행복권 웹사이트 내부 JSON 경로 (공식 공개 API는 아님)
OFFICIAL_API_URL = "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.dhlottery.co.kr/lt645/result",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

DEFAULT_WEIGHTS = {
    "all": 0.30,
    "year": 0.40,
    "recent20": 0.30,
}

NUMBER_COLUMNS = ["n1", "n2", "n3", "n4", "n5", "n6"]


def _history_from_mirror(timeout: float = 15.0) -> pd.DataFrame:
    response = requests.get(
        MIRROR_ALL_URL,
        headers={"User-Agent": REQUEST_HEADERS["User-Agent"]},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list) or not payload:
        raise RuntimeError("미러 응답이 올바른 리스트 형식이 아닙니다.")

    rows = []
    for item in payload:
        try:
            numbers = item["numbers"]
            if not isinstance(numbers, list) or len(numbers) != 6:
                raise ValueError("numbers 형식 오류")

            row = {
                "draw": int(item["draw_no"]),
                "date": pd.to_datetime(item["date"], utc=True).tz_convert(None),
                "n1": int(numbers[0]),
                "n2": int(numbers[1]),
                "n3": int(numbers[2]),
                "n4": int(numbers[3]),
                "n5": int(numbers[4]),
                "n6": int(numbers[5]),
                "bonus": int(item["bonus_no"]),
            }
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise RuntimeError(f"알 수 없는 미러 데이터 형식: {item!r}") from exc

        _validate_row(row)
        rows.append(row)

    df = pd.DataFrame(rows)
    return (
        df.drop_duplicates(subset=["draw"], keep="last")
        .sort_values("draw")
        .reset_index(drop=True)
    )


def _history_from_official(timeout: float = 15.0) -> pd.DataFrame:
    response = requests.get(
        OFFICIAL_API_URL,
        params={"srchLtEpsd": "all"},
        headers=REQUEST_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()
    raw_list = payload.get("data", {}).get("list")
    if not isinstance(raw_list, list) or not raw_list:
        raise RuntimeError("동행복권 응답 JSON에서 data.list를 찾지 못했습니다.")

    rows = []
    for item in raw_list:
        try:
            row = {
                "draw": int(item["ltEpsd"]),
                "date": pd.to_datetime(str(item["ltRflYmd"]), format="%Y%m%d"),
                "n1": int(item["tm1WnNo"]),
                "n2": int(item["tm2WnNo"]),
                "n3": int(item["tm3WnNo"]),
                "n4": int(item["tm4WnNo"]),
                "n5": int(item["tm5WnNo"]),
                "n6": int(item["tm6WnNo"]),
                "bonus": int(item["bnsWnNo"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"알 수 없는 동행복권 데이터 형식: {item!r}") from exc

        _validate_row(row)
        rows.append(row)

    df = pd.DataFrame(rows)
    return (
        df.drop_duplicates(subset=["draw"], keep="last")
        .sort_values("draw")
        .reset_index(drop=True)
    )


def fetch_lotto_history(timeout: float = 15.0) -> pd.DataFrame:
    """
    1차: GitHub Pages 공개 미러
    2차: 동행복권 내부 JSON 경로

    Streamlit Community Cloud에서 동행복권 서버 연결이 차단/지연되는
    경우가 있어 미러를 우선 사용합니다.
    """
    errors = []

    try:
        df = _history_from_mirror(timeout=timeout)
        if not df.empty:
            return df
    except Exception as exc:
        errors.append(f"GitHub 미러 실패: {exc}")

    try:
        df = _history_from_official(timeout=timeout)
        if not df.empty:
            return df
    except Exception as exc:
        errors.append(f"동행복권 실패: {exc}")

    raise RuntimeError(" / ".join(errors))


def parse_uploaded_csv(data: bytes) -> pd.DataFrame:
    df = pd.read_csv(BytesIO(data))

    aliases = {
        "drwNo": "draw",
        "draw_no": "draw",
        "drwNoDate": "date",
        "draw_date": "date",
        "drwtNo1": "n1",
        "drwtNo2": "n2",
        "drwtNo3": "n3",
        "drwtNo4": "n4",
        "drwtNo5": "n5",
        "drwtNo6": "n6",
        "bnusNo": "bonus",
    }
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})

    required = ["draw", "date", *NUMBER_COLUMNS]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"CSV 필수 열이 없습니다: {', '.join(missing)}")

    if "bonus" not in df.columns:
        df["bonus"] = pd.NA

    df["draw"] = pd.to_numeric(df["draw"], errors="raise").astype(int)
    df["date"] = pd.to_datetime(df["date"], errors="raise")

    for col in NUMBER_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="raise").astype(int)

    for _, r in df.iterrows():
        row = {k: r[k] for k in ["draw", "date", *NUMBER_COLUMNS]}
        _validate_row(row, bonus_required=False)

    return (
        df[["draw", "date", *NUMBER_COLUMNS, "bonus"]]
        .drop_duplicates(subset=["draw"], keep="last")
        .sort_values("draw")
        .reset_index(drop=True)
    )


def _validate_row(row: Mapping, bonus_required: bool = True) -> None:
    nums = [int(row[c]) for c in NUMBER_COLUMNS]
    if len(set(nums)) != 6:
        raise ValueError(f"{row.get('draw')}회에 중복 당첨번호가 있습니다: {nums}")
    if not all(1 <= n <= 45 for n in nums):
        raise ValueError(f"{row.get('draw')}회 당첨번호 범위 오류: {nums}")

    if bonus_required:
        bonus = int(row["bonus"])
        if not 1 <= bonus <= 45:
            raise ValueError(f"{row.get('draw')}회 보너스 번호 범위 오류: {bonus}")


def _frequency(df: pd.DataFrame) -> pd.Series:
    counts = Counter()
    for col in NUMBER_COLUMNS:
        counts.update(df[col].astype(int).tolist())
    return pd.Series(
        {n: int(counts.get(n, 0)) for n in range(1, 46)},
        dtype="int64",
    )


def _percentile(values: pd.Series) -> pd.Series:
    rank = values.rank(method="average", ascending=True)
    if len(values) <= 1:
        return pd.Series(0.5, index=values.index)
    return (rank - 1.0) / (len(values) - 1.0)


def build_score_table(
    history: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    if history.empty:
        raise ValueError("당첨 이력이 비어 있습니다.")

    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    required_weights = {"all", "year", "recent20"}
    if set(weights) != required_weights:
        raise ValueError(f"가중치는 {sorted(required_weights)}만 사용해야 합니다.")

    weight_sum = sum(float(v) for v in weights.values())
    if weight_sum <= 0:
        raise ValueError("가중치 합계는 0보다 커야 합니다.")
    weights = {k: float(v) / weight_sum for k, v in weights.items()}

    ordered = history.sort_values("draw").reset_index(drop=True)
    latest_date = pd.Timestamp(ordered.iloc[-1]["date"]).normalize()

    one_year_start = latest_date - pd.Timedelta(days=365)
    one_year = ordered[ordered["date"] >= one_year_start]
    recent20 = ordered.tail(20)

    all_count = _frequency(ordered)
    year_count = _frequency(one_year)
    recent_count = _frequency(recent20)

    all_pct = _percentile(all_count)
    year_pct = _percentile(year_count)
    recent_pct = _percentile(recent_count)

    raw_score = (
        weights["all"] * all_pct
        + weights["year"] * year_pct
        + weights["recent20"] * recent_pct
    )

    out = pd.DataFrame(
        {
            "number": range(1, 46),
            "all_count": [all_count[n] for n in range(1, 46)],
            "year_count": [year_count[n] for n in range(1, 46)],
            "recent20_count": [recent_count[n] for n in range(1, 46)],
            "all_percentile": [all_pct[n] for n in range(1, 46)],
            "year_percentile": [year_pct[n] for n in range(1, 46)],
            "recent20_percentile": [recent_pct[n] for n in range(1, 46)],
            "score_raw": [raw_score[n] for n in range(1, 46)],
        }
    )

    smin = out["score_raw"].min()
    smax = out["score_raw"].max()
    if smax > smin:
        out["score"] = 100.0 * (out["score_raw"] - smin) / (smax - smin)
    else:
        out["score"] = 50.0

    return out


def generate_portfolio(
    score_table: pd.DataFrame,
    games: int = 5,
    numbers_per_game: int = 6,
    repeat_factor: float = 0.25,
    max_usage: int = 2,
    randomness: float = 0.12,
    trials: int = 600,
    seed: int | None = None,
):
    if games <= 0 or numbers_per_game <= 0:
        raise ValueError("games와 numbers_per_game은 양수여야 합니다.")
    if not 0 < repeat_factor <= 1:
        raise ValueError("repeat_factor는 0보다 크고 1 이하여야 합니다.")
    if max_usage <= 0:
        raise ValueError("max_usage는 1 이상이어야 합니다.")
    if not 0 <= randomness <= 1:
        raise ValueError("randomness는 0~1 범위여야 합니다.")
    if games * numbers_per_game > 45 * max_usage:
        raise ValueError("현재 최대 사용 횟수로는 필요한 번호 자리를 채울 수 없습니다.")

    scores = score_table.set_index("number")["score_raw"].astype(float).to_dict()
    if set(scores) != set(range(1, 46)):
        raise ValueError("score_table에는 1-45 번호가 모두 있어야 합니다.")

    rng = np.random.default_rng(seed)

    best = None
    best_obj = -np.inf

    for _ in range(max(1, trials)):
        usage = Counter()
        candidate_games = [[] for _ in range(games)]

        for _slot in range(numbers_per_game):
            order = rng.permutation(games)
            for game_idx in order:
                current = set(candidate_games[game_idx])
                candidates = [
                    n for n in range(1, 46)
                    if n not in current and usage[n] < max_usage
                ]
                if not candidates:
                    break

                adjusted = []
                for n in candidates:
                    base = max(scores[n], 1e-6)
                    value = base * (repeat_factor ** usage[n])
                    if randomness > 0:
                        value *= float(np.exp(rng.normal(0.0, randomness)))
                    adjusted.append(max(value, 1e-12))

                probs = np.asarray(adjusted, dtype=float)
                probs /= probs.sum()
                picked = int(rng.choice(candidates, p=probs))
                candidate_games[game_idx].append(picked)
                usage[picked] += 1

        if any(len(g) != numbers_per_game for g in candidate_games):
            continue

        base_sum = sum(scores[n] for g in candidate_games for n in g)
        repeat_slots = sum(max(0, c - 1) for c in usage.values())
        repeat_penalty = (1.0 - repeat_factor) * repeat_slots * 0.35
        unique_bonus = len(usage) * 0.01
        objective = base_sum - repeat_penalty + unique_bonus

        if objective > best_obj:
            best_obj = objective
            best = ([sorted(g) for g in candidate_games], usage.copy())

    if best is None:
        raise RuntimeError("게임 조합 생성에 실패했습니다.")

    games_out, usage = best
    all_selected = [n for g in games_out for n in g]
    repeated = {n: c for n, c in sorted(usage.items()) if c > 1}

    meta = {
        "unique_numbers": len(set(all_selected)),
        "repeat_slots": len(all_selected) - len(set(all_selected)),
        "repeated_numbers": repeated,
        "mean_base_score": float(
            score_table.set_index("number").loc[all_selected, "score"].mean()
        ),
    }
    return games_out, meta
