import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { buildCasePath } from "../caseUrl.js";
import { getCaseDetail, getCaseSummary } from "../api.js";
import useDocumentTitle from "../useDocumentTitle.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import highlightMatches from "../highlight.jsx";

const SUMMARY_FIELDS = [
  { key: "summary_point", label: "지적사항" },
  { key: "summary_cause", label: "원인" },
  { key: "summary_action", label: "조치" },
  { key: "summary_result", label: "결과" },
];

const SCROLL_TOP_THRESHOLD = 480;

// 원문이 그냥 통짜 텍스트로 나열돼서 보기 힘들다는 피드백(2026-08-12) 대응 — 감사보고서
// 원문에 자주 나오는 구조 패턴(제목, 번호/가나다 항목, 로마숫자 장 구분, 괄호라벨)만
// 정규식으로 감지해서 굵게+여백을 주고, 나머지 본문은 그대로 둠. 공사마다 양식이 달라
// 완벽한 파싱은 안 되지만, 눈에 띄는 패턴만 강조해도 완전히 평평한 텍스트보다는 훨씬
// 스캔하기 쉬워짐.
//
// 2026-08-12 2차: "가." "1."처럼 구두점 있는 경우보다 "가 업무개요"처럼 구두점 없이
// 띄어쓰기만 있는 경우가 더 흔했음 — 구두점을 선택(optional)으로 완화.
//
// 2026-08-12 3차: 실제 문서로 두 가지 더 발견—
//   1) "(현황)" "(위법부당내용)" 처럼 그 줄 전체가 괄호 라벨 하나뿐인 경우가 있는데
//      아무 패턴에도 안 걸려서 문단에 그냥 흡수돼 이상하게 붙어 보였음 -> 패턴 추가.
//   2) "○ ..." 불릿은 원래 짧은 소제목이 아니라 그 자체로 긴 문단(사실상 목록 항목)을
//      이끄는 경우가 많았음. 이걸 헤더 취급해서 굵게 만들면, 같은 문장이 "첫 줄만 굵고
//      나머지는 안 굵은" 상태로 쪼개져 보여서 오히려 더 이상해 보였음 — 그래서 불릿은
//      "새 문단 시작" 신호로만 쓰고(굵게 안 함, 문단 간 여백만 살짝 줌) 구분함.
// 문서 제목 줄 — HEADING_LABEL_PATTERNS에도 포함되지만(굵게 처리 대상), 목차/타이포에서
// "제목"은 다른 헤딩과 구분해서 더 크게 세리프로 보여주고 목차 항목에서는 제외하려고
// 별도 상수로 뺌(law.go.kr류 공식 문서 타이포 요청, 2026-08-12)
//
// 2026-08-14: "제 목】: 직원의 의무 위반"처럼 원본은 "【제 목】: ..." 형식인데 문서
// 맨 앞 여는 대괄호(【 또는 [)가 추출 단계에서 유실된 문서를 실제로 확인함(건강보험
// 심사평가원 다수 — textutils.py의 extract_title()에서 탭 타이틀 쪽은 이미 같은
// 문제를 2026-08-13에 고쳤지만, 프론트 렌더링(굵게/큰 제목 스타일) 쪽은 이 정규식이
// "목" 바로 뒤에 콜론/공백만 허용해서 여전히 못 잡고 있었음("제목이 안 굵고 크기도
// 작다"는 피드백). 여는/닫는 대괄호를 전부 선택(optional)으로 둬서 유실된 경우
// ("제 목】...")와 온전한 경우("【제 목】...", "[제 목] ...") 둘 다 커버함.
const TITLE_RE = /^[[【]?제\s*목\s*[\]】]?\s*[:：]?\s/;

// 2026-08-14: 상단 필드 라벨("제목", "관계부서" 등)이 콜론 없이 공백만으로 구분되는
// 문서가 실제로 있음(예: "소관부서 [부서]사업소") — 그렇다고 콜론을 완전히 선택
// (optional, `[:：]?`)로 두면 "조치부서는 ~"/"관련자 T은 ~"처럼 라벨 단어 뒤에 조사가
// 바로 붙은 평범한 본문 문장까지 걸려버림(실제 문서 "관련자 T은 2019. 1. 31.부터..."로
// 확인). 그래서 콜론 **또는** 공백 중 하나는 반드시 있어야 매칭되게
// `(?:[:：]\s*|\s+)`로 강제함 — textutils.py의 _TITLE_LINE_RE와 같은 이유·같은 해법.
const LABEL_SEP = "(?:[:：]\\s*|\\s+)";

// (현황) (위법부당내용) 처럼 줄 전체가 괄호 라벨뿐인 경우 — HEADING_LABEL_PATTERNS와
// splitIntoBlocks(표 블록 안에서 날짜 셀 하나만 있는 줄과 구분할 때) 둘 다에서 씀.
const PAREN_LABEL_RE = /^[(（][^()（）]{1,20}[)）]$/;

