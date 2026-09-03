"""Lightweight UI translation support for MediaSort.

All user-visible strings live in JSON translation files under
``mediasort/translations/``, one file per language code (e.g. ``en.json``).
The active language is chosen from the ``language`` setting in
settings.json; the file matching that code is loaded and every UI string
is looked up through :func:`tr` (or :func:`tr_plural` for count-dependent
forms).

Lookup order: active language table -> default language ("en") table ->
the raw key itself, so a missing key in a partial translation degrades
gracefully instead of breaking the UI.
"""
import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = APP_DIR / "translations"

DEFAULT_LANGUAGE = "en"

_translations = {}   # table of the active language
_default = {}        # table of the default language (fallback)
_current_language = DEFAULT_LANGUAGE


def _load_file(language_code):
    """Load one translation file; return {} when it is missing or broken."""
    path = TRANSLATIONS_DIR / f"{language_code}.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_translations(language_code):
    """Select and load the translation table for ``language_code``.

    Returns the code actually in use.  Missing/unknown files keep the
    default-language table as fallback, so the app never shows raw keys.
    """
    global _translations, _default, _current_language
    code = language_code or DEFAULT_LANGUAGE
    _current_language = code
    _translations = _load_file(code)
    _default = _load_file(DEFAULT_LANGUAGE)
    return code


def current_language():
    """Return the language code currently loaded (e.g. "en")."""
    return _current_language


def tr(key, **kwargs):
    """Return the translated string for ``key``, optionally filled with
    ``kwargs`` via str.format (placeholders like ``{count}``)."""
    text = _translations.get(key) or _default.get(key) or key
    if kwargs and isinstance(text, str) and "{" in text:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


# Count -> plural-category rules per language (CLDR-style category names:
# "one", "few", "many", ...).  Languages not listed here use the generic
# "1 -> one, anything else -> other" rule.
_PLURAL_RULES = {
    # Polish: 1 -> one; 2-4 (but not 12-14) -> few; everything else -> many.
    "pl": lambda n: (
        "one" if n == 1 else (
            "few" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
            else "many"
        )
    ),
}


def tr_plural(key, count, **kwargs):
    """Return a plural-aware translation.

    The translation file defines variants as ``key.one`` / ``key.few`` /
    ``key.many`` (etc.).  The category is derived from ``count`` using the
    active language's plural rules.  Falls back to ``key.other``, then to
    any other defined variant, then to :func:`tr`.  A ``{count}``
    placeholder in the selected text is filled automatically unless
    overridden via kwargs.
    """
    rules = _PLURAL_RULES.get(
        _current_language, lambda n: "one" if n == 1 else "other"
    )
    variant = rules(count)
    # Prefer the exact category; "other" is the standard generic fallback;
    # "many" then "few"/"one" act as the next-best generic singular/plural
    # forms when a translation only defines a subset of categories.
    variants = [variant, "other", "many", "few", "one", "zero"]

    text = None
    for table in (_translations, _default):
        for v in variants:
            candidate = table.get(f"{key}.{v}")
            if candidate:
                text = candidate
                break
        if text is not None:
            break

    if text is None:
        return tr(key, **kwargs)
    if "count" not in kwargs:
        kwargs["count"] = count
    if "{" in text:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
