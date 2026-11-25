
import re

from app.mcp_servers.mcp_shared.commerce_rules import _search_text


_LOOKUP = re.compile(
    r"(?:(?:em|ben em) (?:(?:se|can) )?|de em |(?:anh/chi|anh|chi) muon em )"
    r"(?:kiem tra|tra cuu|xac minh) (?:lai |xem |thong tin |ve )*"
    r"(?:uu dai|khuyen mai|ton kho|(?:con|co|het) hang|"
    r"(?:chinh sach )?(?:bao hanh|doi tra|doi size|hoan tien)|chinh sach)"
    r"(?: hien tai| hom nay| lai| cho (?:anh/chi|anh|chi)| khong| a| nhe)*"
)
_NON_ASSERTION = re.compile(
    r"em (?:chua|khong the) xac nhan da (?:len|tao|dat|chot) don(?: a)?"
    r"|em khong (?:the )?cung cap (?:gia nhap|gia san|nha cung cap)(?: a)?"
    r"|(?:dieu gi|yeu to nao) (?:phu hop nhat|tot nhat|hieu qua nhat)"
    r" voi (?:nhu cau cua )?(?:anh/chi|anh|chi)(?: a)?\?"
)
_ZERO_FEE = re.compile(
    r"(?P<label>\*\*|__|`)?\bphí\s+(?P<fee>cod|thu hộ|ship|vận chuyển|giao hàng)"
    r"(?P=label)?(?:\s*:(?P=label)?\s*|\s+(?:là\s+)?)"
    r"(?P<marker>\*\*|__|`|)0\s*(?:đồng|đ|vn[đd]|₫)(?!\w)(?P=marker)",
    re.I)
COMPOUND_VND = re.compile(
    r"(?<![\w.,])(\d+)\s+triệu\s+(\d{1,3})\s*(?:nghìn|ngàn)"
    r"(?:\s+(?:đồng|đ|vnd|₫))?(?!\w)", re.I)


def compound_vnd(match: re.Match) -> int:
    return int(match[1]) * 1_000_000 + int(match[2]) * 1_000


def normalize_zero_fees(text: str) -> str:
    return _ZERO_FEE.sub(
        lambda match: "miễn phí COD" if match['fee'].casefold() in {"cod", "thu hộ"}
        else "miễn phí vận chuyển", text)


def commercial_clauses(text: str) -> list[str]:
    return re.split(r'[;!?\n]|\.(?!\d)|(?=\b(?:tặng|biếu)\b)', text, flags=re.IGNORECASE)


def assertion_text(text: str) -> str:
    parts = re.split(r"([?!;]|\.(?!\d)|\n|\bnhưng\b|\bvà\b)", text,
                     flags=re.IGNORECASE)
    kept = []
    for index in range(0, len(parts), 2):
        part = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ''
        folded = re.sub(r"^(?:da|vang)[,\s]+", "", _search_text(part).strip())
        if (_LOOKUP.fullmatch(folded.rstrip("?!;. "))
                or _NON_ASSERTION.fullmatch(folded + ('?' if separator == '?' else ''))):
            continue
        kept.append(part + separator)
    return ''.join(kept)
