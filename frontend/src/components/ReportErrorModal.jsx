import { useEffect, useRef, useState } from "react";
import { submitErrorReport } from "../api.js";

const MAX_LEN = 2000;

/**
 * 2026-08-26(기능 추가): 상세페이지 "오류 신고" 버튼 클릭 시 뜨는 모달.
 *
 * 처음엔 이 버튼이 GitHub "새 이슈 만들기" 링크로 바로 이동했는데, "그게 아니라 신고창
 * 뜨고 그거 제출하면 내가 볼 수 있게 해야지"라는 피드백으로 자체 폼+저장으로 교체함
 * (문서ID/기관/연도/감사종류/현재 URL은 계속 자동으로 같이 실어 보냄 — 사용자가 직접
 * 안 적어도 됨. 백엔드는 GET /admin/reports?token=... 로 관리자만 조회).
 *
 * @param {object} doc - DetailPage의 문서 상세 데이터
 * @param {string} docId - useParams()의 id (URL 슬러그 아님, 실제 document_id)
 * @param {() => void} onClose
 */
export default function ReportErrorModal({ doc, docId, onClose }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("idle"); // idle | submitting | done | error
  const [errorText, setErrorText] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleSubmit(e) {
    e.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) return;
    setStatus("submitting");
    setErrorText("");
    try {
      await submitErrorReport({
        document_id: docId,
        institution: doc.institution,
        year: doc.year,
        audit_type: doc.audit_type,
        message: trimmed,
        page_url: window.location.href,
      });
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setErrorText(err.message || "신고 접수에 실패했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <div
        className="report-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {status === "done" ? (
          <>
            <p className="report-modal-success">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="10" stroke="var(--success-text)" strokeWidth="1.8" />
                <path d="M8 12.5l2.5 2.5L16 9.5" stroke="var(--success-text)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              신고가 접수됐습니다. 확인해 볼게요, 감사합니다.
            </p>
            <div className="report-modal-actions">
              <button type="button" className="report-modal-submit" onClick={onClose}>
                닫기
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 id="report-modal-title" className="report-modal-title">
              데이터 오류 신고
            </h2>
            <p className="report-modal-meta">
              {doc.institution || "기관명 미상"}
              {doc.year ? ` · ${doc.year}년` : ""}
              {doc.audit_type ? ` · ${doc.audit_type}` : ""} · 문서 {docId}
            </p>
            <textarea
              ref={textareaRef}
              className="report-modal-textarea"
              placeholder="어떤 부분이 이상한가요? (예: 감사종류가 잘못 표시됨 / 기관명이 깨져 보임 / 법령 링크가 엉뚱한 곳으로 감 등)"
              value={message}
              maxLength={MAX_LEN}
              onChange={(e) => setMessage(e.target.value)}
              rows={5}
            />
            <div className="report-modal-charcount">
              {message.length}/{MAX_LEN}
            </div>
            {status === "error" && <p className="error-message">{errorText}</p>}
            <div className="report-modal-actions">
              <button type="button" className="report-modal-cancel" onClick={onClose}>
                취소
              </button>
              <button
                type="submit"
                className="report-modal-submit"
                disabled={!message.trim() || status === "submitting"}
              >
                {status === "submitting" ? "제출 중..." : "제출"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