const HEADING_LABEL_PATTERNS = [
  TITLE_RE, // 제목 / 제 목
  /^징\s*계\s*(대\s*상\s*자|종\s*류|사\s*유)/, // 징계대상자 / 징 계 종 류 / 징 계 사 유
  // 2026-08-14: "관계기관"뿐 아니라 "관계부서"("♣♣팀" 등)도 실제 문서로 확인 —
  // 기관/부서를 하나로 묶고, 위 LABEL_SEP로 구분자 필수화(콜론 없는 "소관부서 [부서]
  // 사업소" 형태도 커버하면서 "조치부서는 ~" 같은 본문 오탐은 막음).
  new RegExp(`^(소\\s*관|조\\s*치|관\\s*계)\\s*(기\\s*관|부\\s*서)\\s*${LABEL_SEP}\\S`),
  /^조\s*치\s*기\s*한\s*[:：]?/, // 조치기한
  // 2026-08-14: "감사명 : 공모사업 운영실태 특정감사" — 문서 맨 위 개요 라벨.
  new RegExp(`^감\\s*사\\s*명\\s*${LABEL_SEP}\\S`),
  // 2026-08-14: "관 련 자 : U(경고)" — 콜론이 있을 때만 라벨로 인정(콜론 없이 "관련자
  // T은 2019..."처럼 본문 주어로 쓰이는 경우가 실제 문서에 흔해서, 오탐 방지 위해
  // 이 라벨만 콜론 필수로 좁힘 — "관련자 의견"처럼 콜론 없는 소제목은 놓치지만,
  // 본문을 헤딩으로 잘못 굵게 만드는 것보다 안전한 쪽을 택함).
  /^관\s*련\s*자\s*[:：]\s*\S/,
  // 2026-08-14: "일련번호 2025-03-001" — 처분서 양식 상단 식별번호, 콜론 없이 공백만 씀.
  new RegExp(`^일\\s*련\\s*번\\s*호\\s*${LABEL_SEP}\\S`),
  // 2026-08-14: "내 용" 단독 줄 — 그 줄 전체가 이 라벨 하나뿐일 때만(내용을 서술하는
  // 본문 문장 첫머리에 "내용"이 오는 경우와 헷갈리지 않게 줄 전체 일치로 한정).
  /^내\s*용\s*$/,
  // 2026-08-19: 유니코드 로마숫자(Ⅰ,Ⅱ,Ⅲ...)뿐 아니라 라틴 알파벳 I/V/X도 같은
  // 문자 클래스에 있었음 — ASCII 로마숫자로 표기된 실제 문서 사례는 이 저장소에
  // 한 번도 검증된 적 없는 방어적 코드였는데, 표 셀 값 "X"(미인증 표시)로 시작하는
  // 줄("X 기능 개선시...")이 전부 장 제목으로 오인되는 실사용 버그로 이어짐(사용자
  // 제보: [표 3] 웹 접근성 품질 미인증 현황). 검증된 유니코드 로마숫자만 남기고
  // 라틴 알파벳 단독 매칭은 제거.
  /^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?\s/, // Ⅰ. Ⅱ. 로마숫자 장 구분
  // [표 1] [별표 1] [붙임] [참고] 같은 대괄호 캡션만 — "[부서]"(익명화 placeholder,
  // 문장 맨 앞에 수도 없이 나옴)까지 통째로 걸려서 문장을 헤딩 취급하던 심각한 오탐을
  // 6차 수정에서 발견(실제 문서로 확인) — 캡션 키워드로 한정해서 좁힘.
  // 2026-08-13 9차: "[표-1]"처럼 키워드와 번호 사이가 공백이 아니라 하이픈인 경우도
  // 실제 문서로 발견 — [\s-]*로 하이픈도 허용(TABLE_CAPTION_RE도 동일하게 수정).
  // 2026-08-14: "사진"도 "[사진 1]"처럼 번호 붙는 캡션으로 실제 문서에서 269건 확인돼서
  // 같은 그룹에 추가(아래 10차 조사 참고).
  /^\[(표|그림|별표|붙임|별첨|참고|서식|양식|사진)[\s-]*\d*\]/,
  /^【.+】/, // 【 구간표시 】
  // 2026-08-13 8차: "<☆☆☆☆☆본부 직장내 괴롭힘 관련자 현황>"처럼 표/현황 캡션이
  // 꺾쇠괄호(<>)로 감싸인 경우도 실제 문서에서 발견됨 — 【】와 완전히 같은 이유로 줄
  // 전체를 캡션으로 인정(일반 문장이 줄 전체를 <>로 감싸는 경우는 사실상 없음).
  /^<.+>$/,
  PAREN_LABEL_RE, // (현황) (위법부당내용) 처럼 줄 전체가 괄호 라벨뿐인 경우
  // 2026-08-13 7차: "[판단근거]" "[지적사항]" "[조치할 사항]" 처럼 대괄호 라벨이 그
  // 줄 통째로 나오는 양식이 실제 문서에 많음(제목/번호항목 없이 이 방식만 쓰는 문서는
  // 전부 강조 없이 밋밋한 본문으로만 보였음). 위 캡션 패턴과 달리 "[부서]사무소는..."처럼
  // 대괄호 뒤에 문장이 이어지면 여기 안 걸림(줄 끝 $ 고정) — 그래서 6차 수정 때 막았던
  // "[부서]" 문장 오탐과는 겹치지 않음(그 placeholder는 항상 문장 중간에 이어지는 형태로만
  // 실제 문서에서 확인됨, 대괄호 하나로 줄 전체를 채우는 사례는 못 찾음).
  /^\[[^[\]]{1,20}\]$/,
  // 2026-08-14 10차: 위 "줄 전체가 라벨뿐"(바로 위 패턴, $ 고정)이라 뒤에 내용이 바로
  // 이어지는 경우("[통보] ○○팀장은...")를 못 잡던 라벨들 — Railway DB 67,751건 전수조사로
  // 정확한 영향 문서 수까지 확인 후 추가(짐작 아님). 표/그림처럼 뒤에 번호가 오는 게
  // 아니라 라벨 하나로 완결되는 형태라 별도 그룹으로 관리. 영향 큰 순서:
  // 소관부점의견(824건)/통보(796건)/관련자(601건, 기존 패턴으로 1,287건은 이미 인식되고
  // 있었음 — 뒤에 내용 붙는 경우만 보강)/모범사례(351건)/조치할사항(101건, 마찬가지로
  // 547건은 기존 패턴으로 이미 인식됨)/현지조치(151건)/행정상조치(149건)/부서주의(144건)/
  // 부서명(22건, 애초에 이 조사를 시작하게 만든 라벨) 등. "[시정(회수)]"처럼 대괄호 안에
  // 괄호가 또 있는 복합 변형은 이번엔 제외(건수 적고 별도 검증 필요, 다음에 볼 것).
  // 겹치는 라벨(예: 개선요구/개선, 관련자의견/관련자)은 더 긴 쪽을 먼저 둬서 짧은 쪽이
  // 먼저 매칭돼 뒤에 남은 글자 때문에 전체 매칭이 실패하는 일이 없게 순서 조정.
  /^\[(소\s*관\s*부\s*점\s*의\s*견|통\s*보|관\s*련\s*자\s*의\s*견|관\s*련\s*자|모\s*범\s*사\s*례|권\s*고|개\s*선\s*요\s*구|개\s*선|조\s*치\s*할\s*사\s*항|현\s*지\s*조\s*치|행\s*정\s*상\s*조\s*치|부\s*서\s*주\s*의|부\s*서\s*명|덧\s*붙\s*임|첨\s*부|신\s*분\s*상\s*조\s*치|관\s*련\s*부\s*서\s*의\s*견|관\s*련\s*부\s*서|시\s*정\s*요\s*구|현\s*지\s*시\s*정|시\s*정)\s*\]/,
];

