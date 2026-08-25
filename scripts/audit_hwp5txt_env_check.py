# ------------------------------------------------------------------
# hwp5txt 런타임 정상 동작 여부 최소 진단 (2026-08-25, 읽기 전용, Colab 실행용)
# ------------------------------------------------------------------
# 배경: STATUS.md 2026-08-24(17차) — audit_hwp_table_loss_full_population.py
# (.hwp 33,089건 전수)를 돌렸더니 "영향받음 0건(0.0%), 에러 337건"으로
# 나왔는데, 8/18 표본조사(3,426건, 완전히 같은 로직)가 50.5%를 잡아냈던
# 것과 정면으로 모순됨. 원인 추적 결과 로직 버그가 아니라 **그 세션의 Colab
# 런타임에서 hwp5txt가 사실상 100% 실패**하고 있었던 것으로 판명(성공
# 처리된 32,752건 전부가 n_table_markers=0, 명시적 에러 337건은 전부
# jsdelivr 403 레이트리밋으로 무관). 유력 후보는 8/19에 이미 한 번 겪은
# `pkgutil.ImpImporter` AttributeError(Python 3.12 + setuptools 버전
# 문제) — 그 세션에서 픽스(아래 설치 순서)를 다시 안 걸었을 가능성이 높음.
#
# 이 스크립트는 전수조사를 다시 돌리기 **전에** 딱 한 파일로 hwp5txt가
# 실제로 정상 동작하는지 먼저 확인하는 최소 진단임 — 여기서 실패가
# 재현되면 아래 "실행 순서"대로 재설치 후 이 스크립트부터 재실행할 것.
# (audit_hwp_table_loss_full_population.py의 `_check_one`은 8/24에 이미
# returncode 체크가 추가돼서, 이제는 hwp5txt가 실패해도 조용히 "표 0개"로
# 넘어가지 않고 에러로 잡힘 — 하지만 그 에러가 33,089건 전부에서 터지면
# 전수조사 자체가 몇 시간을 날리게 되므로, 1건짜리 이 진단으로 먼저
# 확인하는 게 훨씬 쌈)
#
# 실행 순서 (Colab 새 셀에서, 반드시 이 순서 지킬 것):
#   1) !pip install -q "setuptools<60" pyhwp
#   2) !pip install -qU "setuptools<82"
#   3) 런타임 재시작(런타임 > 세션 다시 시작) — pip install만으로는 이미
#      import된 setuptools가 안 바뀌므로 재시작 필수
#   4) 재시작 후 이 스크립트를 처음부터 다시 실행
#
# 이 진단이 "✅ 정상"으로 나온 뒤에만
# audit_hwp_table_loss_full_population.py를 재실행할 것. 재실행 전 기존
# 체크포인트(hwp_table_loss_full_checkpoint.jsonl)는 이번 사고로 얻은
# 값이 전부 무효이므로 반드시 삭제 후 재실행 — 안 지우면 "이미 처리됨"으로
# 건너뛰면서 무효 판정을 그대로 씀. 아래 결론 출력에 삭제 명령 포함됨.
# ------------------------------------------------------------------

# !pip install -q "setuptools<60" pyhwp
# !pip install -qU "setuptools<82"
# (여기서 런타임 재시작 필요 — 재시작 후에 아래부터 실행)
# !pip install -q psycopg2-binary requests

import os
import subprocess
import sys
import tempfile
import urllib.parse

import psycopg2
import requests

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    try:
        from google.colab import userdata
        DATABASE_URL = userdata.get("DATABASE_URL")
    except Exception:
        pass
if not DATABASE_URL:
    try:
        from google.colab import userdata
        DATABASE_URL = userdata.get("DATABASE_PUBLIC_URL")
    except Exception:
        pass
if not DATABASE_URL:
    raise SystemExit(
        "\nDATABASE_URL을 찾을 수 없습니다. Colab 좌측 열쇠(Secrets) 아이콘에서 "
        "\"DATABASE_URL\" Secret이 등록돼 있는지 확인하세요."
    )

_SOURCE_REPO_RAW_BASE = "https://cdn.jsdelivr.net/gh/haechyaning-commits/data@main/"
_SOURCE_FILE_PREFIX = "data_repo/"


