/**
 * 신뢰도 배지 — 백엔드가 이미 "신뢰도 높음" / "일부 참고" 같은 사람이 읽을 문자열로
 * 변환해서 내려주므로(main.py CONFIDENCE_LABELS), 여기서는 값에 따라 색만 다르게 표시.
 */
export default function ConfidenceBadge({ label }) {
  const isHigh = label === "신뢰도 높음";
  return (
    <span className={`badge ${isHigh ? "badge-high" : "badge-partial"}`}>
      {label}
    </span>
  );
}