// 새 문단(목록 항목) 시작 신호로만 쓰는 불릿 — 굵게 만들지 않음(위 3차 수정 이유 참고).
// "❍"(U+274D)도 실제 문서에서 "○"와 같은 용도로 쓰이는 걸 확인해서 추가함(4차).
// "※"/"*"도 실제 문서에서 각주(비고) 여러 개를 줄바꿈으로 나열할 때 씀 — 없으면
// "※ ... ※ ... ※ ..."가 한 문단으로 다 이어붙어서 뒤섞여 보임(5차, 실제 문서로 확인).
// 2026-08-13 7차: "①②③..." 원문자 번호도 "가/나/다"처럼 하위 항목을 나열할 때 씀
// (예: "[지적내용]\n① 『인사규정』...\n② 『복무규정』..."). 지금까지는 이게 그냥
// body로 뭉쳐서 항목 구분이 안 보였음 — 다른 불릿과 같은 이유로 굵게는 안 하고
// 문단 시작 신호로만 추가.
//
// 2026-08-13 7차 회귀: 원문자는 다른 불릿과 달리 "①제1항의..."처럼 공백 없이 문장
// 중간 조항번호로도 흔히 쓰임(특히 띄어쓰기가 통째로 빠진 추출 문서에서). 이런 줄이
// PDF 줄바꿈으로 우연히 문단 맨 앞에 오면, 같은 조항 나열인데 ①②는 한 문단에 붙어있고
// ③만 새 줄 첫머리라는 이유로 뜬금없이 쪼개지는 문제가 실제 문서로 확인됨(한국수력원자력
// 사례). 실제 목록 항목은 항상 "① 검강검진..."처럼 뒤에 공백이 있으므로, 원문자만
// 공백 필수(\s+)로 다른 불릿(\s*)과 다르게 조건을 둬서 구분함.
const BULLET_RE =
  /^(?:[-–—□○◦▪‣·❍※*]\s*\S|[①②③④⑤⑥⑦⑧⑨⑩]\s+\S)/;

// 2026-08-14: "□"/"○" 같은 원문 불릿 기호가 PDF 폰트 글리프 매핑 문제로 텍스트 추출
// 시 라틴 알파벳 "q"/"m"으로 저장된 문서를 실제로 확인함(예: "q ｢취업규칙｣ 제9조
// 제1항...", "m 지부위원장인 [부서]은..." — 원본 PDF에는 □/○로 보임, "네모가 q로
// 나온다"는 피드백). 뒤에 오는 글자가 익명화 placeholder 기호(#, @◎@ 등 종류가
// 워낙 다양함)일 때도 있어서 괄호/한글을 일일이 나열하는 대신 "소문자 알파벳으로
// 이어지는 진짜 영어 단어가 아니면 전부 허용"으로 반대로 좁힘(이 말뭉치가 한국어
// 문서라 줄 맨 앞에 진짜 영어 단어 "q"/"m" 하나만 오는 경우는 사실상 없음). q/m
// 단독 글자 뒤에 공백이 반드시 있어야 하므로 "management" 같은 영단어는 애초에
// 안 걸림. 매칭되면 화면엔 원래 기호(□/○)로 치환해서 보여줌(normalizeGlyphBullet).
const GLYPH_BULLET_RE = /^([qm])\s+(?=[^a-z\s])/;
const GLYPH_BULLET_MAP = { q: "□", m: "○" };

/** GLYPH_BULLET_RE에 매칭되는 줄의 맨 앞 글자(q/m)만 원래 기호(□/○)로 바꿔치기.
 * 매칭 안 되면 원본 그대로 반환(일반 불릿엔 영향 없음). */
function normalizeGlyphBullet(trimmed) {
  const m = trimmed.match(GLYPH_BULLET_RE);
  if (!m) return trimmed;
  return GLYPH_BULLET_MAP[m[1]] + trimmed.slice(m[1].length);
}

