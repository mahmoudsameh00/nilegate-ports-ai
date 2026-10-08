"""Injection screening of uploaded text (RAG plan Phase 8 §c; the project rules rule 5: retrieved text is data, never
instructions).

Layer 3 of the upload screening: the *visible* text of an upload, after normalization, against patterns of known
prompt-injection shapes in English, Modern Standard Arabic and Egyptian Arabic. Layers 1 (active PDF / DOCX content)
and 2 (hidden text) are in `upload_reader`; layer 4 (handling: every session result is labelled
`trust="untrusted_upload"`) is in `session_store` / `retrieval`.

Honest limit: patterns catch known shapes, not a cleverly paraphrased instruction. The guarantee does not rest on this
module: upload text is always handed on as labelled, untrusted data.
"""
import re
import unicodedata
from dataclasses import dataclass

from pipelines.lib.common import redact

# Invisible / direction-changing characters: zero-width (incl. joiners), soft hyphen, word joiner and invisible
# operators, BOM, bidi embeddings / overrides / isolates, and the Unicode "tag" block (used to smuggle ASCII text that
# no reader sees). They are removed before matching; above CONTROL_LIMIT in one document the upload is refused.
CONTROL_CHARS = re.compile("[­​-‏  ‪-‮⁠-⁤⁦-⁩﻿"
                           "\U000e0000-\U000e007f]")
CONTROL_LIMIT = 3
_AR_DIACRITICS = re.compile("[ً-ْٰـ]")  # harakat, superscript alef, tatweel
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def strip_controls(text: str) -> tuple[str, int]:
    """(text without invisible / bidi / tag characters, how many were removed)."""
    found = CONTROL_CHARS.findall(text)
    return CONTROL_CHARS.sub("", text), len(found)


def match_form(text: str) -> str:
    """The form patterns are matched against: NFKC (folds full-width letters, ligatures and Arabic presentation forms
    back to plain letters), controls removed, lower case, Arabic letter variants folded, diacritics / tatweel removed,
    spaces collapsed (line breaks kept: a role marker counts only at the start of a line). Never stored: chunks keep
    the NFKC text."""
    t = unicodedata.normalize("NFKC", text)
    t, _ = strip_controls(t)
    t = _AR_DIACRITICS.sub("", t.lower()).translate(_AR_FOLD)
    return re.sub(r"[ \t\r\f\v]+", " ", t)


