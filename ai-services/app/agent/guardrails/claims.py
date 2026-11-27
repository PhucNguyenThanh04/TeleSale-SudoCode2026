
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
    r"em (?:chua(?: the)?|khong the) xac nhan "
    r"(?:da (?:len|tao|dat|chot) don|don(?: hang)? da (?:duoc )?(?:len|tao|dat|chot))(?: a)?"
    r"|em (?:chua|khong)(?: the| duoc phep)? cung cap "
    r"(?:gia nhap|gia san|(?:ten )?nha cung cap)"
    r"(?: (?:va|hoac|hay) (?:gia nhap|gia san|(?:ten )?nha cung cap))*(?: a)?"
    r"|(?:dieu gi|yeu to nao) (?:phu hop nhat|tot nhat|hieu qua nhat)"
    r" voi (?:nhu cau cua )?(?:anh/chi|anh|chi)(?: a)?\?"
)
_MENTION_CONTEXT = re.compile(
    r'(?:(?:hien tai|hien|van)\s+)?(?:(?:em|toi|ben em|he thong)\s+)?'
    r'(?:(?:cung|van)\s+)?'
    r'(?:chua\s+(?:the\s+)?(?:biet|ro|xac minh|xac nhan|co thong tin|co du lieu)'
    r'|khong\s+(?:the\s+)?(?:biet|ro|xac minh|xac nhan)'
    r'|(?:can|se|dang)\s+(?:kiem tra|tra cuu|xac minh))\b'
    r'|(?:em\s+(?:da\s+)?ghi nhan\s+)?(?:anh/chi|anh|chi|ban|co|chu)\s+'
    r'(?:dang\s+)?(?:can|muon|tim|uu tien|yeu cau|cho em (?:xin|biet))\b'
    r'|em\s+(?:da\s+)?ghi nhan\s+(?:anh/chi|anh|chi|ban)\s+(?:thay|noi|bao|ke)\b'
)
_INDEPENDENT_CLAIM = re.compile(
    r'^(?:hien|hom nay|mau|may|san pham|don|ben em|shop|gia|duoc|tang|bieu|cam ket|em da)\b'
)
_QUESTION_END = re.compile(r'\b(?:khong|chua|nao|gi|bao nhieu|bao lau|the nao)(?:\s+a)?$')
_CAPABILITY = re.compile(r'\b(?:em|toi|ben em)\s+(?:co the|san sang)\b')
_CAPABILITY_ACTION = re.compile(r'\b(?:tim kiem|kiem tra|tra cuu|tu van|cung cap thong tin|giai dap)\b')
_CONCRETE_CAPABILITY_CLAIM = re.compile(
    r'\d|%|\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b|'
    r'\b(?:mien phi|freeship|tang|bieu|trieu|nghin|ngan|phan tram|da|het han|het hieu luc|'
    r'(?:con|co|san|het)\s+hang|co san trong kho|'
    r'hepa|pm\s*2[.,]5|khoa\s+(?:an toan\s+)?tre em|'
    r'tot nhat|phu hop nhat|hieu qua nhat|'
    r'bao hanh\s+tron doi|gia nhap|gia san|nha cung cap|'
    r'(?:deu|luon)\s+(?:giam|co|duoc)|'
    r'(?:mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)\s+dong|'
    r'(?<!uu dai )(?<!khuyen mai )\bhien\s+co\b|dang\s+co|(?:dang|hien)\s+(?:giam|ap dung)|'
    r'(?:khong|chua)\s+(?:co|con|duoc)|'
    r'(?:co|ap dung)\s+(?:khuyen mai|uu dai))\b')
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


def price_assertion_text(text: str) -> str:
    budget_pattern = (
        r'(?:\bngân sách\s+'
        r'(?:(?:tối đa|tầm|khoảng|là|dưới|mức|(?:của\s+)?(?:anh/chị|anh|chị|bạn))\s+)*'
        r'|\b(?:anh/chị|anh|chị|bạn)\s+(?:muốn|định|có thể)\s+chi\s+(?:là\s+)?'
        r'|^\s*(?:với|theo)\s+(?:tầm|mức)\s+giá\s+(?:của\s+)?'
        r'(?:anh/chị|anh|chị|bạn)\s+(?:mong muốn|muốn chi)\s+(?:là\s+)?)'
        r'\d[\d.,]*\s*(?:triệu|tr|nghìn|ngàn|k|đồng|đ|vnd)\b'
    )
    parts = []
    for clause in re.split(r'([.!?;,\n](?!\d))', text):
        stripped = re.sub(budget_pattern, '', clause, flags=re.IGNORECASE)
        commercial = re.search(r'(?i)\b(?:giá|bán|thành tiền|thanh toán|trả thêm)\b|'
                               r'\b(?:không|chưa)\s+(?:có|tìm thấy)\s+(?:mẫu|sản phẩm)\b', stripped)
        parts.append(clause if commercial else stripped)
    return ''.join(parts)


def _context_only(text: str, question: bool) -> bool:
    folded = re.sub(r'^(?:da|vang)(?:\s+(?:anh/chi|anh|chi|ban|co|chu))?[,\s]+',
                    '', _search_text(text).strip())
    parts = re.split(r',\s*(?!\d)|\b(?:va|nhung|nen)\b', folded)
    if _MENTION_CONTEXT.match(folded):
        return not any(_INDEPENDENT_CLAIM.match(part.strip()) for part in parts[1:])
    return question and len(parts) == 1 and _QUESTION_END.search(folded) is not None


def assertion_text(text: str) -> str:
    sentences = re.split(r'([?!;]|\.(?!\d)|\n)', text)
    assertions = []
    for index in range(0, len(sentences), 2):
        sentence = re.sub(r'[*`]|__', '', sentences[index]).strip()
        question = index + 1 < len(sentences) and sentences[index + 1] == '?'
        if _context_only(sentence, question):
            continue
        folded = _search_text(re.sub(r'^(?:Dạ|Vâng)[,\s]+', '', sentence, flags=re.IGNORECASE))
        if _NON_ASSERTION.fullmatch(folded + ('?' if index + 1 < len(sentences) and sentences[index + 1] == '?' else '')):
            continue
        capability = _CAPABILITY.search(folded)
        if (capability and _CAPABILITY_ACTION.search(folded, capability.end())
                and not _CONCRETE_CAPABILITY_CLAIM.search(folded)):
            continue
        assertions.append(sentences[index] + (sentences[index + 1] if index + 1 < len(sentences) else ''))
    text = ''.join(assertions)
    parts = re.split(r"([?!;]|\.(?!\d)|\n|\bnhưng\b|\bvà\b|\bnên\b|,\s*(?!\d))", text,
                     flags=re.IGNORECASE)
    kept = []
    for index in range(0, len(parts), 2):
        part = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ''
        folded = re.sub(r"^(?:da|vang)(?:\s+(?:anh/chi|anh|chi|ban|co|chu))?[,\s]+",
                        "", _search_text(part).strip())
        if (_LOOKUP.fullmatch(folded.rstrip("?!;. "))
                or _NON_ASSERTION.fullmatch(folded + ('?' if separator == '?' else ''))
                or _context_only(part, separator == '?')):
            continue
        kept.append(part + separator)
    return ''.join(kept)