// 2026-08-14: "[부서]" 익명화 placeholder가 부서명뿐 아니라 사람 이름·행사명 등도
// 전부 뭉뚱그려 마스킹한 것으로 실제 문서로 확인됨(예: "[부서]이 초과근무를 했다" —
// 문맥상 사람인데 "부서"라고 읽혀서 문장이 이상해짐, 사용자 피드백). 뒤에 오는
// 글자(조사인지 조직 접미어인지)로 부서/사람을 구분해보려 했으나, "[부서]와 공사로부터
// [부서] 행사의..."처럼 행사명에도 조사가 바로 붙는 반례가 실제로 있어서 안전하게
// 구분 불가 — 대신 종류를 특정하지 않는 원문 마스킹 관례(○○○)로 화면 표시만
// 통일함(원문 자체·구조 분류는 안 건드림). "부서"라는 확신에 찬 오독은 없어지고,
// 그 대신 아무것도 단정하지 않는 표기가 됨.
function maskDeptPlaceholder(text) {
  return text.replaceAll("[부서]", "○○○");
}

// 2026-08-12 4차: 전처리 단계에서 표/그림 이미지 자체는 지웠지만, 표 안 내용이 셀 구분
// 없이 텍스트로만 남아있는 경우가 있음(예: "근무일자 근태구분 직번 질병명 ~201905
// 질병휴직 [부서] ..."). 이걸 일반 문단처럼 공백으로 이어붙이면 뜻 없는 단어 나열이라
// 오히려 더 안 읽힘 — "【표 N】"/"[표 N]"/"【그림 N】"/"[그림 N]" 캡션 직후에 이어지는
// 문단은 "표/그림에서 남은 조각"으로 보고 접어서(기본 숨김) 따로 표시함.
// 실제 문서로 확인해보니 표 데이터 바로 뒤에 빈 줄 없이 "❍ ..." 같은 실제 문장이 곧바로
// 이어지는 경우가 있어서, 그 경계를 잡으려면 BULLET_RE에 "❍"가 포함돼 있어야 함(위에서 추가).
// 2026-08-13 9차: "[표-1]"처럼 키워드-번호 사이가 하이픈인 경우도 실제 문서로 발견돼서
// [\s-]*로 하이픈 허용(위 HEADING_LABEL_PATTERNS의 동일 패턴과 이유 같음).
// 2026-08-14: "[관련자 명세]"뿐 아니라 "[공직기강 점검 2회 적발자 현황]"처럼 표/그림
// 키워드가 아예 없는 캡션도 실제 문서로 다수 확인 — 하나하나 키워드로 나열하는 대신
// "현황/내역/명세/명단/실태"로 끝나는 대괄호 캡션은 통계·집계표일 가능성이 높다고
// 보고 통째로 표 트리거에 포함시킴(괄호 안 앞부분 텍스트는 안 가리고 끝 키워드만 봄).
// "[판단근거]"/"[지적사항]"처럼 실제 서술 문단을 이끄는 라벨은 이 키워드로 안 끝나서
// 안 걸림(6차 수정 때 겪은 "표 아닌데 표 취급" 오탐과 같은 이유로 끝 $ 고정 유지).
const TABLE_CAPTION_RE =
  /^[【[]\s*(표|그림|별표)[\s-]*\d*\s*[】\]]|^[【[][^【】[\]]*(?:명세|현황|내역|명단|실태)\s*[】\]]$/;

// 2026-08-12 6차: 표 데이터 뒤에는 보통 "자료: ○○ 제출자료 재구성" 같은 출처 표기가
// 붙는데, 그 바로 뒤에 헤딩/불릿 없이 실제 문장이 곧장 이어지는 경우가 있었음(실제 문서로
// 확인 — "자료: 지사 제출자료 및 현지 확인 결과 재구성" 다음 줄에 "♠♡지사에서는 ①
// 차량번호..."라는 진짜 감사 내용이 헤딩/불릿 없이 바로 나옴). 이걸 못 끊으면 표 블록이
// 실제 내용까지 통째로 삼켜서 접힌 박스 안에 숨겨버리는 심각한 문제가 생김 — "자료:"/
// "출처:" 줄을 표 블록을 반드시 끝내는 경계로 인식시킴.
const SOURCE_NOTE_RE = /^(자료|출처)\s*[:：]/;

// 2026-08-14: "본 문서의 감사요지 및 귀책내용이 누설되어 문제가 발생되지 않도록 특별
// 문서보안조치 지시 및 관리를 요구합니다." — 페이지마다 반복되는 문서보안 고정 문구가
// 텍스트 추출 시 그 페이지 위치 그대로 본문 문장 한가운데 섞여 들어옴(실제 문서에서 한
// 문서에 10번 넘게 반복 확인, "본문 중간에 이상한 게 낀다" 피드백). 내용이 없는 반복
// 상용구라 자료/출처 표기와 같은 급으로 취급해서 작게 표시 — 지우지는 않음(원문 그대로
// 다 보여준다는 기존 방침 유지, 눈에만 덜 띄게).
const SECURITY_NOTICE_RE = /^본\s*문서의\s*감사요지\s*및\s*귀책내용이\s*누설되어/;

