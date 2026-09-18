# 로또 5게임 분산 생성기

매주 웹에서 5게임을 만들기 위한 Streamlit 앱입니다.

## 점수 공식

각 번호 `n`에 대해:

```text
S(n) = 0.30 × A(n) + 0.40 × Y(n) + 0.30 × R20(n)
```

- `A(n)`: 전체 누적 출현빈도의 1~45 번호 내 백분위 점수
- `Y(n)`: 최근 1년 출현빈도의 백분위 점수
- `R20(n)`: 최근 20회 출현빈도의 백분위 점수

기간별 추첨 횟수가 크게 다르므로 raw 횟수를 직접 더하지 않고, 각 기간에서 번호 간 상대 순위를 `0~1`로 변환해 합산합니다.

게임 간 중복 패널티는:

```text
S_select(n) = S(n) × repeat_factor ^ usage(n)
```

기본 `repeat_factor=0.25`이므로:
- 아직 안 쓴 번호: 원래 점수 100%
- 한 번 쓴 번호: 다음 게임에서 25%
- 두 번 이상: 기본 설정에서는 후보 제외 (`max_usage=2`)

즉, 통계 점수가 높은 번호는 일부 재사용될 수 있지만 5게임 전체가 같은 상위 번호에 몰리지 않도록 합니다.

> 주의: 이 규칙은 과거 출현빈도를 이용한 선택 규칙입니다. 공정한 추첨에서 특정 조합의 실제 1등 확률을 높인다는 의미는 아닙니다.

## 실행

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

브라우저에서 표시되는 주소를 열면 됩니다.

## 데이터

기본적으로 동행복권 웹페이지가 사용하는 내부 JSON 경로를 통해 1회~최신 회차 데이터를 가져옵니다.

```text
https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd=all
```

이 경로는 공식 공개 API가 아니므로 동행복권 사이트가 변경되면 수정이 필요할 수 있습니다.

자동 수집이 실패할 경우 CSV 업로드 기능을 사용할 수 있습니다.

필수 CSV 열:

```text
draw,date,n1,n2,n3,n4,n5,n6
```

선택 열:

```text
bonus
```

## Streamlit Community Cloud 배포

1. 이 폴더를 GitHub 저장소에 올립니다.
2. Streamlit Community Cloud에서 `Create app`을 선택합니다.
3. 저장소와 `app.py`를 선택해 배포합니다.
4. 생성된 고정 URL을 북마크하면 매주 브라우저에서 바로 사용할 수 있습니다.

## 파일

- `app.py`: 웹 UI
- `lotto_core.py`: 데이터 수집, 통계, 생성 알고리즘
- `requirements.txt`: Python 패키지
