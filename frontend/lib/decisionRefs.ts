// Номера решений в тексте задач и комментариев становятся ссылками на /d/.
// Формы: «P-030» (реестр проекта задачи), «SSK:P-030» или «skolkoskolko:P-030»
// (реестр другого проекта), «_global:P-022» (кросс-проектные правила).
// Одна буква области и три цифры, поэтому ключи задач (SSK-203) сюда не попадают.

export const REF_RE = /(?<![\w/.\-\[])(?:([A-Za-z_][\w]*):)?([A-Z])-(\d{3})(?![\w-])/g;

export interface RefPart {
  text: string;
  href?: string;
}

export function hrefFor(prefix: string | undefined, letter: string, num: string, projectCode?: string) {
  const p = prefix ? (prefix.toLowerCase() === "_global" ? "g" : prefix) : projectCode;
  if (!p) return undefined;
  return `/d/${p.toLowerCase()}-${letter.toLowerCase()}-${num}`;
}

// Разбить простой текст на куски: ссылки на решения и всё остальное.
export function splitDecisionRefs(text: string, projectCode?: string): RefPart[] {
  const parts: RefPart[] = [];
  let last = 0;
  for (const m of text.matchAll(REF_RE)) {
    const href = hrefFor(m[1], m[2], m[3], projectCode);
    if (!href) continue;
    const at = m.index ?? 0;
    if (at > last) parts.push({ text: text.slice(last, at) });
    parts.push({ text: m[0], href });
    last = at + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

// Для Markdown: обернуть номера в [P-030](/d/ssk-p-030). Код (`…`) и готовые
// ссылки не трогаем: lookbehind пропускает «[», «/» и «-» перед номером.
export function linkDecisionRefsMarkdown(text: string, projectCode?: string): string {
  return text
    .split(/(`[^`]*`)/g)
    .map((chunk) =>
      chunk.startsWith("`")
        ? chunk
        : chunk.replace(REF_RE, (whole, prefix, letter, num) => {
            const href = hrefFor(prefix, letter, num, projectCode);
            return href ? `[${whole}](${href})` : whole;
          })
    )
    .join("");
}
