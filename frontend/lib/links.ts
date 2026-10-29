// Ссылки в тексте задач и комментариев. Кликабельными становятся:
//   • голые адреса https://… и http://… (точка, запятая и непарная «)» в конце
//     в адрес не входят, «&» и «?» — входят);
//   • пути сайта проекта «/lk/turnkey/?admin=1» → https://<site_url>/lk/turnkey/?admin=1
//     (site_url — в настройках проекта; правила те же, что в backend/app/core/links.py);
//   • ключи задач «SSK-262» → /t/ssk-262 (только коды существующих проектов);
//   • номера решений «P-030», «SSK:P-030», «_global:P-022» → /d/… (decisionRefs.ts).
// Код в обратных кавычках и готовые Markdown-ссылки не трогаем.

import { REF_RE, hrefFor } from "./decisionRefs";

export interface LinkContext {
  projectCode?: string;
  siteUrl?: string | null;
  // коды проектов workspace: «UC-001» или «ISO-9001» без проекта остаются текстом
  taskCodes?: ReadonlySet<string>;
}

export interface LinkPart {
  text: string;
  href?: string;
  external?: boolean;
}

// Пути серверов и Mac, которые в задачах пишут постоянно: это файлы, не страницы.
const FS_ROOTS = new Set([
  "srv", "etc", "home", "tmp", "var", "usr", "opt", "root", "mnt", "proc", "dev",
  "bin", "sbin", "lib", "lib64", "run", "sys", "boot", "media", "snap", "users",
  "private", "volumes", "library", "applications", "system", "archive", "backup",
  "backups", "nix",
]);

const FILE_EXTS = new Set([
  "py", "sh", "ts", "tsx", "jsx", "md", "yaml", "yml", "sql", "log", "conf", "env",
  "toml", "ini", "service", "lock", "pyc", "gz", "zst", "tar", "csv", "tsv",
]);

const Q = "[^\\s<>\"'`«»*\\[\\]{}|\\\\^]*";
const URL_SRC = "https?:\\/\\/[^\\s<>\"'`«»]+";
const PATH_SRC =
  "(?<![\\w/.\\-~:@%&=+])\\/[A-Za-z0-9][A-Za-z0-9._~%\\-]*(?:\\/[A-Za-z0-9._~%\\-]*)*" +
  `(?:\\?${Q})?(?:#${Q})?`;
const KEY_SRC = "(?<![\\w/.\\-#])[A-Z][A-Z0-9]{1,19}-\\d+(?![\\w-])";
const PLAIN_SRC = `(?<url>${URL_SRC})|(?<path>${PATH_SRC})|(?<dec>${REF_RE.source})|(?<key>${KEY_SRC})`;
const MD_SRC = `(?<md>!?\\[[^\\]\\n]*\\]\\([^)\\n]*\\))|(?<auto><https?:\\/\\/[^>\\s]+>)|${PLAIN_SRC}`;
const DEC_PARTS = /^(?:([A-Za-z_]\w*):)?([A-Z])-(\d{3})$/;
const CODE_SPLIT = /(```[\s\S]*?```|`[^`\n]*`)/g;

// Срезать хвостовую пунктуацию и непарные закрывающие скобки.
export function trimTrailing(token: string): string {
  while (token) {
    const last = token[token.length - 1];
    if (".,;:!?".includes(last)) token = token.slice(0, -1);
    else if (last === ")" && count(token, ")") > count(token, "(")) token = token.slice(0, -1);
    else break;
  }
  return token;
}

function count(s: string, ch: string): number {
  return s.split(ch).length - 1;
}

// Путь страницы сайта, а не файл и не slash-команда: второй сегмент, «/» в конце,
// «?» или «#»; первый сегмент — не корень файловой системы.
export function isSitePath(path: string): boolean {
  const bare = path.split(/[?#]/, 1)[0];
  const segments = bare.split("/").slice(1);
  if (!segments.length || FS_ROOTS.has(segments[0].toLowerCase())) return false;
  const last = segments[segments.length - 1];
  const dot = last.lastIndexOf(".");
  if (dot >= 0 && FILE_EXTS.has(last.slice(dot + 1).toLowerCase())) return false;
  return segments.length >= 2 || bare !== path;
}

interface Token {
  raw: string; // весь совпавший кусок
  text: string; // видимая часть ссылки (без хвостовой пунктуации)
  href?: string;
  external?: boolean;
  keep?: boolean; // готовая ссылка/адрес: в Markdown оставить как есть
}

function classify(m: RegExpMatchArray, ctx: LinkContext): Token {
  const g = m.groups ?? {};
  const raw = m[0];
  if (g.md || g.auto) return { raw, text: raw, keep: true };
  if (g.url) {
    const text = trimTrailing(raw);
    return { raw, text, href: text, external: true, keep: true };
  }
  if (g.path) {
    const text = trimTrailing(raw);
    const site = ctx.siteUrl?.replace(/\/+$/, "");
    if (site && isSitePath(text)) return { raw, text, href: site + text, external: true };
    return { raw, text: raw };
  }
  if (g.dec) {
    const p = DEC_PARTS.exec(raw);
    const href = p ? hrefFor(p[1], p[2], p[3], ctx.projectCode) : undefined;
    return { raw, text: raw, href };
  }
  const code = raw.slice(0, raw.lastIndexOf("-"));
  if (code === ctx.projectCode || ctx.taskCodes?.has(code)) {
    return { raw, text: raw, href: `/t/${raw.toLowerCase()}` };
  }
  return { raw, text: raw };
}

// Простой текст (комментарии) → куски: ссылки и всё остальное.
export function splitLinks(text: string, ctx: LinkContext = {}): LinkPart[] {
  const parts: LinkPart[] = [];
  let last = 0;
  const push = (s: string) => {
    if (!s) return;
    const prev = parts[parts.length - 1];
    if (prev && !prev.href) prev.text += s;
    else parts.push({ text: s });
  };
  for (const m of text.matchAll(new RegExp(PLAIN_SRC, "g"))) {
    const tok = classify(m, ctx);
    if (!tok.href) continue;
    const at = m.index ?? 0;
    push(text.slice(last, at));
    parts.push({ text: tok.text, href: tok.href, external: tok.external });
    last = at + tok.text.length;
  }
  push(text.slice(last));
  return parts;
}

function escapeLabel(s: string): string {
  return s.replace(/([\\`*_[\]<>])/g, "\\$1");
}

// Markdown (описание задачи): пути, ключи и номера решений → [текст](<адрес>).
// Голые https://… оставляем remark-gfm — он делает их ссылками сам.
export function linkifyMarkdown(text: string, ctx: LinkContext = {}): string {
  return text
    .split(CODE_SPLIT)
    .map((chunk) =>
      chunk.startsWith("`")
        ? chunk
        : chunk.replace(new RegExp(MD_SRC, "g"), (...args) => {
            const groups = args[args.length - 1] as Record<string, string | undefined>;
            const m = Object.assign([args[0]] as unknown as RegExpMatchArray, { groups });
            const tok = classify(m, ctx);
            if (tok.keep || !tok.href) return tok.raw;
            return `[${escapeLabel(tok.text)}](<${tok.href}>)${tok.raw.slice(tok.text.length)}`;
          })
    )
    .join("");
}