// 2026-08-14: 본문 중 붙어서 등장하는 각주 참조("87,818,181원1)", "위임2)")를 문서
// 전체에서 미리 스캔해서 각주 번호 집합을 만들어둠 — 그 번호로 시작하는 줄이 나오면
// 진짜 소제목("1) 태양광...")이 아니라 각주 본문("1) 권익위의 의결서 내에는...")일
// 가능성이 높다고 판단하는 데 씀(splitIntoBlocks 참고). 공백/숫자가 아닌 문자 바로
// 뒤에 붙은 "숫자)"만 참조로 인정 — 줄 맨 앞 목록 번호("1) 업무개요")는 앞에 아무
// 문자도 없어서 이 정규식엔 애초에 안 걸림.
const FOOTNOTE_REF_RE = /[^\s\d](\d{1,2})\)/g;
// 각주 본문 후보 줄 — 목록 헤딩과 똑같은 모양("숫자) 내용")이라 이것만으로는 구분
// 못 함, splitIntoBlocks에서 위 참조 집합 + 직전 블록 종류까지 같이 봐야 함.
const FOOTNOTE_DEF_RE = /^(\d{1,2})\)\s+\S/;

/** 줄 하나를 "heading"(굵게, 독립 블록) / "bullet"(새 문단 시작, 안 굵음) /
 * "caption"(작고 흐린 출처/상용구 표기, 독립 블록) / "body"(이어지는 일반 줄) /
 * "blank"(빈 줄, 문단 구분)로 분류. 각주("footnote")는 문서 전체 맥락(참조 번호,
 * 직전 블록 종류)이 필요해서 여기가 아니라 splitIntoBlocks에서 별도로 먼저 검사함. */
function classifyLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return "blank";

  // 가/나/다 단독 소제목은 원문에서 보통 그 줄 전체가 짧은 편(예: "가 업무개요") —
  // 본문 문장이 우연히 "나"로 시작하는 경우까지 오탐하지 않게 길이 상한을 둠
  if (
    /^[가나다라마바사아자차카타파하][.)]?\s+\S/.test(trimmed) &&
    trimmed.length <= 24
  ) {
    return "heading";
  }
  // 2026-08-18: "1. 2. 3." 번호 항목도 같은 이유로 길이 상한을 둠 — 원문에서 "1. 관계
  // 법령 및 규정"처럼 짧은 소제목 뒤에 줄바꿈 없이 긴 본문이 바로 이어 붙는 경우(PDF
  // 원본부터 그렇게 한 줄이었음, 실제 문서 e6bae4491398a6b2로 확인)가 있어서, 길이
  // 상한 없이는 그 문단 전체가 헤딩(진하게)으로 잘못 렌더링됨. 위 가/나/다 케이스와
  // 동일한 상한(24자)을 씀 — 실제 짧은 번호 헤딩("1. 감사배경 및 목적" 등)은 다 그
  // 안에 들어옴.
  if (/^\d{1,2}[.)]\s+\S/.test(trimmed) && trimmed.length <= 24) {
    return "heading";
  }
  if (HEADING_LABEL_PATTERNS.some((re) => re.test(trimmed))) return "heading";
  if (SOURCE_NOTE_RE.test(trimmed) || SECURITY_NOTICE_RE.test(trimmed))
    return "caption";
  if (BULLET_RE.test(trimmed) || GLYPH_BULLET_RE.test(trimmed))
    return "bullet";
  return "body";
}

/** 원문을 문단 단위 블록으로 나눔(렌더링 전 순수 데이터 단계) — renderRawText와
 * buildToc가 같은 블록 목록을 같이 써서 목차 항목과 실제 앵커가 항상 일치하게 함
 * (law.go.kr류 조문 목차 참고 요청, 2026-08-12).
 *
 * 원문의 줄바꿈(\n)은 대부분 PDF가 페이지 폭에 맞춰 끊은 자리라 실제 문장/문단 구분과
 * 다름(심하면 "근무하" / "고 있는" 처럼 단어 중간에서도 끊김) — 그 줄을 그대로 각자 블록
 * 으로 렌더링하면 원래 한 문장이 짧은 조각으로 뚝뚝 끊겨 보임(2026-08-12 피드백).
 * 그래서 헤딩/불릿 줄이나 빈 줄(진짜 문단 구분)을 만나기 전까지 이어지는 일반 줄들은
 * 공백으로 합쳐서 하나의 문단으로 흘러가게 함. */