def build_source_url(source_file):
    if not source_file:
        return None
    path = source_file.strip()
    if path.startswith(_SOURCE_FILE_PREFIX):
        path = path[len(_SOURCE_FILE_PREFIX):]
    path = path.strip("/")
    if not path:
        return None
    encoded = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
    return _SOURCE_REPO_RAW_BASE + encoded


print("=== 1) 환경 정보 ===")
print(f"python: {sys.version}")
try:
    import setuptools
    print(f"setuptools: {setuptools.__version__}")
except Exception as e:
    print(f"setuptools import 실패: {e}")

hwp5txt_version = subprocess.run(
    ["hwp5txt", "--version"], capture_output=True, text=True
)
print(f"hwp5txt --version: returncode={hwp5txt_version.returncode}")
print(f"  stdout: {hwp5txt_version.stdout.strip()}")
print(f"  stderr: {hwp5txt_version.stderr.strip()[:500]}")

print("\n=== 2) 알려진 표 손실 문서로 실제 변환 테스트 ===")
# 8/18 조사에서 이미 "표 손실" 영향으로 실사례 확인된 문서
# (한전KPS 2018, cb8dcfbd7983ba43) — audit_hwp_table_loss.py 헤더 참고.
# 이 문서는 hwp5txt로 뽑으면 "<표>" 마커가 반드시 나와야 정상.
TEST_DOC_ID = "cb8dcfbd7983ba43"

conn = psycopg2.connect(DATABASE_URL)
with conn.cursor() as cur:
    cur.execute(
        "SELECT id, institution, year, source_file FROM documents WHERE id = %s",
        (TEST_DOC_ID,),
    )
    row = cur.fetchone()
conn.close()

if not row:
    raise SystemExit(
        f"테스트 문서 {TEST_DOC_ID}를 DB에서 못 찾음 — id가 바뀌었을 수 있으니 "
        "audit_hwp_table_loss.py 헤더의 사례를 참고해 다른 .hwp 문서 id로 "
        "TEST_DOC_ID를 바꿔서 재실행할 것"
    )

doc_id, institution, year, source_file = row
url = build_source_url(source_file)
print(f"테스트 문서: {institution} {year} ({doc_id})")
print(f"다운로드 URL: {url}")

resp = requests.get(url, timeout=30)
resp.raise_for_status()
with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
    f.write(resp.content)
    tmp_path = f.name

try:
    proc = subprocess.run(
        ["hwp5txt", tmp_path], capture_output=True, text=True, timeout=60
    )
finally:
    os.unlink(tmp_path)

print(f"\nhwp5txt returncode: {proc.returncode}")
print(f"stderr (앞 1000자): {(proc.stderr or '(없음)').strip()[:1000]}")
n_table_markers = proc.stdout.count("<표>")
print(f"stdout 길이: {len(proc.stdout)}자, '<표>' 마커: {n_table_markers}개")

print("\n=== 결론 ===")
if proc.returncode != 0:
    print(
        "❌ hwp5txt 실행 자체가 실패함(returncode != 0) — 위 stderr 확인 후 "
        "스크립트 상단 주석의 setuptools 재설치 순서(런타임 재시작 포함)부터 "
        "다시 시도할 것. 아직 전수조사(audit_hwp_table_loss_full_population.py) "
        "재실행하지 말 것 — 지금 재실행하면 8/24와 같은 전면 실패가 반복됨."
    )
elif n_table_markers == 0:
    print(
        "⚠️ hwp5txt는 정상 종료했지만 이 문서에서 '<표>' 마커가 0개 — 알려진 "
        "표 손실 사례인데 마커가 없으면 이 문서 자체가 바뀌었거나 hwp5txt 동작이 "
        "달라진 것일 수 있음. audit_hwp_table_loss.py 8/18 원본 헤더와 대조해서 "
        "재확인 필요(그래도 returncode=0이라 위 8/24 사고와는 다른 케이스)."
    )
else:
    print(
        f"✅ 정상 — '<표>' 마커 {n_table_markers}개 확인(알려진 표 손실 케이스로 "
        "예상대로 잡힘). hwp5txt 런타임 정상 동작 중.\n\n"
        "다음 단계: 기존 무효 체크포인트 삭제 후 "
        "audit_hwp_table_loss_full_population.py 재실행:\n"
        "  !rm -f /content/drive/MyDrive/audit_project/"
        "hwp_table_loss_full_checkpoint.jsonl"
    )
