"""One vocabulary for catalog query cleanup from model and price routing."""

import re


# a: automatic price search; m: model-proposed query; t: model cleanup trigger;
# p: whole phrase removed from model-proposed queries before token filtering.
QUERY_TERMS = {
    "có loại nào": "a", "có mẫu nào": "a", "những loại nào": "a",
    "loại nào": "a", "mẫu nào": "a", "máy nào": "a", "sản phẩm nào": "a",
    "đang khuyến mãi": "a", "khuyến mãi": "a", "đang giảm giá": "a",
    "giảm giá": "a", "ưu đãi": "a", "sale": "a", "giá bao nhiêu": "at",
    "bao nhiêu tiền": "a", "bao nhiêu": "at", "mấy tiền": "a",
    "giảm": "a", "giá": "am", "các": "a", "những": "a",
    "cho em hỏi": "a", "cho anh hỏi": "a", "hiện tại": "a",
    "không em": "a", "em ơi": "a", "anh ơi": "a", "ạ": "am", "nhé": "am",
    "của": "am", "bao": "m", "nhiêu": "m", "tiền": "m", "vậy": "m",
    "shop": "m", "ơi": "m", "cho": "m", "mình": "m", "tôi": "m",
    "hỏi": "m", "em": "m", "anh": "m", "chị": "m", "muốn": "m",
    "biết": "m", "được": "m", "là": "m", "sao": "m", "bạn": "m",
    "giá của": "t", "shop ơi": "t", "cho mình hỏi": "t",
    "còn hàng không": "p",
    "xin báo": "a", "chi phí": "at", "giúp mình": "a",
    "xin": "m", "báo": "m", "chi": "m", "phí": "m", "giúp": "m",
}

# A product phrase followed by a purpose clause is a common model output. The
# catalog matches every query word literally, so keep the product phrase only.
_PURPOSE_CLAUSE = re.compile(r"(?i)\b(?:dành\s+)?cho\b")


def clean_catalog_query(query: str, *, generated: bool = False) -> str:
    """Keep product terms while preserving each caller's existing cleanup timing."""
    if generated:
        text = query
        for term, flags in sorted(QUERY_TERMS.items(), key=lambda entry: len(entry[0]), reverse=True):
            if "a" in flags:
                text = re.sub(rf"(?i)\b{re.escape(term)}\b", " ", text)
        return " ".join(re.findall(r"[\w-]+", text, flags=re.UNICODE)).strip()
    purpose = _PURPOSE_CLAUSE.search(query)
    if purpose and len(query[:purpose.start()].split()) >= 2:
        query = query[:purpose.start()]
    query = " ".join(query.split())
    if not any("t" in flags and re.search(rf"(?i)\b{re.escape(term)}\b", query)
               for term, flags in QUERY_TERMS.items()):
        return query
    text = query
    for term, flags in QUERY_TERMS.items():
        if "p" in flags:
            text = re.sub(rf"(?i)\b{re.escape(term)}\b", " ", text)
    words = re.findall(r"[\w-]+", text, flags=re.UNICODE)
    keywords = [word for word in words if "m" not in QUERY_TERMS.get(word.lower(), "")]
    return " ".join(keywords) if keywords else query
