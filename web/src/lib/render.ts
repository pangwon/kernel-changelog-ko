import { marked } from "marked";

const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** 백틱 코드 밖의 <, >, &를 이스케이프한다. 생성 텍스트의 `< 0` 같은 표현이 HTML로 해석되지 않게. */
function escapeOutsideCode(src: string): string {
  return src
    .split(/(`[^`\n]*`)/)
    .map((part) => (part.startsWith("`") && part.endsWith("`") && part.length > 1 ? part : escapeHtml(part)))
    .join("");
}

/** 해설(### 배경 / ### 변경 내용 / ### 영향) 마크다운. 제목은 h3 대신 h4로 낮춘다. */
export function markdown(src: string | null | undefined): string {
  if (!src) return "";
  const html = marked.parse(escapeOutsideCode(src), { async: false, gfm: true }) as string;
  return html.replace(/<(\/?)h3>/g, "<$1h4>");
}

/** 요약 한 단락 (인라인 코드만). */
export function inline(src: string | null | undefined): string {
  if (!src) return "";
  return marked.parseInline(escapeOutsideCode(src), { async: false }) as string;
}

/** unified diff를 줄 단위로 색을 입힌 HTML로. */
export function diffHtml(patch: string): string {
  return patch
    .replace(/\n$/, "")
    .split("\n")
    .map((line) => {
      let cls = "";
      if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("+++") || line.startsWith("---")) cls = "meta";
      else if (line.startsWith("@@")) cls = "hunk";
      else if (line.startsWith("+")) cls = "add";
      else if (line.startsWith("-")) cls = "del";
      return `<span class="dl ${cls}">${escapeHtml(line) || " "}</span>`;
    })
    .join("\n");
}

export const gitWeb = (sha: string) =>
  `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=${sha}`;
