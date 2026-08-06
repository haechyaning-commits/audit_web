# ------------------------------------------------------------------
# DB 적재 전 사전 점검 스크립트
# ------------------------------------------------------------------
# load_to_postgres.py로 실제 Railway DB에 넣기 전에, 로컬(Colab)에서 먼저
# 돌려서 문제를 미리 잡는 용도. DB 연결 전혀 안 함 — 파일만 읽어서 검증.
#
# 여기서 걸러내는 것들:
#   1) chunks_final.jsonl의 document_id가 documents_final.jsonl에 실제로
#      존재하는지 (FK 위반 미리 확인 — 안 걸러내면 load_to_postgres.py가
#      적재 도중 psycopg2.errors.ForeignKeyViolation으로 멈출 수 있음)
#   2) parsing_quality 값이 schema.sql의 CHECK 제약(standard/partial/fallback)
#      을 벗어나는 게 없는지
#   3) year 필드 타입이 이상한 게 없는지 (정수여야 함)
#   4) documents_final.jsonl / chunks_final.jsonl 안에 id 중복이 없는지
#      (PRIMARY KEY라 중복 있어도 에러는 안 나고 ON CONFLICT DO NOTHING으로
#       조용히 스킵되지만, 몇 건이나 스킵될지 미리 알아두는 게 좋음)
#   5) chunks_final.jsonl의 각 청크가 embeddings.npy/chunk_ids.jsonl에 실제로
#      임베딩이 있는지 (없으면 load_chunks()가 자동 스킵하긴 하지만, 몇 건이나
#      스킵될지 사전에 알아야 "왜 개수가 안 맞지?" 하고 당황하지 않음)
#
# 실행:
#   python preflight_check.py
#   (에러/경고 없으면 "모든 점검 통과" 출력, 그럼 load_to_postgres.py 진행해도 됨)
# ------------------------------------------------------------------

import json
import os

BASE = "/content/drive/MyDrive/audit_project/"
DOCUMENTS_PATH = BASE + "documents_final.jsonl"
CHUNKS_PATH = BASE + "chunks_final.jsonl"
CHUNK_IDS_PATH = BASE + "embeddings_v2/chunk_ids.jsonl"

ALLOWED_PARSING_QUALITY = {"standard", "partial", "fallback"}


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def check_documents(docs: list[dict]) -> dict:
    ids = [d["id"] for d in docs]
    id_counts = {}
    for i in ids:
        id_counts[i] = id_counts.get(i, 0) + 1
    dup_ids = {i: c for i, c in id_counts.items() if c > 1}

    bad_quality = [d["id"] for d in docs if d.get("parsing_quality") not in ALLOWED_PARSING_QUALITY]

    bad_year = [
        d["id"] for d in docs
        if d.get("year") is not None and not isinstance(d.get("year"), int)
    ]

    missing_raw_text = [d["id"] for d in docs if not d.get("raw_text")]

    return {
        "total": len(docs),
        "unique_ids": len(id_counts),
        "dup_ids": dup_ids,
        "bad_quality": bad_quality,
        "bad_year": bad_year,
        "missing_raw_text": missing_raw_text,
    }


def check_chunks(chunks: list[dict], doc_ids: set, chunk_ids_with_embedding: set) -> dict:
    ids = [c["id"] for c in chunks]
    id_counts = {}
    for i in ids:
        id_counts[i] = id_counts.get(i, 0) + 1
    dup_ids = {i: c for i, c in id_counts.items() if c > 1}

    orphan_chunks = [c["id"] for c in chunks if c.get("document_id") not in doc_ids]

    missing_embedding = [c["id"] for c in chunks if c["id"] not in chunk_ids_with_embedding]

    return {
        "total": len(chunks),
        "unique_ids": len(id_counts),
        "dup_ids": dup_ids,
        "orphan_chunks": orphan_chunks,  # FK 위반 예방 — 이게 있으면 load_to_postgres.py가 멈춤
        "missing_embedding": missing_embedding,  # 이건 에러는 아니고 자동 스킵됨, 개수만 확인용
    }


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


