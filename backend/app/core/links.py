"""Ссылки в тексте задач и комментариев.

Путь сайта проекта (``/lk/turnkey/?admin=1&branch=63680``) при сохранении
становится абсолютным URL на домен из ``projects.site_url``: тогда ссылка
кликабельна и в базе, и в уведомлениях, и в CLI. Тот же разбор на фронте —
``frontend/lib/links.ts``; правила держать одинаковыми.

Что считается путём сайта: начинается с «/» после пробела, начала строки или
открывающей скобки/кавычки; первый сегмент не корень файловой системы сервера
(``/srv``, ``/etc``, ``/home``…); есть второй сегмент, «/» в конце, «?» или «#»
(одиночное ``/poisk`` похоже на slash-команду и не трогается). Код в обратных
кавычках и готовые URL не трогаем.
"""

import re

# Пути серверов и Mac, которые в задачах пишут постоянно: это файлы, не страницы.
FS_ROOTS = frozenset({
    "srv", "etc", "home", "tmp", "var", "usr", "opt", "root", "mnt", "proc", "dev",
    "bin", "sbin", "lib", "lib64", "run", "sys", "boot", "media", "snap", "users",
    "private", "volumes", "library", "applications", "system", "archive", "backup",
    "backups", "nix",
})

# Расширения исходников и конфигов: «/backend/app/x.py» — файл репозитория.
FILE_EXTS = frozenset({
    "py", "sh", "ts", "tsx", "jsx", "md", "yaml", "yml", "sql", "log", "conf", "env",
    "toml", "ini", "service", "lock", "pyc", "gz", "zst", "tar", "csv", "tsv",
})

_CODE_SPLIT_RE = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")
_QUERY = r"[^\s<>\"'`«»*\[\]{}|\\^]*"
_TOKEN_RE = re.compile(
    r"(?P<url>https?://[^\s<>\"'`«»]+)"
    r"|(?P<path>(?<![\w/.\-~:@%&=+])/[A-Za-z0-9][A-Za-z0-9._~%\-]*"
    r"(?:/[A-Za-z0-9._~%\-]*)*(?:\?" + _QUERY + r")?(?:#" + _QUERY + r")?)"
)
_TRAILING = ".,;:!?"


def trim_trailing(token: str) -> str:
    """Срезать хвостовую пунктуацию и непарные закрывающие скобки."""
    while token:
        last = token[-1]
        if last in _TRAILING:
            token = token[:-1]
        elif last == ")" and token.count(")") > token.count("("):
            token = token[:-1]
        else:
            break
    return token


def is_site_path(path: str) -> bool:
    bare = re.split(r"[?#]", path, maxsplit=1)[0]
    segments = bare.split("/")[1:]
    if not segments or segments[0].lower() in FS_ROOTS:
        return False
    last = segments[-1]
    if "." in last and last.rsplit(".", 1)[1].lower() in FILE_EXTS:
        return False
    return len(segments) >= 2 or bare != path


def normalize_site_url(value: str | None) -> str | None:
    """«skolkoskolko.ru/» → «https://skolkoskolko.ru»; пусто → None."""
    if value is None:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(?::\d+)?", value):
        raise ValueError("site_url must be a bare origin like https://example.ru")
    return value.lower()


def absolutize_site_paths(text: str | None, site_url: str | None) -> str | None:
    """Заменить пути сайта на абсолютные URL; без site_url текст не меняется."""
    if not text or not site_url:
        return text

    def repl(m: re.Match[str]) -> str:
        if m.group("url"):
            return m.group(0)
        token = m.group("path")
        path = trim_trailing(token)
        if not is_site_path(path):
            return token
        return site_url + path + token[len(path):]

    return "".join(
        chunk if chunk.startswith("`") else _TOKEN_RE.sub(repl, chunk)
        for chunk in _CODE_SPLIT_RE.split(text)
    )
