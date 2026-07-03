# 나만의 주식 대시보드

**엔비디아 · 마이크론 · 팔란티어 · 삼성전자 · SK하이닉스** 5개 종목으로 시작하는 개인 대시보드.
새로고침 버튼 한 번으로 PER, Fwd PER, PBR, EPS, 배당수익률, 애널리스트 목표주가, 상승여력까지 표로 정리됩니다.

## 지금 바로 실행 (내 PC)

```bash
# 1. 파이썬 설치되어 있다는 가정
pip install -r requirements.txt

# 2. 실행 (브라우저가 자동으로 열림)
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 이 열리면 성공. 사이드바에서 종목을 추가/삭제하고, 각 종목의 **적정PER**을 입력하면 **내 목표가**와 **내 상승여력**이 자동으로 계산됩니다.

## 폰에서도 보기 (다음 단계)

로컬 실행만으로는 폰에서 안 보입니다. 두 가지 무료 옵션:

### 옵션 A: Streamlit Community Cloud (추천)
1. GitHub에 이 세 파일(`app.py`, `config.json`, `requirements.txt`)을 새 저장소로 올림
2. https://share.streamlit.io 에 GitHub 계정으로 로그인
3. "New app" → 저장소 선택 → 배포 (3~5분)
4. `https://내이름-대시보드.streamlit.app` 같은 주소가 생김 → 폰 브라우저 즐겨찾기

**주의**: 공개 저장소는 누구나 볼 수 있음. 개인 데이터라면 저장소를 private로 만들거나 Streamlit의 비밀번호 기능(secrets)을 추가하세요.

### 클라우드 자동저장 설정 (선택, 추천)

Streamlit Cloud는 앱이 재시작될 때마다 GitHub의 코드 상태로 초기화되므로, 배포된 사이트에서 사이드바로 종목을 추가/수정해도 기본적으로는 다음 재시작 때 사라집니다. 이를 막으려면 앱이 변경사항을 GitHub에 직접 커밋하도록 토큰을 설정하세요.

1. GitHub → 우측 상단 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens** → "Generate new token"
2. Repository access를 `stock-tracking` 저장소로 제한, Permissions에서 **Contents: Read and write** 부여
3. 생성된 토큰(`github_pat_...`) 복사
4. Streamlit Cloud 앱 페이지 → 우측 하단 **⋮ → Settings → Secrets** 에 다음 입력:
   ```
   GITHUB_TOKEN = "여기에_토큰_붙여넣기"
   ```
5. 저장 후 앱 재시작 → 사이드바에 "☁️ 클라우드 자동저장 켜짐" 표시되면 성공

### 옵션 B: 집 컴퓨터 + Tailscale
집 PC에서 streamlit을 계속 돌리고, Tailscale VPN으로 폰에서 접속. 무료. 이 방식이 궁금하시면 Claude Code에 부탁하세요.

## Claude Code로 이어서 하기

여기서 만든 파일들을 다운로드하신 뒤 Claude Code를 열고 이렇게 부탁하시면 됩니다:

> "이 폴더에 있는 Streamlit 앱을 Streamlit Community Cloud에 배포하고 싶어. GitHub 저장소 만드는 것부터 배포까지 도와줘."

또는:

> "이 앱에 [원하는 기능]을 추가해줘." (예: 알림, 차트, 종목별 뉴스 등)

## 데이터 관련 안내

- **데이터 출처**: Yahoo Finance (yfinance 라이브러리) — 무료, API 키 불필요
- **지연**: 무료 데이터는 15~20분 지연될 수 있음 (실시간 아님)
- **한국 종목 한계**: 삼성전자·SK하이닉스 같은 대형주는 Forward PER, 애널리스트 목표주가가 나오지만 중소형주는 값이 비어있을 수 있음
- **적정PER**: 종목마다 수기 입력. 값 × 후행 EPS = 내 목표가