function splitIntoBlocks(text) {
  // 문서 전체에서 "숫자)" 형태로 붙어 나온 각주 참조 번호를 미리 수집(각주 판별용,
  // FOOTNOTE_REF_RE 주석 참고).
  const footnoteNums = new Set();
  for (const m of text.matchAll(FOOTNOTE_REF_RE)) {
    footnoteNums.add(m[1]);
  }

  const blocks = [];
  let para = [];
  let paraType = "body";
  let nextIsTable = false; // 표/그림 캡션 바로 다음 문단인지
  // 직전에 flush된 블록의 타입 — 각주 판별에 씀(아래 각주 분기 참고). 목록 헤딩은
  // 항상 그 앞이 "heading"/"bullet"(다른 항목의 헤딩/본문)이고, 각주는 페이지 하단에
  // 있던 게 그대로 이어붙은 거라 항상 그 앞이 미완성 "body" 문단(또는 바로 위 각주)임.
  let prevType = null;

  function flushPara() {
    if (para.length === 0) return;
    blocks.push({ type: paraType, text: para.join(" ") });
    prevType = paraType;
    para = [];
    paraType = "body";
  }

  for (const rawLine of text.split("\n")) {
    const trimmed = rawLine.trim();

    if (!trimmed) {
      flushPara();
      continue;
    }

    // 2026-08-14: 각주 판별 — classifyLine의 일반 "숫자) 내용" 헤딩 패턴보다 먼저
    // 검사해야 함. 두 조건을 동시에 요구해서 오탐을 좁힘: ①이 번호가 본문 어딘가에
    // 참조로 붙어 나온 적이 있고, ②바로 앞이 아직 안 끝난 본문 문단(또는 바로 위
    // 각주)일 것 — 진짜 목록 헤딩("1) 태양광...")은 항상 상위 헤딩/불릿 블록 바로
    // 다음에 오므로 ②를 만족하지 않아 여기 안 걸림(실제 문서로 확인).
    // "바로 앞"은 아직 flush 안 되고 누적 중인 para가 있으면 그 para의 타입(paraType),
    // 없으면 마지막으로 flush된 블록의 타입(prevType)임 — para가 비어있지 않을 때도
    // prevType만 보면 그 이전(이미 flush된) 블록 타입을 잘못 참조하게 됨.
    const effectivePrevType = para.length > 0 ? paraType : prevType;
    const footnoteMatch = FOOTNOTE_DEF_RE.exec(trimmed);
    if (
      footnoteMatch &&
      footnoteNums.has(footnoteMatch[1]) &&
      (effectivePrevType === "body" || effectivePrevType === "footnote")
    ) {
      flushPara();
      blocks.push({ type: "footnote", text: trimmed });
      prevType = "footnote";
      continue;
    }

    const kind = classifyLine(trimmed);

    // 2026-08-14: 표 데이터를 접어서 보여주는 중(paraType === "table")에 표 안 날짜
    // 셀 하나만 있는 줄("(2025. 8. 8.)")이 우연히 PAREN_LABEL_RE(괄호 라벨 헤딩)에도
    // 걸려서, 매 셀마다 표가 끊기고 남은 행은 표가 아닌 통짜 본문으로 새어나가던 문제를
    // 실제 문서("[공직기강 점검 2회 적발자 현황]" 표)로 확인함 — 표를 누적하는 중에
    // 나온 괄호 라벨 줄은 진짜 새 소제목이 아니라 표 셀 조각으로 보고 표 문단에
    // 그대로 흡수시킴(접힌 박스가 끊기지 않고 표 데이터 전체를 담게 됨).
    if (kind === "heading" && paraType === "table" && PAREN_LABEL_RE.test(trimmed)) {
      para.push(trimmed);
      continue;
    }
    if (kind === "heading") {
      flushPara();
      blocks.push({ type: "heading", text: trimmed });
      prevType = "heading";
      nextIsTable = TABLE_CAPTION_RE.test(trimmed);
      continue;
    }
    if (kind === "caption") {
      flushPara(); // 표 블록이 진행 중이었으면 여기서 확실히 끝냄(6차 수정 이유 참고)
      blocks.push({ type: "caption", text: trimmed });
      prevType = "caption";
      nextIsTable = false;
      continue;
    }
    if (kind === "bullet") {
      flushPara(); // 불릿은 새 항목 시작 — 앞 문단과 분리(표 캡션 뒤라도 여기서 끊음)
      paraType = "bullet";
      nextIsTable = false;
      para.push(normalizeGlyphBullet(trimmed));
      continue;
    }
    if (para.length === 0 && nextIsTable) {
      paraType = "table";
      nextIsTable = false;
    }
    para.push(trimmed);
  }
  flushPara();
  // 위 분류 로직(각주/헤딩/표 판별 등)은 전부 원본 "[부서]" 문자열 기준으로 이미
  // 끝난 뒤이므로, 화면에 보여줄 텍스트에만 마지막에 치환을 적용함 — classifyLine
  // 등이 "[부서]"를 헤딩으로 오인하지 않게 설계된 기존 로직(6차 수정)과 안 얽히게 함.
  return blocks.map((b) => ({ ...b, text: maskDeptPlaceholder(b.text) }));
}

/** 헤딩 블록에만 앵커 id를 붙여서 렌더링 — 목차(TocSidebar)가 이 id로 점프함.
 * id는 등장 순서 기반("heading-3")으로만 부여, buildToc와 항상 같은 순서/조건이어야 함.
 * 제목 줄(TITLE_RE)은 별도 "title" 타입으로 렌더링 — 다른 헤딩보다 크게, 세리프로. */
function renderRawText(blocks, query) {
  let headingIdx = 0;
  return blocks.map((b, i) => {
    if (b.type === "table") {
      return (
        <details key={i} className="raw-line-table">
          <summary>표/그림 데이터 (펼쳐보기)</summary>
          <div>{query ? highlightMatches(b.text, query) : b.text}</div>
        </details>
      );
    }
    if (b.type !== "heading") {
      return (
        <div key={i} className={`raw-line raw-line-${b.type}`}>
          {query ? highlightMatches(b.text, query) : b.text}
        </div>
      );
    }
    const isTitle = TITLE_RE.test(b.text);
    const id = `heading-${headingIdx++}`;
    return (
      <div
        key={i}
        id={id}
        className={`raw-line ${isTitle ? "raw-line-title" : "raw-line-heading"}`}
      >
        {query ? highlightMatches(b.text, query) : b.text}
      </div>
    );
  });
}

/** 목차 항목만 뽑음 — renderRawText의 id 채번 방식과 반드시 같은 순서/조건("heading"
 * 블록만, 등장 순서대로 — 제목도 포함해서 카운트)이어야 앵커가 안 어긋남. 다만 목차
 * 화면에는 제목 자체는 안 보여줌(페이지에 이미 큼직하게 있어서 중복). */
function buildToc(blocks) {
  let headingIdx = 0;
  const items = [];
  for (const b of blocks) {
    if (b.type !== "heading") continue;
    const id = `heading-${headingIdx++}`;
    if (TITLE_RE.test(b.text)) continue;
    items.push({ id, text: b.text });
  }
  return items;
}

