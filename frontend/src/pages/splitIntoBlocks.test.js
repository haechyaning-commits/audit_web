// DetailPage.jsx의 splitIntoBlocks() 유닛테스트.
//
// 이 프로젝트는 지금까지 자동화된 테스트가 없었고(STATUS.md 참고), 원문 파싱
// 로직(splitIntoBlocks/classifyLine 등 각주·헤딩·불릿 분류 휴리스틱) 수정마다
// 세션에서 Node로 함수만 수동으로 떼어내 합성 문서로 매번 다시 검증해왔음. 그
// 수동 검증 과정을 반복 가능한 유닛테스트로 옮겨서, 앞으로 이 휴리스틱을 건드릴
// 때 회귀를 바로 잡아낼 수 있게 함.
//
// splitIntoBlocks는 DetailPage.jsx에서 named export로 노출돼 있음(컴포넌트
// 자체는 default export로 그대로 둠, 동작 변경 없음).
import { describe, expect, it } from "vitest";
import { splitIntoBlocks } from "./DetailPage.jsx";

describe("splitIntoBlocks", () => {
  it("빈 줄로 구분된 두 문단을 별도 body 블록으로 나눔", () => {
    const blocks = splitIntoBlocks("첫 번째 문단입니다.\n\n두 번째 문단입니다.");
    expect(blocks.map((b) => b.type)).toEqual(["body", "body"]);
    expect(blocks[0].text).toBe("첫 번째 문단입니다.");
    expect(blocks[1].text).toBe("두 번째 문단입니다.");
  });

  it("빈 줄 없이 이어지는 줄은 공백으로 합쳐 하나의 body 문단이 됨", () => {
    const blocks = splitIntoBlocks("한 문장이 페이지 폭 때문에\n여러 줄로 끊긴 경우.");
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("body");
    expect(blocks[0].text).toBe("한 문장이 페이지 폭 때문에 여러 줄로 끊긴 경우.");
  });

  it("가/나/다 소제목을 heading으로 분류함", () => {
    const blocks = splitIntoBlocks("가. 업무 개요\n\n관련 내용은 다음과 같다.");
    expect(blocks[0]).toMatchObject({ type: "heading", text: "가. 업무 개요" });
    expect(blocks[1]).toMatchObject({ type: "body" });
  });

  it("○ 불릿으로 시작하는 줄은 bullet로 분류하고 굵게 만들지 않음", () => {
    const blocks = splitIntoBlocks("○ 첫 번째 지적사항\n○ 두 번째 지적사항");
    expect(blocks.map((b) => b.type)).toEqual(["bullet", "bullet"]);
  });

  it('"소관부서 [부서]사업소"처럼 라벨+값이 붙은 줄은 field로 분리함', () => {
    const blocks = splitIntoBlocks("소관부서 [부서]사업소");
    expect(blocks[0].type).toBe("field");
    expect(blocks[0].label).toBe("소관부서");
    expect(blocks[0].value).toBe("○○○사업소"); // maskDeptPlaceholder가 [부서]를 ○○○로 치환
  });

  it("짧은 한 줄짜리 각주 정의(임/함/음/됨 종결)는 footnote로 유지됨", () => {
    // footnoteNums는 문서 전체에서 "글자+숫자)" 형태의 인라인 참조를 스캔해서 채워짐
    // (FOOTNOTE_REF_RE) — 본문에 "위임1)" 같은 참조가 있어야 뒤의 "1) ..." 정의 줄이
    // 각주로 인식됨.
    const text = [
      "관련 규정에 따라 권한을 위임1)하였다.",
      "",
      "1) 총무처장에게 예산 집행 권한을 위임함",
    ].join("\n");
    const blocks = splitIntoBlocks(text);
    const footnote = blocks.find((b) => b.type === "footnote");
    expect(footnote).toBeDefined();
    expect(footnote.text).toBe("1) 총무처장에게 예산 집행 권한을 위임함");
  });

  it(
    "회귀 테스트(2026-08-27): 짧은 각주 정의 뒤에 무관한 정상 본문이 곧바로 이어지면 " +
      "그 본문까지 각주로 흡수하지 않고 body로 재분류함 — 원본 PDF와 웹페이지를 나란히 " +
      "비교한 사용자 스크린샷 제보로 확인된 버그(각주 1개만 작아야 하는데 본문 전체가 " +
      "다음 헤딩 전까지 계속 작은 글씨로 나왔음)",
    () => {
      const text = [
        "관련 채용 절차1)에 따라 진행되었다.",
        "",
        // 짧은 각주 정의 — "...참조"로 끝나 문장종결(다/임/함/음/됨) 없이 끝남.
        "1) ○○○처-682(2016.2.24.)「자산구조조정 전문인력 채용계획(안)」 참조 등 사실에 대해, " +
          "해당실무 담당자는 면접관들이 면접을 유선상으로 실시하는 관계로 면접내역을 남기지 " +
          "않았다고 소명하고 있으나 감사대상기간 중의 공개채용 사례2) 면접내역을 구비한 " +
          "사례가 확인된 바 향후 철저한 관리가 필요한 사항으로 판단된다. 또한 공사 별정직 " +
          "관리요령 제10조에 의하면 구비서류를 규정하고 있다고 명시하고 있다. 그러함에도 " +
          "구비서류를 검토한 결과 규정을 위반한 사실이 인정된다. 인사운영 원칙에 따르면 " +
          "인사 운영 전반을 공정하고 투명하게 운영하여야 한다고 명시하고 있다. 또한 최근 " +
          "공공기관의 채용비리 감사결과 공개3) 등 공공기관의 채용 비리에 대한 신뢰도에도 " +
          "영향을 미칠 수 있다.",
        "",
        "조치할 사항",
        "",
        "사장은 관련자에게 주의 조치 하시기 바랍니다.",
        "",
        "2) 2013년 6월 이후 공개채용",
      ].join("\n");
      const blocks = splitIntoBlocks(text);

      // "1) ..." 각주 정의 + 뒤이은 본문 전체가 body로 재분류돼야 함(예전엔
      // footnote로 새어서 작은 글씨로 렌더링됐음).
      const longBlock = blocks.find((b) => b.text.startsWith("1) ○○○처-682"));
      expect(longBlock.type).toBe("body");
      expect(longBlock.text).toContain("판단된다");
      expect(longBlock.text).toContain("명시하고 있다"); // 뒤이은 문장까지 같은 블록에 포함

      // "조치할 사항"은 여전히 정상 heading으로 분리됨(각주 흡수에 안 걸림).
      expect(blocks.find((b) => b.text === "조치할 사항")?.type).toBe("heading");

      // 뒤이은 진짜 짧은 각주 2)는 heading 이후 새로 시작되므로 여전히
      // footnote로 정상 분류됨(이번 수정이 진짜 각주까지 없애면 안 됨).
      const shortFootnote = blocks.find((b) => b.text.startsWith("2) 2013년"));
      expect(shortFootnote.type).toBe("footnote");
    },
  );

  it('"[표 1]" 캡션 뒤 셀 구분 없는 텍스트는 table 블록(줄바꿈 보존)으로 접힘', () => {
    const text = ["[표 1] 출장 내역", "일자 출장자 목적지", "2024.1.1 홍길동 세종"].join("\n");
    const blocks = splitIntoBlocks(text);
    expect(blocks[0]).toMatchObject({ type: "heading", text: "[표 1] 출장 내역" });
    expect(blocks[1].type).toBe("table");
    expect(blocks[1].text).toBe("일자 출장자 목적지\n2024.1.1 홍길동 세종");
  });

  it("자료/출처 표기는 caption으로 작게 분리됨", () => {
    const blocks = splitIntoBlocks("본문 문단입니다.\n자료: ○○ 제출자료 재구성");
    expect(blocks[0].type).toBe("body");
    expect(blocks[1]).toMatchObject({ type: "caption", text: "자료: ○○ 제출자료 재구성" });
  });

  it('"붙임 : ..." 뒤에 이어지는 짧은 번호 항목들은 각자 heading으로 승격되지 않고 하나의 body로 흡수됨', () => {
    // ATTACHMENT_LABEL_RE 주석 참고 — "붙임"을 문단 경계 라벨로 인정하고, 그 뒤
    // 이어지는 짧은 번호 항목("2. 확인서" 등)은 새 소제목이 아니라 첨부 목록의
    // 계속되는 항목이므로 inAttachmentList로 heading 승격을 막아야 함.
    const text = "붙임 : 1. 문답서\n2. 확인서\n3. 진술서";
    const blocks = splitIntoBlocks(text);
    expect(blocks[0]).toMatchObject({ type: "heading", text: "붙임", isTitle: false });
    expect(blocks[1]).toMatchObject({
      type: "body",
      text: "1. 문답서 2. 확인서 3. 진술서",
    });
  });

  it('"N) 법령 「...」 \'인용문...\'"처럼 번호+법령라벨 뒤에 줄바꿈 없이 인용문이 붙으면 라벨/인용문을 분리함', () => {
    // splitLawCitationHeading 주석 참고 — 라벨(번호+법령명+조항)만 heading으로,
    // 뒤이은 실제 인용문은 별도 body로 떼어내야 함(안 그러면 인용문까지 통째로 굵어짐).
    const text =
      "1) 법령 「공직자윤리법」 제3조(청렴의무) '공직유관단체인 우리 공사는 청렴하게 직무를 수행하여야 한다.'";
    const blocks = splitIntoBlocks(text);
    expect(blocks[0]).toMatchObject({
      type: "heading",
      text: "1) 법령 「공직자윤리법」 제3조(청렴의무)",
    });
    expect(blocks[1]).toMatchObject({
      type: "body",
      text: "'공직유관단체인 우리 공사는 청렴하게 직무를 수행하여야 한다.'",
    });
  });

  it("ⅰ)/ⅱ)/ⅲ)... 로마숫자 소제목을 heading으로 분류함", () => {
    // ROMAN_NUMERAL_HEADING_RE 주석 참고 — 가/나/다·1./2./3.과 같은 급의 짧은
    // 소제목으로 다뤄야 함(예전엔 어떤 헤딩 패턴에도 안 걸려 그냥 body였음).
    const text = "나. 관계 법령 및 판단 기준\nⅰ) 내규 준수 관련\nⅱ) 금품 수수 관련";
    const blocks = splitIntoBlocks(text);
    expect(blocks.map((b) => ({ type: b.type, text: b.text }))).toEqual([
      { type: "heading", text: "나. 관계 법령 및 판단 기준" },
      { type: "heading", text: "ⅰ) 내규 준수 관련" },
      { type: "heading", text: "ⅱ) 금품 수수 관련" },
    ]);
  });

  it("연속된 각주 참조(1)/2)/3))는 각각 독립된 footnote 블록으로 정확히 순서대로 인식됨", () => {
    const text = [
      "관련 규정에 따라 권한을 위임1)하였고, 정산 업무를 위탁2)하였으며, 이후 절차를 간소화3)하였다.",
      "",
      "1) 총무처장에게 예산 집행 권한을 위임함",
      "2) 회계법인에 정산 업무를 위탁함",
      "3) 내부 규정 개정으로 절차를 간소화함",
    ].join("\n");
    const blocks = splitIntoBlocks(text);
    expect(blocks.map((b) => b.type)).toEqual(["body", "footnote", "footnote", "footnote"]);
    expect(blocks[1].text).toBe("1) 총무처장에게 예산 집행 권한을 위임함");
    expect(blocks[2].text).toBe("2) 회계법인에 정산 업무를 위탁함");
    expect(blocks[3].text).toBe("3) 내부 규정 개정으로 절차를 간소화함");
  });

  it("문서 맨 앞 표지 블록(뱃지/제목/날짜/기관명이 줄바꿈으로만 나열)은 cover 타입으로 줄바꿈을 보존함", () => {
    // looksLikeCoverBlock 주석 참고 — 마지막 줄이 문장종결로 안 끝나야 표지로 인식.
    const text = "복무감사\n2020. 10월 복무감사결과 보고서\n2020. 10.\n한국철도공사\n감사실";
    const blocks = splitIntoBlocks(text);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("cover");
    expect(blocks[0].text).toBe(text);
  });
});
