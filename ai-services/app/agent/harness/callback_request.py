"""Parse only explicit, unambiguous callback instructions from current speech."""
import re
from datetime import date, timedelta
from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def callback_request(text: str, on: date) -> str | None:
    folded = _search_text(text)
    request_clauses = ' '.join(clause for clause in re.split(r'[,;.!]', folded)
                              if re.search(r'\bgoi\b|dat lich|\bhen\b', clause))
    if (not re.search(r'(?:dat lich|hen|goi lai)', folded)
            or not re.search(r'goi lai', folded)
            or re.search(r'\bneu\b|\?|\bhoac\b|\bhay\b|\bdung\b', folded)
            or re.search(r'\b(?:khong|chua|dung)\b', request_clauses)):
        return None
    dates = re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', folded)
    relative = on + timedelta(days=1) if 'ngay mai' in folded else on if 'hom nay' in folded else None
    if len(dates) > 1:
        return None
    try:
        day = date(int(dates[0][2]), int(dates[0][1]), int(dates[0][0])) if dates else relative
        if day is None or day < on or relative and day != relative:
            return None
        times = re.findall(r'\b(\d{1,2})\s*(?:gio|h)(?:\s*(\d{1,2})\s*(?:phut)?)?\b', folded)
        if len(times) != 1:
            return None
        hour, minute = int(times[0][0]), int(times[0][1] or 0)
        if re.search(r'\b(?:chieu|toi)\b', folded) and 1 <= hour < 12:
            hour += 12
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        return f'{day.isoformat()}T{hour:02d}:{minute:02d}'
    except ValueError:
        return None