function TocSidebar({ items }) {
  if (items.length < 3) return null; // 항목 적으면 스크롤 한 번이면 끝 — 목차가 노이즈만 됨

  function handleClick(e, id) {
    e.preventDefault();
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <nav className="toc-sidebar" aria-label="원문 목차">
      <p className="toc-label">목차</p>
      <ol>
        {items.map((item) => (
          <li key={item.id}>
            <a href={`#${item.id}`} onClick={(e) => handleClick(e, item.id)}>
              {item.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export default function DetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const location = useLocation();
  const navigate = useNavigate();

  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showScrollTop, setShowScrollTop] = useState(false);

  // 4줄 요약 — "요약보기" 버튼을 눌러야 채워짐(§4.5 온디맨드, POST /documents/{id}/summary).
  // summary === null이면 아직 안 본 상태. doc에 이미 캐싱된 값이 있으면 API 호출 없이 그대로 씀.
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState(null);

  const backLink = query ? `/?q=${encodeURIComponent(query)}` : "/";

  // 탭 타이틀 — 제목 파싱 실패한 소수 문서는 기관명으로, 그것도 없으면 그냥 기본 타이틀
  // (useDocumentTitle이 falsy면 안 건드림) 유지. "공공감사데이터 검색" 접미사를 붙여서
  // 여러 탭 열어놨을 때 어느 서비스인지 구분되게 함.
  useDocumentTitle(
    doc && (doc.title || doc.institution)
      ? `${doc.title || doc.institution} - 공공감사데이터 검색`
      : null,
  );

  // raw_text -> 블록 목록은 doc이 바뀔 때만 다시 계산(문서 하나가 꽤 길어서 매 렌더마다
  // 다시 파싱하면 낭비) — renderRawText(본문)와 buildToc(목차)가 같은 블록 목록을 공유
  const blocks = useMemo(
    () => (doc ? splitIntoBlocks(doc.raw_text) : []),
    [doc],
  );
  const tocItems = useMemo(() => buildToc(blocks), [blocks]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);
    setCopied(false);
    setSummary(null);
    setSummaryLoading(false);
    setSummaryError(null);

    getCaseDetail(id)
      .then((data) => {
        if (!cancelled) setDoc(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err.message || "상세 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // 예전 링크(/documents/:id)나 title 파싱이 안 됐던 시점에 만들어진 URL로 들어온
  // 경우, 문서 로드가 끝나 title/institution/year를 알게 되면 새 URL(/cases/:id/:slug)로
  // 조용히 교체함(replace라 히스토리에 새 엔트리 안 남고, 뒤로가기는 여전히 검색 결과로 감).
  // 이미 최신 slug와 일치하면(캐노니컬 링크로 바로 들어온 경우) 아무것도 안 함.
  useEffect(() => {
    if (!doc) return;
    const canonicalPath = buildCasePath(doc.id, doc);
    if (location.pathname !== canonicalPath) {
      navigate(`${canonicalPath}${location.search}`, { replace: true });
    }
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps -- location/navigate는 매 렌더 안정적이지 않아 제외, doc만 트리거로 충분

  useEffect(() => {
    function onScroll() {
      setShowScrollTop(window.scrollY > SCROLL_TOP_THRESHOLD);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function handleShowSummary() {
    if (summary || summaryLoading || !doc) return;

    // doc 조회 시점에 이미 둘 다 캐싱돼 있으면(예전에 누가 먼저 생성해둔 경우) API 호출 없이
    // 바로 표시 — 구조화/자유형 둘 중 하나라도 아직 없으면 서버에 다시 요청(그쪽만 새로 생성됨)
    const structuredCached = doc.summary_point || doc.summary_failed;
    const freeformCached = doc.summary_freeform || doc.summary_freeform_failed;
    if (structuredCached && freeformCached) {
      setSummary({
        summary_point: doc.summary_point,
        summary_cause: doc.summary_cause,
        summary_action: doc.summary_action,
        summary_result: doc.summary_result,
        summary_failed: doc.summary_failed,
        summary_freeform: doc.summary_freeform,
        summary_freeform_failed: doc.summary_freeform_failed,
      });
      return;
    }

    setSummaryLoading(true);
    setSummaryError(null);
    getCaseSummary(id)
      .then((data) => setSummary(data))
      .catch((err) =>
        setSummaryError(err.message || "요약을 가져오지 못했습니다."),
      )
      .finally(() => setSummaryLoading(false));
  }

  function handleCopy() {
    if (!summary) return;
    const text = SUMMARY_FIELDS.map(
      ({ label, key }) => `${label}: ${summary[key] || "미기재"}`,
    ).join("\n");
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      })
      .catch(() => {
        // 클립보드 API를 막아둔 브라우저 환경 — 조용히 무시 (버튼은 그대로 남아있어 재시도 가능)
      });
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (loading) {
    return (
      <div className="app-main detail-page">
        <BackLink to={backLink} />
        <p className="loading-message">불러오는 중…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-main detail-page">
        <BackLink to={backLink} />
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="app-main detail-page">
      <BackLink to={backLink} />

      {/* 목차(TocSidebar)가 있는 문서(헤딩 3개 이상)는 좌-사이드바/우-본문 2단 레이아웃.
          detail-card와 summary-card를 detail-content로 같이 묶어서 오른쪽 열에 둠 —
          예전엔 summary-card가 detail-layout 밖에 있어서 목차 왼쪽 끝부터 전체폭으로
          걸쳐 보이고, 원문 박스랑 왼쪽 줄이 안 맞았음("상자 위치" 피드백, 2026-08-12) */}
      <div className="detail-layout">
        <TocSidebar items={tocItems} />
        <div className="detail-content">
          <div className="detail-card">
            <p className="detail-breadcrumb">
              <b>{doc.institution || "기관명 미상"}</b>
              {doc.year ? <span className="sep">›</span> : null}
              {doc.year ? `${doc.year}년` : ""}
              {doc.audit_type ? <span className="sep">›</span> : null}
              {doc.audit_type || ""}
            </p>
            <div className="detail-header">
              {/* source_url은 백필 전이거나 원본 경로를 못 구한 소수 문서는 null이라
                  백엔드가 그냥 필드를 null로 내려줌 — 조건부로 숨김(2026-08-13) */}
              {doc.source_url && (
                <a
                  href={doc.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="source-file-link"
                >
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M14 3h7v7M21 3l-9 9M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  원본 파일 보기
                </a>
              )}
              <ConfidenceBadge label={doc.confidence} />
            </div>

            {/* 검색 결과에서 이어져 들어온 경우(?q= 있음)에만 표시 — 이 사례가 왜 노출됐는지
                알려주고, 아래 원문에서 일치하는 부분을 하이라이트 처리함 */}
            {query && (
              <p className="search-context-note">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle
                    cx="11"
                    cy="11"
                    r="7"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                  <path
                    d="M21 21l-4.3-4.3"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
                '<strong>{query}</strong>' 검색 결과와 유사한 사례입니다 — 아래
                원문에서 일치하는 부분을 표시했습니다
              </p>
            )}

            {/* 원문은 요약을 기다릴 필요 없이 바로 보여줌 (§4.5 — 조회와 요약 생성을 분리).
                문단 단위로 나눠서 렌더링 — 제목/번호항목 같은 구조는 강조하고(renderRawText),
                나머지는 그대로 흘러가는 본문으로 둠. blocks는 useMemo로 doc이 바뀔 때만 재계산. */}
            <div className="raw-text">{renderRawText(blocks, query)}</div>
          </div>

          <div className="summary-card">
            {!summary && !summaryLoading && (
              <button
                type="button"
                className="summary-reveal-btn"
                onClick={handleShowSummary}
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                  <circle
                    cx="12"
                    cy="12"
                    r="4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                  />
                </svg>
                4줄 요약보기 (AI 생성, 몇 초 걸릴 수 있습니다.)
              </button>
            )}

            {summaryLoading && <p className="loading-message">요약 생성 중…</p>}

            {summaryError && <p className="error-message">{summaryError}</p>}

            {summary && summary.summary_failed && (
              <p className="summary-failed-notice">
                요약 어려움 — 원문 참고 필요
              </p>
            )}

            {summary && !summary.summary_failed && (
              <>
                <div className="ai-notice">
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                    <circle
                      cx="12"
                      cy="12"
                      r="4"
                      stroke="currentColor"
                      strokeWidth="1.6"
                    />
                  </svg>
                  AI가 원문을 분석해 자동 생성한 요약입니다. 정확한 내용은
                  원문을 확인하세요.
                </div>

                <div className="summary-toolbar">
                  <span className="summary-toolbar-label">4줄 요약</span>
                  <button
                    type="button"
                    className={`copy-btn ${copied ? "copied" : ""}`}
                    onClick={handleCopy}
                  >
                    {copied ? (
                      "복사됨"
                    ) : (
                      <>
                        <svg
                          width="13"
                          height="13"
                          viewBox="0 0 24 24"
                          fill="none"
                          aria-hidden="true"
                        >
                          <rect
                            x="9"
                            y="9"
                            width="12"
                            height="12"
                            rx="2"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                          <path
                            d="M5 15V5a2 2 0 0 1 2-2h10"
                            stroke="currentColor"
                            strokeWidth="1.6"
                          />
                        </svg>
                        요약 복사
                      </>
                    )}
                  </button>
                </div>

                <dl className="summary-list">
                  {SUMMARY_FIELDS.map(({ key, label }, i) => (
                    <div key={key} className="summary-item">
                      <dt>
                        <span className="num">{i + 1}</span>
                        {label}
                      </dt>
                      <dd>{summary[key] || "미기재"}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}

            {/* 문장형 요약 — 지적/원인/조치/결과 틀 없이 자유롭게 뽑은 버전. 위 박스 요약의
            성공/실패와는 별개 결과라 독립적으로 표시함 */}
            {summary &&
              (summary.summary_freeform || summary.summary_freeform_failed) && (
                <div className="summary-freeform-block">
                  <p className="summary-toolbar-label">문장으로 보기</p>
                  {summary.summary_freeform_failed ? (
                    <p className="summary-failed-notice">
                      문장형 요약 어려움 — 원문 참고 필요
                    </p>
                  ) : (
                    <p className="summary-freeform-text">
                      {summary.summary_freeform.split("\n").join(" ")}
                    </p>
                  )}
                </div>
              )}
          </div>
        </div>
      </div>

      <Link to={backLink} className="back-link bottom-back-link">
        ← 검색 결과 전체 보기
      </Link>

      <button
        type="button"
        className={`scroll-top-btn ${showScrollTop ? "visible" : ""}`}
        onClick={scrollToTop}
        aria-label="맨 위로"
        title="맨 위로"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M12 19V5M5 12l7-7 7 7"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  );
}

function BackLink({ to }) {
  return (
    <Link to={to} className="back-link">
      ← 검색으로 돌아가기
    </Link>
  );
}
