#!/usr/bin/env python3
"""
Facebook 친구 최신 포스팅 자동 수집 → JSON + HTML
- python3 fb_friend_posts.py          (headless)
- python3 fb_friend_posts.py --login  (브라우저 띄워서 로그인)
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from playwright.async_api import async_playwright

# ── 수집 대상 친구 목록 (friends.json에서 로드) ─────────
FRIENDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friends.json")

def load_friends():
    with open(FRIENDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ── 설정 ──────────────────────────────────────────────
PROFILE_DIR = os.path.expanduser("~/.fb-scraper-profile")
POSTS_PER_FRIEND = 5
LOGIN_WAIT_SEC = 120
OUTPUT_DIR = os.path.expanduser("~/facebook")
# ─────────────────────────────────────────────────────


async def wait_for_login(page):
    await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    login_form = await page.query_selector('input[name="email"]')
    if login_form:
        if "--login" not in sys.argv:
            print("로그인 필요! 먼저: python3 fb_friend_posts.py --login")
            return False
        print(f"\n  브라우저에서 Facebook 로그인해주세요. ({LOGIN_WAIT_SEC}초 대기)\n")
        try:
            await page.wait_for_url("**/facebook.com/**", timeout=LOGIN_WAIT_SEC * 1000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
    try:
        btn = page.locator('button:has-text("나중에 하기")')
        if await btn.is_visible(timeout=2000):
            await btn.click()
    except Exception:
        pass
    print("로그인 OK")
    return True


async def get_profile_name(page):
    """프로필 페이지에서 실제 이름 가져오기"""
    name = await page.evaluate(r"""
        () => {
            const h = document.querySelector('h1, h2');
            if (h) {
                const btn = h.querySelector('button, [role="button"]');
                if (btn) return btn.innerText?.trim().split('\n')[0] || '';
            }
            return '';
        }
    """)
    return name or ""


async def get_latest_posts(page, friend):
    url = friend["url"]
    name = friend["name"]

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # 실제 이름 가져오기 (URL만 알 때)
        real_name = await get_profile_name(page)
        if real_name:
            name = real_name

        # 포스트 영역까지 스크롤 (lazy load 트리거)
        for i in range(15):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)
            # 포스트 시간 링크가 충분히 로드됐는지 체크
            state = await page.evaluate(r"""
                () => {
                    const main = document.querySelector('[role="main"]');
                    if (!main) return { stop: false };
                    const hs = main.querySelectorAll('h2');
                    let hasPinned = false, hasOther = false;
                    for (const h of hs) {
                        if (h.textContent.includes('상단 고정')) hasPinned = true;
                        if (h.textContent.includes('다른 게시물')) hasOther = true;
                    }
                    // 시간 링크 갯수 체크
                    const tls = main.querySelectorAll('a[href*="/posts/"], a[href*="permalink"], a[href*="/reel/"]');
                    const timePattern = /^(\d+\s*(분|시간|일|주|개월|년)|어제|방금)/;
                    let timeCount = 0;
                    for (const tl of tls) {
                        if (timePattern.test(tl.innerText?.trim() || '')) timeCount++;
                    }
                    return { hasPinned, hasOther, timeCount };
                }
            """)
            if state.get("hasOther"):
                # 상단 고정 있음 → "다른 게시물" 도달, 추가 4회 스크롤
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await page.wait_for_timeout(800)
                break
            elif not state.get("hasPinned") and state.get("timeCount", 0) >= POSTS_PER_FRIEND:
                # 상단 고정 없음 → 충분한 시간 링크 확보되면 중단
                break

        # "더 보기" 버튼 모두 클릭하여 전문 펼치기
        for _ in range(3):  # 여러 번 시도 (동적 로드 대응)
            clicked = await page.evaluate("""
                () => {
                    let count = 0;
                    const main = document.querySelector('[role="main"]');
                    if (!main) return 0;
                    // 모든 가능한 "더 보기" 요소
                    const all = main.querySelectorAll('div[role="button"], span[role="button"], [role="button"]');
                    for (const el of all) {
                        // 댓글 영역 제외
                        if (el.closest('article')) continue;
                        const t = el.innerText?.trim();
                        if (t === '더 보기') {
                            el.click();
                            count++;
                        }
                    }
                    return count;
                }
            """)
            if clicked == 0:
                break
            await page.wait_for_timeout(1000)

        raw_posts = await page.evaluate(r"""
            (args) => {
                const [postsNeeded, profileName] = args;
                const results = [];
                const main = document.querySelector('[role="main"]');
                if (!main) return results;

                const seenTexts = new Set();
                const skipStarts = ['댓글', '좋아요', '공유', '게시물', '필터', '더 보기',
                    '모두 보기', '릴스', '하이라이트', '상단 고정', '댓글 달기', '공감',
                    '사용 가능', '홍보', '인사이트', '카드 무시', '타겟', '숨기기',
                    '신고', '답글', '이름으로', '아바타', '이모티콘', 'GIF', '스티커',
                    '공개 대상', '옵션', '읽어들이는', '사진/동영상', '사람 태그',
                    '님에게 글', '무슨 생각', '라이브', '커버 사진', '프로필 사진',
                    '게시물 관리', '즐겨찾기', '다른 게시물', '개인정보', '약관', '광고',
                    'AdChoices', '쿠키', '메뉴', 'Messenger', '알림', '내 프로필',
                    '님의 타임라인', '확인', '나중에', '팔로워', '팔로잉', '친구 ',
                    '함께 아는', '사진 모두', '모든 친구'];

                const timePattern = /^(\d+\s*(분|시간|일|주|개월|년)\s*(전)?|어제|방금|그저께|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일)$/;

                // "상단 고정 게시물" ~ "다른 게시물" 사이의 DOM 영역을 찾아서
                // 그 안의 시간 링크를 pinnedHrefs에 기록 → 나중에 제외
                const pinnedHrefs = new Set();
                const headings = main.querySelectorAll('h2');
                let pinnedH = null, otherH = null;
                for (const h of headings) {
                    if (h.textContent.includes('상단 고정')) pinnedH = h;
                    if (h.textContent.includes('다른 게시물')) otherH = h;
                }
                if (pinnedH) {
                    // 상단 고정 heading 이후, 다른 게시물 heading 이전의 시간 링크를 수집
                    const allTimeLinks = main.querySelectorAll('a[href*="permalink"], a[href*="/posts/"]');
                    let inPinned = false;
                    for (const tl of allTimeLinks) {
                        // pinnedH 이후인지 확인 (DOM 순서)
                        if (pinnedH.compareDocumentPosition(tl) & Node.DOCUMENT_POSITION_FOLLOWING) {
                            inPinned = true;
                        }
                        // otherH 이후면 벗어남
                        if (otherH && otherH.compareDocumentPosition(tl) & Node.DOCUMENT_POSITION_FOLLOWING) {
                            break;
                        }
                        if (inPinned) {
                            pinnedHrefs.add(tl.getAttribute('href'));
                        }
                    }
                }

                const timeLinks = main.querySelectorAll('a[href*="/posts/"], a[href*="permalink"], a[href*="/reel/"]');

                for (const tl of timeLinks) {
                    if (results.length >= postsNeeded * 2) break;
                    const timeText = tl.innerText?.trim();
                    if (!timeText || !timePattern.test(timeText)) continue;
                    // 상단 고정 영역의 링크면 스킵
                    if (pinnedHrefs.has(tl.getAttribute('href'))) continue;

                    // 같은 포스트 URL이면 스킵 (첫 번째=본문, 이후=댓글 타임스탬프)
                    const rawHref = tl.getAttribute('href') || '';
                    // permalink의 story_fbid 또는 /posts/ID 부분으로 중복 판별
                    let postId = '';
                    const storyMatch = rawHref.match(/story_fbid=([^&]+)/);
                    const postsMatch = rawHref.match(/\/posts\/([^/?]+)/);
                    const reelMatch = rawHref.match(/\/reel\/([^/?]+)/);
                    if (storyMatch) postId = 'story:' + storyMatch[1];
                    else if (postsMatch) postId = 'post:' + postsMatch[1];
                    else if (reelMatch) postId = 'reel:' + reelMatch[1];
                    if (postId && seenTexts.has('__url__' + postId)) continue;
                    if (postId) seenTexts.add('__url__' + postId);

                    // 포스트 컨테이너 찾기
                    let container = tl;
                    for (let i = 0; i < 20; i++) {
                        container = container.parentElement;
                        if (!container) break;
                        if (container.offsetHeight > 150) break;
                    }
                    if (!container) continue;

                    // ★ 포스트 URL이 프로필 주인의 글인지 확인
                    const postHref = tl.getAttribute('href') || '';
                    const pageUrl = window.location.href;
                    let profileSlug = '';
                    if (pageUrl.includes('profile.php?id=')) {
                        const m = pageUrl.match(/id=(\d+)/);
                        if (m) profileSlug = m[1];
                    } else {
                        const parts = pageUrl.replace(/\/$/, '').split('/');
                        profileSlug = parts[parts.length - 1];
                    }

                    // URL 패턴으로 본인 글 판별:
                    // 본인 글: /slug/posts/XXX 또는 permalink.php?...&id=본인ID
                    // 남의 글: /다른사람/posts/XXX
                    if (profileSlug) {
                        // /someone/posts/ 패턴에서 someone이 본인이 아니면 스킵
                        const slugMatch = postHref.match(/facebook\.com\/([^/?#]+)\/(posts|reel)\//);
                        if (slugMatch && slugMatch[1] !== profileSlug) {
                            continue;  // 다른 사람의 /posts/ URL → 건너뜀
                        }
                        // permalink.php는 항상 본인 타임라인 글이므로 통과
                    }

                    // 포스트 본문 텍스트 추출 (댓글 제외)
                    const textDivs = container.querySelectorAll('div[dir="auto"]');
                    let postText = "";
                    for (const div of textDivs) {
                        // article 안의 텍스트는 댓글이므로 제외
                        if (div.closest('article')) continue;
                        // 댓글 입력란 제외
                        if (div.closest('[contenteditable]')) continue;
                        if (div.closest('form')) continue;
                        const text = div.innerText?.trim();
                        if (!text || text.length < 3) continue;
                        let skip = false;
                        for (const sw of skipStarts) {
                            if (text.startsWith(sw) || text === sw) { skip = true; break; }
                        }
                        if (skip) continue;
                        // 프로필 이름과 동일한 텍스트 건너뜀
                        if (text === profileName) continue;
                        postText = text;
                        break;
                    }

                    if (!postText || seenTexts.has(postText)) continue;
                    seenTexts.add(postText);

                    let isPinned = false;
                    let el = container;
                    for (let i = 0; i < 5; i++) {
                        if (!el) break;
                        const prev = el.previousElementSibling;
                        if (prev && prev.innerText?.includes('상단 고정')) {
                            isPinned = true; break;
                        }
                        el = el.parentElement;
                    }
                    // 포스트 링크 추출 (query string에서 __cft__ 등만 제거, id/story_fbid 유지)
                    const postLink = tl.getAttribute('href') || '';
                    let fullLink = '';
                    if (postLink.includes('/posts/') || postLink.includes('permalink') || postLink.includes('/reel/')) {
                        fullLink = postLink.startsWith('http') ? postLink : 'https://www.facebook.com' + postLink;
                        // /posts/나 /reel/은 ? 이전까지, permalink는 story_fbid&id만 유지
                        if (fullLink.includes('permalink.php')) {
                            const url = new URL(fullLink);
                            const clean = new URL(url.origin + url.pathname);
                            if (url.searchParams.has('story_fbid')) clean.searchParams.set('story_fbid', url.searchParams.get('story_fbid'));
                            if (url.searchParams.has('id')) clean.searchParams.set('id', url.searchParams.get('id'));
                            fullLink = clean.toString();
                        } else {
                            fullLink = fullLink.split('?')[0];
                        }
                    }

                    // 댓글 수 추출 - "댓글 N개" 버튼 텍스트
                    let commentCount = '';
                    const btns = container.querySelectorAll('button, [role="button"]');
                    for (const btn of btns) {
                        const t = btn.innerText?.trim() || '';
                        const m = t.match(/^댓글\s*(\d+)개$/);
                        if (m) { commentCount = m[1]; break; }
                    }

                    // 이미지 URL 추출 (댓글 영역 제외)
                    const images = [];
                    const imgs = container.querySelectorAll('img[src*="scontent"], img[src*="fbcdn"]');
                    for (const img of imgs) {
                        if (img.closest('article')) continue;  // 댓글 내 이미지 제외
                        const src = img.getAttribute('src') || '';
                        // 프로필/아이콘 이미지 제외 (작은 이미지)
                        const w = img.naturalWidth || img.width || 0;
                        const h = img.naturalHeight || img.height || 0;
                        if (w < 100 && h < 100) continue;
                        if (src.includes('_s80x80') || src.includes('_p80x80') || src.includes('emoji')) continue;
                        if (src && !images.includes(src)) images.push(src);
                    }

                    // 외부 링크 추출 (facebook 외부로 가는 링크)
                    let sharedLink = '';
                    let sharedLinkTitle = '';
                    const extLinks = container.querySelectorAll('a[href*="l.facebook.com/l.php"], a[href*="lm.facebook.com"]');
                    for (const el of extLinks) {
                        if (el.closest('article')) continue;
                        const href = el.getAttribute('href') || '';
                        // URL 디코딩해서 실제 외부 URL 추출
                        const uMatch = href.match(/[?&]u=([^&]+)/);
                        if (uMatch) {
                            sharedLink = decodeURIComponent(uMatch[1]).split('&fbclid')[0].split('?fbclid')[0];
                            sharedLinkTitle = el.innerText?.trim().substring(0, 100) || '';
                            break;
                        }
                    }

                    results.push({ time: timeText, text: postText, pinned: isPinned, link: fullLink, comments: commentCount, images: images.slice(0, 4), sharedLink, sharedLinkTitle });
                }

                const nonPinned = results.filter(r => !r.pinned);
                const pinned = results.filter(r => r.pinned);
                return [...nonPinned, ...pinned].slice(0, postsNeeded);
            }
        """, [POSTS_PER_FRIEND, name])

        # 이미지 다운로드 디렉토리
        img_dir = os.path.join(OUTPUT_DIR, "images")
        os.makedirs(img_dir, exist_ok=True)

        posts = []
        for rp in raw_posts:
            text = rp.get("text", "").strip()
            text = re.sub(r"\s*…\s*더 보기\s*$", "…", text)
            # 글자 제한 없음 - 전문 수집

            # 이미지 다운로드
            local_images = []
            for img_url in rp.get("images", []):
                try:
                    img_hash = str(abs(hash(img_url)) % 10**10)
                    ext = "jpg"
                    local_path = f"images/{img_hash}.{ext}"
                    full_path = os.path.join(OUTPUT_DIR, local_path)
                    if not os.path.exists(full_path):
                        resp = await page.request.get(img_url)
                        if resp.ok:
                            with open(full_path, "wb") as f:
                                f.write(await resp.body())
                    local_images.append(local_path)
                except Exception:
                    pass

            posts.append({
                "time": rp.get("time", ""),
                "text": text,
                "pinned": rp.get("pinned", False),
                "link": rp.get("link", ""),
                "comments": rp.get("comments", ""),
                "images": local_images,
                "sharedLink": rp.get("sharedLink", ""),
                "sharedLinkTitle": rp.get("sharedLinkTitle", ""),
            })

        return {"name": name, "url": url, "posts": posts, "scraped_at": datetime.now().isoformat()}

    except Exception as e:
        print(f"  [{name}] 오류: {e}")
        return {"name": name, "url": url, "posts": [], "scraped_at": datetime.now().isoformat()}


def render_html(data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cards = ""
    for person in data:
        name = person["name"]
        url = person["url"]
        posts = person["posts"]
        if not posts:
            continue
        hue = sum(ord(c) for c in name) % 360
        initial = name[0]
        posts_html = ""
        for p in posts:
            pin = '<span class="pin">PIN</span> ' if p.get("pinned") else ""
            text = p["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            link = p.get("link", "")
            comments = p.get("comments", "")
            if link:
                time_html = f'<a href="{link}" target="_blank" class="time-link">{pin}{p["time"]}</a>'
            else:
                time_html = f'{pin}{p["time"]}'
            comment_html = f' <span class="comments">💬 {comments}</span>' if comments else ""

            # 이미지
            img_html = ""
            for img_path in p.get("images", []):
                img_html += f'<img src="{img_path}" class="post-img" loading="lazy">'
            if img_html:
                img_html = f'<div class="post-images">{img_html}</div>'

            # 외부 링크
            shared = p.get("sharedLink", "")
            shared_title = p.get("sharedLinkTitle", "")
            link_html = ""
            if shared:
                display = shared_title or shared
                # 도메인만 표시
                domain = shared.split("//")[-1].split("/")[0].replace("www.", "")
                link_html = f'<div class="shared-link"><a href="{shared}" target="_blank">🔗 {domain}</a></div>'

            posts_html += f'<div class="post"><div class="time">{time_html}{comment_html}</div><div class="text">{text}</div>{img_html}{link_html}</div>'
        cards += f'''<div class="card">
  <div class="head"><a href="{url}" target="_blank" class="av" style="background:hsl({hue},55%,45%)">{initial}</a>
  <div><a href="{url}" target="_blank" class="nm">{name}</a><span class="cnt">{len(posts)}개</span></div></div>
  <div class="body">{posts_html}</div></div>'''

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FB Friends - {now}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#18191a;color:#e4e6eb;line-height:1.5;padding:20px}}
.hdr{{max-width:680px;margin:0 auto 20px;text-align:center}}
.hdr h1{{font-size:20px;font-weight:700}} .hdr .m{{font-size:12px;color:#b0b3b8;margin-top:2px}}
.grid{{max-width:680px;margin:0 auto;display:flex;flex-direction:column;gap:14px}}
.card{{background:#242526;border-radius:12px;border:1px solid #3e4042;overflow:hidden}}
.head{{display:flex;align-items:center;gap:10px;padding:14px 14px 10px}}
.av{{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;text-decoration:none;flex-shrink:0}}
.nm{{font-size:15px;font-weight:600;color:#e4e6eb;text-decoration:none}} .nm:hover{{text-decoration:underline}}
.cnt{{display:block;font-size:11px;color:#b0b3b8}}
.body{{padding:0 14px 14px}}
.post{{padding:10px 0;border-top:1px solid #3e4042}} .post:first-child{{border:none;padding-top:2px}}
.time{{font-size:11px;color:#2d88ff;font-weight:500;margin-bottom:4px}}
.time-link{{color:#2d88ff;text-decoration:none}} .time-link:hover{{text-decoration:underline}}
.comments{{color:#b0b3b8;font-size:11px;margin-left:6px}}
.post-images{{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}}
.post-img{{max-width:100%;max-height:300px;border-radius:8px;object-fit:cover}}
.post-images:has(img+img) .post-img{{max-width:48%}}
.shared-link{{margin-top:6px;padding:8px 10px;background:#3a3b3c;border-radius:8px;font-size:12px}}
.shared-link a{{color:#2d88ff;text-decoration:none}} .shared-link a:hover{{text-decoration:underline}}
.text{{font-size:13px;white-space:pre-wrap;word-break:break-word}}
.pin{{background:#e8a23e;color:#000;font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;margin-right:3px}}
@media(prefers-color-scheme:light){{body{{background:#f0f2f5;color:#1c1e21}}.card{{background:#fff;border-color:#dadde1}}.post{{border-color:#dadde1}}.nm{{color:#1c1e21}}.cnt,.hdr .m{{color:#65676b}}.time{{color:#1877f2}}}}
</style></head><body>
<div class="hdr"><h1>Facebook 친구 최신 포스팅</h1><div class="m">수집: {now} &middot; {len([d for d in data if d['posts']])}명</div></div>
<div class="grid">{cards}</div></body></html>"""


async def main():
    headless = "--login" not in sys.argv

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=headless,
            viewport={"width": 1440, "height": 900}, locale="ko-KR",
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        if not await wait_for_login(page):
            await context.close()
            return

        # 이전 이미지 삭제
        import shutil
        img_dir = os.path.join(OUTPUT_DIR, "images")
        if os.path.isdir(img_dir):
            shutil.rmtree(img_dir)

        friends = load_friends()
        print(f"\n{len(friends)}명 포스트 수집 중 (각 {POSTS_PER_FRIEND}개)...\n")
        results = []
        for friend in friends:
            result = await get_latest_posts(page, friend)
            results.append(result)
            if result["posts"]:
                for p in result["posts"]:
                    pin = " [고정]" if p["pinned"] else ""
                    print(f"  [{result['name']}] ({p['time']}{pin}) {p['text'][:70]}…")
            else:
                print(f"  [{result['name']}] 포스트 없음")
            print()

        await context.close()

    # 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    json_path = os.path.join(OUTPUT_DIR, "fb_friend_posts.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    html_path = os.path.join(OUTPUT_DIR, "fb_friend_posts.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(results))

    active = len([r for r in results if r["posts"]])
    print(f"{'='*60}")
    print(f"완료: {active}/{len(results)}명 수집")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")


if __name__ == "__main__":
    asyncio.run(main())
