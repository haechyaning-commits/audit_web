# ------------------------------------------------------------------
# 사례 상세페이지(/cases/{id}/{slug}) 전체를 담은 sitemap 생성 (2026-08-24, 웹페이지
# 피드백 반영 — "SEO 친화적 URL을 설계해놓고 sitemap이 없다" 항목)
# ------------------------------------------------------------------
# frontend/public/sitemap.xml은 지금 "/"(홈) 하나만 담은 최소 버전인데, 이 스크립트가
# documents 테이블 전체(67,751건 안팎)를 훑어서 진짜 sitemap을 만듦. 이 저장소를 다루는
# 코드 샌드박스 세션에는 실제 Railway DATABASE_URL이 없어서 여기서는 실행 못 해봤음 —
# DB 접근 가능한 로컬/CI 환경에서 실행할 것.
#
# **왜 파일을 여러 개로 쪼개는가**: sitemaps.org 프로토콜 상한이 파일 하나당 URL
# 50,000개 — 67,751건이면 최소 2개 파일 + 그 둘을 가리키는 인덱스 파일이 필요함.
#
# **URL(slug) 만드는 로직은 frontend/src/caseUrl.js의 buildCaseSlug/buildCasePath와
# 반드시 동일해야 함** — 그래야 sitemap에 올린 URL이 실제 라우트와 정확히 일치함(하나가
# 바뀌면 다른 쪽도 같이 고칠 것). 제목 추출도 backend/app/textutils.extract_title을
# 그대로 재사용해서 API가 실제로 내려주는 title과 어긋나지 않게 함.
#
# 실행:
#   DATABASE_URL=postgresql://... python scripts/generate_sitemap.py       # DRY_RUN(기본): 개수/샘플만 출력
#   DRY_RUN=false DATABASE_URL=postgresql://... python scripts/generate_sitemap.py  # 실제 파일 생성
#
# 생성 결과: frontend/public/sitemap/sitemap-1.xml, sitemap-2.xml, ... + sitemap-index.xml
# 실행 후 사람이 확인/반영해야 하는 것(스크립트가 자동으로 안 건드림, 실수로 잘못된
# robots.txt를 덮어쓰지 않으려는 의도적 설계):
#   1) frontend/public/robots.txt의 "Sitemap:" 줄을
#      https://audit-web-phi.vercel.app/sitemap-index.xml 로 교체
#   2) frontend/public/sitemap.xml(최소 버전, "/" 하나만 있음)은 그대로 둬도 되고
#      지워도 됨 — sitemap-index.xml이 실질적인 진입점이 됨
# ------------------------------------------------------------------
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import psycopg2

REPO_ROOT = Path(__file__).resolve().parent.parent
# backend/app/textutils.extract_title을 그대로 재사용(제목 추출 로직 이중 관리 방지) —
# 이 스크립트는 Colab이 아니라 이 저장소 클론 루트에서 바로 실행되는 걸 전제로 함.
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.textutils import extract_title  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://audit-web-phi.vercel.app").rstrip("/")
OUT_DIR = REPO_ROOT / "frontend" / "public" / "sitemap"
URLS_PER_FILE = 50_000  # sitemaps.org 프로토콜 상한(파일당 URL 개수)
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# --- frontend/src/caseUrl.js의 buildCaseSlug와 동일한 로직(문자 그대로 대응시킴) ---
SLUG_MAX_LEN = 100
_WS_RE = re.compile(r"\s+")
_BAD_CHARS_RE = re.compile(r"[/\\?#%]")
_DASH_COLLAPSE_RE = re.compile(r"-+")


def build_case_slug(institution: str | None, year: int | None, title: str | None) -> str:
    parts = [p for p in (institution, str(year) if year else None, title) if p and str(p).strip()]
    raw = " ".join(parts).strip()
    if not raw:
        return "사례"
    slug = _WS_RE.sub("-", raw)
    slug = _BAD_CHARS_RE.sub("-", slug)
    slug = _DASH_COLLAPSE_RE.sub("-", slug)
    slug = slug.strip("-")[:SLUG_MAX_LEN]
    return slug or "사례"


def build_case_path(doc_id: str, institution: str | None, year: int | None, title: str | None) -> str:
    slug = build_case_slug(institution, year, title)
    return f"/cases/{quote(doc_id, safe='')}/{quote(slug, safe='')}"


def fetch_documents() -> list[dict]:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL 환경변수를 설정하세요 (Railway Postgres 서비스 -> Connect 탭)")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            # main.py의 검색 SQL과 동일하게 200자 buffer만 가져와서 extract_title에 넘김
            # (raw_text 전체를 안 끌어와도 됨 — id/기관/연도/제목 200자면 충분).
            cur.execute(
                "SELECT id, institution, year, left(raw_text, 200) AS title_buffer "
                "FROM documents ORDER BY id"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def build_urls(docs: list[dict]) -> list[str]:
    urls = []
    for d in docs:
        title = extract_title(d["title_buffer"])
        path = build_case_path(d["id"], d["institution"], d["year"], title)
        urls.append(SITE_BASE_URL + path)
    return urls


def write_sitemaps(urls: list[str]) -> list[str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chunks = [urls[i : i + URLS_PER_FILE] for i in range(0, len(urls), URLS_PER_FILE)]
    filenames = []
    for i, chunk in enumerate(chunks, start=1):
        filename = f"sitemap-{i}.xml"
        body = "\n".join(f"  <url><loc>{escape(u)}</loc></url>" for u in chunk)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n"
            "</urlset>\n"
        )
        (OUT_DIR / filename).write_text(xml, encoding="utf-8")
        filenames.append(filename)

    index_body = "\n".join(
        f"  <sitemap><loc>{escape(SITE_BASE_URL)}/sitemap/{fn}</loc></sitemap>" for fn in filenames
    )
    index_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{index_body}\n"
        "</sitemapindex>\n"
    )
    index_path = REPO_ROOT / "frontend" / "public" / "sitemap-index.xml"
    index_path.write_text(index_xml, encoding="utf-8")
    return filenames


if __name__ == "__main__":
    print(f"DB에서 documents 조회 중... (DRY_RUN={DRY_RUN})")
    docs = fetch_documents()
    print(f"문서 {len(docs)}건 조회됨")

    urls = build_urls(docs)
    print(f"URL {len(urls)}개 생성됨, 샘플 3개:")
    for u in urls[:3]:
        print(f"  {u}")

    if DRY_RUN:
        n_files = -(-len(urls) // URLS_PER_FILE)  # 올림 나눗셈
        print(f"\nDRY_RUN=true라 파일은 안 씀. 실제 실행하면 sitemap 파일 {n_files}개 + 인덱스 1개 생성 예정.")
        print("DRY_RUN=false DATABASE_URL=... python scripts/generate_sitemap.py 로 재실행하세요.")
    else:
        filenames = write_sitemaps(urls)
        print(f"\n생성 완료: frontend/public/sitemap/{{{', '.join(filenames)}}} + frontend/public/sitemap-index.xml")
        print("다음: frontend/public/robots.txt의 Sitemap: 줄을 sitemap-index.xml로 바꿀 것(스크립트 상단 주석 참고)")