if __name__ == "__main__":
    print_section("1) 파일 로드")
    docs = load_jsonl(DOCUMENTS_PATH)
    chunks = load_jsonl(CHUNKS_PATH)
    print(f"documents_final.jsonl: {len(docs)}건")
    print(f"chunks_final.jsonl: {len(chunks)}건")

    chunk_ids_with_embedding = {json.loads(l)["chunk_id"] for l in open(CHUNK_IDS_PATH, encoding="utf-8")}
    print(f"임베딩 있는 chunk_id: {len(chunk_ids_with_embedding)}건")

    print_section("2) documents 점검")
    doc_report = check_documents(docs)
    print(f"고유 id: {doc_report['unique_ids']} / 전체 {doc_report['total']}")
    if doc_report["dup_ids"]:
        print(f"⚠️  중복 id {len(doc_report['dup_ids'])}건 발견 (적재 시 첫 건만 남고 나머지는 조용히 스킵됨):")
        for i, c in list(doc_report["dup_ids"].items())[:10]:
            print(f"    {i} ({c}번 등장)")
    else:
        print("✅ 중복 id 없음")

    if doc_report["bad_quality"]:
        print(f"❌ parsing_quality가 standard/partial/fallback이 아닌 문서 {len(doc_report['bad_quality'])}건 "
              f"— 이대로 적재하면 CHECK 제약 위반으로 적재가 중간에 멈춥니다:")
        for i in doc_report["bad_quality"][:10]:
            print(f"    {i}")
    else:
        print("✅ parsing_quality 전부 정상 값")

    if doc_report["bad_year"]:
        print(f"⚠️  year 필드가 정수가 아닌 문서 {len(doc_report['bad_year'])}건 (문자열 등 — 적재 시 타입 에러 가능성):")
        for i in doc_report["bad_year"][:10]:
            print(f"    {i}")
    else:
        print("✅ year 필드 타입 정상")

    if doc_report["missing_raw_text"]:
        print(f"⚠️  raw_text가 비어있는 문서 {len(doc_report['missing_raw_text'])}건 "
              f"— NOT NULL 제약 위반으로 적재가 중간에 멈춥니다:")
        for i in doc_report["missing_raw_text"][:10]:
            print(f"    {i}")
    else:
        print("✅ raw_text 전부 존재")

    print_section("3) chunks 점검")
    doc_ids = {d["id"] for d in docs}
    chunk_report = check_chunks(chunks, doc_ids, chunk_ids_with_embedding)
    print(f"고유 id: {chunk_report['unique_ids']} / 전체 {chunk_report['total']}")
    if chunk_report["dup_ids"]:
        print(f"⚠️  중복 id {len(chunk_report['dup_ids'])}건 (첫 건만 남고 나머지 스킵됨)")
    else:
        print("✅ 중복 id 없음")

    if chunk_report["orphan_chunks"]:
        print(f"❌ document_id가 documents_final.jsonl에 없는 청크 {len(chunk_report['orphan_chunks'])}건 "
              f"— 이대로 적재하면 psycopg2.errors.ForeignKeyViolation으로 적재가 중간에 멈춥니다:")
        for i in chunk_report["orphan_chunks"][:10]:
            print(f"    {i}")
    else:
        print("✅ 모든 청크의 document_id가 documents에 존재함 (FK 위반 없음)")

    n_missing_emb = len(chunk_report["missing_embedding"])
    if n_missing_emb:
        print(f"ℹ️  임베딩 없는 청크 {n_missing_emb}건 — 에러는 아니고 load_to_postgres.py가 자동 스킵함 "
              f"(임베딩이 다 끝났다면 0건이어야 정상, 0이 아니면 embed_chunks.py가 정말 다 끝났는지 재확인 권장)")
    else:
        print("✅ 모든 청크에 임베딩 존재")

    print_section("결론")
    fatal = doc_report["bad_quality"] or doc_report["missing_raw_text"] or chunk_report["orphan_chunks"]
    if fatal:
        print("❌ 치명적 문제 발견 — load_to_postgres.py 실행 전에 위 항목부터 해결하세요.")
    else:
        print("✅ 치명적 문제 없음 — load_to_postgres.py 실행해도 안전합니다.")
        if n_missing_emb:
            print(f"   (다만 임베딩 없는 청크 {n_missing_emb}건은 스킵되니, 이게 예상한 숫자인지 한 번 더 확인하세요)")