# (name, pattern) on match_form(text). English verbs need a word boundary on both sides ("ignored" in a USCG report is
# narrative, "ignore" with "previous instructions" is an order).
_W = r"[^.!?\n]{0,40}"  # a short gap inside one sentence
PATTERNS: list[tuple[str, re.Pattern]] = [(n, re.compile(p)) for n, p in [
    # --- English ---------------------------------------------------------------------------------------------------
    ("override_en", r"\b(ignore|disregard|forget|override|bypass|skip)\b" + _W +
                    r"\b(previous|prior|above|earlier|preceding|all|any|your|these|those|the)\b" + _W +
                    r"\b(instructions?|prompts?|rules|directions|guidelines|guardrails|constraints|messages?)\b"),
    ("new_role_en", r"\byou are now (an? |the |in )?(ai|assistant|chatbot|model|system|dan|unrestricted|jailbroken|"
                    r"developer mode|free)\b|\bfrom now on,? you (are|will|must)\b|\bpretend (to be|you are)\b"
                    r"|\bnew instructions?\s*:"
                    r"|\bact as (an?|the|my)\b" + _W + r"\b(assistant|ai|system|admin|administrator|developer|dan)\b"),
    ("prompt_marker", r"<\|?\s*(im_start|im_end|system|endoftext|assistant)\s*\|?>|\[/?(inst|sys)\]|<</?sys>>"
                      r"|(^|\n) ?(system|assistant|developer|user) ?: |#{2,} ?(system|instructions?)\b"),
    ("prompt_ref_en", r"\b(system|hidden|initial|original|developer) (prompt|message|instructions)\b"
                      r"|\bjailbreak|\bdo anything now\b|\bdeveloper mode\b"),
    ("reveal_en", r"\b(reveal|print|show|output|repeat|leak|dump|tell me)\b" + _W +
                  r"\b(system prompt|your instructions|api[ _-]?keys?|passwords?|credentials|secrets?|tokens?)\b"),
    ("exfiltrate_en", r"\b(send|post|upload|forward|e-?mail|exfiltrate|transmit)\b[^.!?\n]{0,60}(https?://|www\.)"),
    ("tool_call", r"\"(tool|function)_?(call|name)s?\"\s*:|\b(call|invoke|execute|trigger)\b" + _W +
                  r"\b(tool|function|search_documents|query_records|query_operations|compute_toll|web_search)\b"),
    ("markdown_beacon", r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*\)"),
    # --- Arabic (MSA + Egyptian), on the folded form (أ/إ/آ -> ا, ى -> ي, ة -> ه) ------------------------------------
    ("override_ar", r"(تجاهل|تجاهلي|تتجاهل|انس|انسي|انسا|اهمل|اهملي|تخط|تخطي|تجاوز|الغ|الغي|سيبك من|سيبك|طنش|"
                    r"متسمعش|ماتسمعش|متاخدش ب|لا تتبع|لا تلتزم ب)" + _W +
                    r"(التعليمات|تعليمات|الاوامر|اوامر|القواعد|التوجيهات|الارشادات|القيود|كل اللي فات|"
                    r"اللي قبل كده|الكلام اللي فوق|الكلام اللي فات|ما سبق|السابق)"),
    ("new_role_ar", r"(انت|انتي|انتا) (الان|دلوقتي|من دلوقتي|من الان)\b|من (الان|دلوقتي) (انت|هتبقي|هتكون|ستكون)"
                    r"|(تقمص|العب|خد|اعمل) دور|اتصرف (كانك|كانك|زي) |تعليمات جديده\s*:"),
    ("reveal_ar", r"(اكشف|اظهر|اطبع|قول|قولي|قوللي|ابعت|ورني|وريني|اعرض|سرب)" + _W +
                  r"(التعليمات|البرومبت|البرمبت|موجه النظام|رساله النظام|كلمه السر|كلمات السر|كلمه المرور|"
                  r"الباسورد|الباسوورد|المفاتيح|مفتاح|التوكن)"),
    ("prompt_ref_ar", r"(موجه|برومبت|برمبت|رساله|تعليمات) (النظام|السيستم)"),
    ("exfiltrate_ar", r"(ابعت|ارسل|حول|انشر|سرب|ارفع)[^.!؟?\n]{0,60}(https?://|www\.)"),
]]
BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")
# The strongest phrases again on the form without any whitespace: a PDF turns a zero-width character into a space at
# extraction ("Ig nore pre vious instructions"), which the word-level patterns above no longer see.
COMPACT = [(n, re.compile(p)) for n, p in [
    ("override_compact", r"(ignore|disregard|forget|bypass)(all|any|the|your)*(previous|prior|above|earlier)"
                         r"(instructions?|prompts?|rules)"),
    ("prompt_ref_compact", r"systemprompt|developermode|doanythingnow"),
    ("override_ar_compact", r"(تجاهل|انس|اهمل|سيبكمن)(كل|جميع)?(التعليمات|الاوامر)"),
]]


@dataclass
class Hit:
    pattern: str
    excerpt: str  # <= 80 characters around the match, secrets redacted


def screen_text(text: str) -> list[Hit]:
    """Every injection-pattern match in `text` (empty list = clean)."""
    form = match_form(text)
    hits = []
    for name, pat in PATTERNS:
        for m in pat.finditer(form):
            a, b = max(0, m.start() - 20), min(len(form), m.end() + 20)
            hits.append(Hit(name, redact(form[a:b])[:80]))
    if not hits:
        compact = re.sub(r"\s+", "", form)
        for name, pat in COMPACT:
            m = pat.search(compact)
            if m:
                hits.append(Hit(name, redact(m.group(0))[:80]))
    raw, _ = strip_controls(unicodedata.normalize("NFKC", text))
    for m in BASE64_BLOB.finditer(raw):
        hits.append(Hit("base64_blob", m.group(0)[:40] + "…"))
    return hits
