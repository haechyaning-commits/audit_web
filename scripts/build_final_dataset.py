# ------------------------------------------------------------------
# 최종 documents/chunks 데이터셋 빌드 스크립트
# ------------------------------------------------------------------
# 8/6 Colab 세션에서 대화로 진행했던 데이터 정리 작업을 재현 가능한
# 스크립트로 정리한 것. Colab에서 Drive 마운트 후 실행.
#
# 입력:
#   - audit_cases_final_v2.jsonl : 원본 파싱 데이터 (문서 단위, 중복/분할 포함)
#   - embed_ready_v2.jsonl       : 청킹 데이터 (document_id/chunk_id 포함)
#
# 처리 단계:
#   1) audit_cases_final_v2.jsonl을 (source_file, case_number)로 그룹핑
#      - "overview"(감사개요/커버페이지, 실제 지적사항 아님) 레코드 제외
#      - "_splitNofM" 형태의 parse_tier는 같은 사례가 여러 조각으로
#        나뉜 것이므로 순서대로 합침 (그냥 하나만 남기면 원문 유실됨)
#      - 여러 등급(standard/partial/fallback)이 섞여 있으면 최고 등급만 채택
#      - 그룹 내 모든 레코드가 "extraction_failed"면(=쓸 수 있는 원문이
#        하나도 없으면) 통째로 제외 (schema.sql의 parsing_quality CHECK가
#        standard/partial/fallback만 허용하므로, 여기서 안 거르면 DB 적재 시 실패함)
#   2) embed_ready_v2.jsonl의 document_id 중 "title이 1개뿐인" 깨끗한
#      그룹만 채택 (title이 여러 개 섞인 document_id는 실제로는 여러
#      사례가 하나로 잘못 묶인 것으로 판단, 제외)
#   3) 1)과 2)를 (source_file, title) 키로 매칭 — 매칭된 것만
#      documents_final.jsonl / chunks_final.jsonl 로 저장
#
# 출력:
#   - documents_final.jsonl : {id, institution, year, raw_text, parsing_quality}
#   - chunks_final.jsonl    : {id, document_id, text}
#     (embedding 벡터는 여기 안 붙임 — load_to_postgres.py에서
#      embeddings.npy/chunk_ids.jsonl과 조인해서 DB에 넣음)
# ------------------------------------------------------------------

import json
import re
from collections import defaultdict

BASE = "/content/drive/MyDrive/audit_project/"
AUDIT_CASES_PATH = BASE + "audit_cases_final_v2.jsonl"
EMBED_READY_PATH = BASE + "embed_ready_v2.jsonl"
DOCUMENTS_OUT_PATH = BASE + "documents_final.jsonl"
CHUNKS_OUT_PATH = BASE + "chunks_final.jsonl"

# 등급 우선순위 (낮을수록 우선) — overview는 아예 별도 처리(제외)하므로 여기 없음
TIER_PRIORITY = {"standard": 0, "partial": 1, "fallback": 2, "extraction_failed": 99}

SPLIT_RE = re.compile(r"^(.*?)_split(\d+)of(\d+)$")


def parse_tier_info(tier):
    """'standard_split1of2' -> ('standard', 1, 2). 분할 아니면 (tier, None, None)."""
    if tier is None:
        return None, None, None
    m = SPLIT_RE.match(tier)
    if m:
        base, idx, total = m.groups()
        return base, int(idx), int(total)
    return tier, None, None


