import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple, Optional
import math
import json

@dataclass
class NumberFinding:
    text: str                 # exact text matched
    kind: str                 # 'fraction' | 'scientific' | 'decimal' | 'integer'
    value: Optional[float]    # parsed numeric value (None if not applicable)
    exact: bool               # whether treated as exact (relative accuracy = 0)
    decimals: Optional[int]   # decimal places in mantissa (for sci) or number (for decimal)
    abs_tol: Optional[float]  # absolute tolerance if approximate
    rel_acc: Optional[float]  # relative accuracy if approximate
    span: Tuple[int, int]     # (start, end) in the original string
    note: str                 # short reason/decision

def _occupied(spans: List[Tuple[int,int]], start: int, end: int) -> bool:
    for s,e in spans:
        if not (end <= s or start >= e):
            return True
    return False

def _add_span(spans: List[Tuple[int,int]], start: int, end: int):
    spans.append((start,end))

def _strip_braces(s: str) -> str:
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s[1:-1].strip()
    return s

def _sig_decimals_from_mantissa(m: str) -> int:
    # count digits after decimal point in the mantissa literal
    if "." in m:
        return len(m.split(".", 1)[1])
    return 0

def _is_exact_decimal(num_text: str) -> bool:
    """
    Exact if:
      - exactly one decimal place and (abs(value) < 1) OR (fractional digit in {0,5})
      - exactly 0.25 or 0.75 (with or without leading 0, sign allowed)
    """
    s = num_text
    # match .d or d.d
    m1 = re.fullmatch(r"[+-]?(?:\d+\.(\d)|\.(\d))", s)
    if m1:
        frac_digit = (m1.group(1) or m1.group(2))
        try:
            v = float(s)
        except ValueError:
            return False
        if abs(v) < 1:
            return True
        return frac_digit in ("0", "5")

    # exactly 0.25 / .25 or 0.75 / .75
    if re.fullmatch(r"[+-]?(?:0?\.25|0?\.75)", s):
        return True

    return False


def analyze_formula(latex: str) -> Dict[str, Any]:
    findings: List[NumberFinding] = []
    taken: List[Tuple[int,int]] = []

    # 1) Fractions: \frac{p}{q}
    frac_re = re.compile(r"""\\frac\s*\{\s*([+-]?\d+)\s*\}\s*\{\s*([+-]?\d+)\s*\}""")
    for m in frac_re.finditer(latex):
        if _occupied(taken, m.start(), m.end()):
            continue
        p, q = m.group(1), m.group(2)
        try:
            val = int(p) / int(q)
        except ZeroDivisionError:
            val = None
        findings.append(NumberFinding(
            text=m.group(0),
            kind="fraction",
            value=val,
            exact=True,
            decimals=None,
            abs_tol=None,
            rel_acc=0.0,
            span=(m.start(), m.end()),
            note="Explicit rational fraction"
        ))
        _add_span(taken, m.start(), m.end())

    # 2) Scientific notation: a * 10^{k} with \times or \cdot, and 'e' form
    sci_re1 = re.compile(
        r"""([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?:\\times|\\cdot|\*)\s*10\^(\{[-+]?\d+\}|[-+]?\d+)"""
    )
    for m in sci_re1.finditer(latex):
        if _occupied(taken, m.start(), m.end()):
            continue
        mant, exp = m.group(1), _strip_braces(m.group(2))
        try:
            mant_v = float(mant)
            exp_v = int(exp)
            val = mant_v * (10 ** exp_v)
        except Exception:
            mant_v = None
            exp_v = None
            val = None
        d = _sig_decimals_from_mantissa(mant)
        abs_tol = (5 * (10 ** -d)) * (10 ** (exp_v if exp_v is not None else 0))
        rel_acc = None
        exact = False
        note = "Scientific notation treated as approximate"
        if val is not None and val != 0:
            rel_acc = abs_tol / abs(val)
        findings.append(NumberFinding(
            text=m.group(0),
            kind="scientific",
            value=val,
            exact=exact,
            decimals=d,
            abs_tol=abs_tol,
            rel_acc=rel_acc,
            span=(m.start(), m.end()),
            note=note
        ))
        _add_span(taken, m.start(), m.end())

    sci_re2 = re.compile(r"""([+-]?(?:\d+(?:\.\d+)?|\.\d+))[eE]([+-]?\d+)""")
    for m in sci_re2.finditer(latex):
        if _occupied(taken, m.start(), m.end()):
            continue
        mant, exp = m.group(1), m.group(2)
        try:
            mant_v = float(mant)
            exp_v = int(exp)
            val = mant_v * (10 ** exp_v)
        except Exception:
            mant_v = None
            exp_v = None
            val = None
        d = _sig_decimals_from_mantissa(mant)
        abs_tol = (5 * (10 ** -d)) * (10 ** (exp_v if exp_v is not None else 0))
        rel_acc = None
        exact = False
        note = "Scientific notation treated as approximate"
        if val is not None and val != 0:
            rel_acc = abs_tol / abs(val)
        findings.append(NumberFinding(
            text=m.group(0),
            kind="scientific",
            value=val,
            exact=exact,
            decimals=d,
            abs_tol=abs_tol,
            rel_acc=rel_acc,
            span=(m.start(), m.end()),
            note=note
        ))
        _add_span(taken, m.start(), m.end())

    # 3) Decimals (not captured above)
    dec_re = re.compile(r"(?<!\w)([+-]?(?:\d+\.\d+|\.\d+))")
    for m in dec_re.finditer(latex):
        if _occupied(taken, m.start(), m.end()):
            continue
        s = m.group(1)
        v = float(s)
        if _is_exact_decimal(s):
            findings.append(NumberFinding(
                text=s, kind="decimal", value=v, exact=True,
                decimals=len(s.split(".",1)[1]), abs_tol=None, rel_acc=0.0,
                span=(m.start(), m.end()),
                note="Exact decimal per rule (one-place <1, .0/.5, or 0.25/0.75)"
            ))
        else:
            d = len(s.split(".",1)[1])
            abs_tol = 5 * (10 ** -d)
            rel_acc = abs_tol / abs(v) if v != 0 else None
            findings.append(NumberFinding(
                text=s, kind="decimal", value=v, exact=False,
                decimals=d, abs_tol=abs_tol, rel_acc=rel_acc,
                span=(m.start(), m.end()),
                note="Decimal treated as approximate"
            ))
        _add_span(taken, m.start(), m.end())


    # 4) Bare integers (we treat as exact; optional to collect)
    # If you want them reported, uncomment below.
    # int_re = re.compile(r"(?<![\w.])([+-]?\d+)(?![\w.])")
    # for m in int_re.finditer(latex):
    #     if _occupied(taken, m.start(), m.end()):
    #         continue
    #     v = int(m.group(1))
    #     findings.append(NumberFinding(
    #         text=m.group(1),
    #         kind="integer",
    #         value=float(v),
    #         exact=True,
    #         decimals=None,
    #         abs_tol=None,
    #         rel_acc=0.0,
    #         span=(m.start(), m.end()),
    #         note="Integer treated as exact"
    #     ))
    #     _add_span(taken, m.start(), m.end())

    # Compute overall relative accuracy = max over approximate literals; 0 if none
    rels = [f.rel_acc for f in findings if (f.rel_acc is not None)]
    overall_rel = max(rels) if rels else 0.0

    return overall_rel
