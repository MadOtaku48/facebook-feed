# Facebook Friend Feed

Facebook 친구들의 최신 포스팅을 자동 수집하여 Tailscale 네트워크에서 열람할 수 있는 피드 시스템.

## 구성

| 파일 | 설명 |
|------|------|
| `fb_friend_posts.py` | 크롤러 - Playwright headless로 친구 프로필 방문 → 최신 글 수집 |
| `fb_server.py` | 웹 서버 - 피드 HTML 서빙 + 친구 관리 UI + 수동 크롤링 |
| `friends.json` | 트래킹 대상 친구 목록 (**gitignore 대상**) |

## 설치

```bash
# Playwright 설치
pip install playwright
playwright install chromium

# 첫 실행 (브라우저 띄워서 Facebook 로그인)
python3 fb_friend_posts.py --login
```

## 사용법

### 크롤링
```bash
python3 fb_friend_posts.py           # headless 실행
python3 fb_friend_posts.py --login   # 로그인 필요 시 (브라우저 표시)
```

### 웹 서버
```bash
python3 fb_server.py
# 피드:  http://<tailscale-ip>:8484/
# 관리:  http://<tailscale-ip>:8484/admin
```

### 크론 (자동 수집)
```
0 10,18 * * * /path/to/python3 /path/to/fb_friend_posts.py >> /path/to/cron.log 2>&1
```

## 관리 UI (`/admin`)

- 트래킹 친구 추가/삭제/순서 변경
- 수동 크롤링 실행 (진행 상태 표시 → 완료 시 피드로 자동 이동)

## 친구 목록 (`friends.json`)

관리 UI에서 편집하거나 직접 JSON 수정:

```json
[
  {"name": "홍길동", "url": "https://www.facebook.com/username"},
  {"name": "김철수", "url": "https://www.facebook.com/profile.php?id=123456"}
]
```

- `name`: 표시 이름 (빈칸이면 크롤링 시 자동 감지)
- `url`: Facebook 프로필 URL

## 수집 기능

- 친구당 최신 포스트 5개 수집
- 본인 글만 수집 (URL 기반 필터링 - 남의 글에 댓글 단 것 제외)
- 같은 포스트 URL 중복 제거 (본문만 수집, 댓글 타임스탬프 제외)
- "더 보기" 자동 클릭하여 장문 글 전문 수집
- 포스트 이미지 다운로드 (크롤링 시 이전 이미지 자동 삭제)
- 외부 공유 링크 추출
- 댓글 수 표시
- 상단 고정 포스트 제외

## 서비스 등록 (macOS)

```bash
# 서버 상시 구동 (launchd)
cp com.fb.feed-server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.fb.feed-server.plist
```

## 주의사항

- `friends.json`, 크롤링 결과(`fb_friend_posts.*`), 이미지(`images/`)는 개인정보 포함 → `.gitignore` 처리
- Facebook 로그인 세션은 `~/.fb-scraper-profile/`에 저장
- 세션 만료 시 `--login` 으로 재로그인 필요