def build_clean_documents(path: str) -> dict:
    """(source_file, case_number) 그룹핑 -> overview 제외, split 병합, 최고 등급 채택."""
    groups = defaultdict(list)
    skipped_overview = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            base, _, _ = parse_tier_info(rec.get("parse_tier"))
            if base == "overview":
                skipped_overview += 1
                continue  # 실제 지적사항이 아니라 감사개요/커버페이지
            key = (rec.get("source_file"), rec.get("case_number"))
            groups[key].append(rec)

    print(f"[1/3] overview로 제외된 레코드: {skipped_overview}건")

    final_docs = {}
    skipped_extraction_failed = 0
    for key, records in groups.items():
        by_base = defaultdict(list)
        for r in records:
            base, idx, _ = parse_tier_info(r.get("parse_tier"))
            by_base[base].append((idx, r))

        best_base = min(by_base.keys(), key=lambda b: TIER_PRIORITY.get(b, 50))
        if best_base == "extraction_failed":
            # 그룹 내 모든 레코드가 파싱 실패 -> 쓸 수 있는 원문이 없으므로 제외
            # (schema.sql의 parsing_quality CHECK 제약도 standard/partial/fallback만 허용)
            skipped_extraction_failed += 1
            continue
        chosen = by_base[best_base]

        if all(idx is not None for idx, _ in chosen):
            # split된 문서 -> 순서대로 합치기 (중복 split part는 첫 번째만 사용)
            chosen_sorted = sorted(chosen, key=lambda x: x[0])
            seen_idx, parts = set(), []
            for idx, r in chosen_sorted:
                if idx not in seen_idx:
                    parts.append(r.get("raw_text", ""))
                    seen_idx.add(idx)
            rep = chosen_sorted[0][1]
            final_docs[key] = {**rep, "raw_text": "\n".join(parts), "parse_tier": best_base}
        else:
            # [버그 수정] 여기도 if 분기처럼 parse_tier를 best_base로 정규화해야 함.
            # 안 그러면 같은 그룹 안에 split된 레코드(idx 있음)와 안 된 레코드(idx=None)가
            # 섞여서 이 분기를 타는 경우, chosen[0]이 하필 split 레코드면 원본 parse_tier
            # ("fallback_split1of2" 같은 접미사 붙은 값)가 정리 안 된 채 그대로 저장됨 —
            # schema.sql의 parsing_quality CHECK(standard/partial/fallback만 허용) 위반으로
            # DB 적재가 막힘. best_base는 이미 이 그룹에서 채택된 등급이므로 항상 이 값으로
            # 덮어써야 함.
            final_docs[key] = {**chosen[0][1], "parse_tier": best_base}

    print(f"[1/3] 파싱 완전 실패(extraction_failed)로 제외된 사례: {skipped_extraction_failed}건")
    print(f"[1/3] 정리된 고유 문서 수: {len(final_docs)}")
    return final_docs


def match_with_chunks(clean_docs: dict, embed_ready_path: str):
    """embed_ready_v2의 document_id 중 단일 사례(title 1개)만 채택 후
    (source_file, title) 키로 clean_docs와 매칭."""
    doc_titles = defaultdict(set)
    doc_chunks = defaultdict(list)
    with open(embed_ready_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            doc_id = rec["document_id"]
            doc_titles[doc_id].add(rec.get("title"))
            doc_chunks[doc_id].append(rec)

    clean_doc_ids = {d for d, titles in doc_titles.items() if len(titles) == 1}
    print(f"[2/3] 깨끗한 document_id: {len(clean_doc_ids)} / 전체 {len(doc_titles)}")

    # clean_docs를 (source_file, title) 키로 조회 가능하게 인덱싱
    lookup = {(d.get("source_file"), d.get("title")): d for d in clean_docs.values()}

    final_documents = {}
    matched_doc_ids = set()
    for doc_id in clean_doc_ids:
        sample = doc_chunks[doc_id][0]
        key = (sample.get("source_file"), sample.get("title"))
        rec = lookup.get(key)
        if rec is None:
            continue
        final_documents[doc_id] = {
            "id": doc_id,
            "institution": rec.get("institution"),
            "year": rec.get("audit_year"),
            "raw_text": rec.get("raw_text"),
            "parsing_quality": rec.get("parse_tier"),
        }
        matched_doc_ids.add(doc_id)

    print(f"[3/3] 매칭 성공(최종 documents 건수): {len(final_documents)}")
    return final_documents, doc_chunks, matched_doc_ids


def save_outputs(final_documents: dict, doc_chunks: dict, matched_doc_ids: set):
    with open(DOCUMENTS_OUT_PATH, "w", encoding="utf-8") as f:
        for doc in final_documents.values():
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"저장: {DOCUMENTS_OUT_PATH} ({len(final_documents)}건)")

    n = 0
    with open(CHUNKS_OUT_PATH, "w", encoding="utf-8") as f:
        for doc_id in matched_doc_ids:
            for chunk in doc_chunks[doc_id]:
                f.write(json.dumps({
                    "id": chunk["chunk_id"],
                    "document_id": doc_id,
                    "text": chunk["text"],
                }, ensure_ascii=False) + "\n")
                n += 1
    print(f"저장: {CHUNKS_OUT_PATH} ({n}건)")


if __name__ == "__main__":
    clean_docs = build_clean_documents(AUDIT_CASES_PATH)
    final_documents, doc_chunks, matched_doc_ids = match_with_chunks(clean_docs, EMBED_READY_PATH)
    save_outputs(final_documents, doc_chunks, matched_doc_ids)
