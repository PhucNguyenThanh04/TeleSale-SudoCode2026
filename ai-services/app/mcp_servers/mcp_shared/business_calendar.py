import json
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def load_calendar():
    rules = json.loads(Path(__file__).with_name('business-calendar.json').read_text())
    ZoneInfo(rules['timezone'])
    if set(rules['weekly']) != {str(day) for day in range(7)} or not any(rules['weekly'].values()):
        raise ValueError('A weekly opening schedule is required')
    for windows in [*rules['weekly'].values(), *(item.get('hours', []) for item in rules['dates'].values())]:
        for start, end in windows:
            if time.fromisoformat(start) >= time.fromisoformat(end):
                raise ValueError('Invalid opening window')
    for day in rules['dates']:
        datetime.fromisoformat(day)
    return rules


def _local(moment, rules, naive_timezone=None):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(naive_timezone or rules['timezone']))
    return moment.astimezone(ZoneInfo(rules['timezone']))


def normalize_callback_at(moment, *, calendar=None, naive_timezone=None):
    rules = calendar if calendar is not None else load_calendar()
    moment = _local(moment, rules, naive_timezone)
    closed_day = False
    for _ in range(8 + len(rules['dates'])):
        windows = rules['dates'].get(moment.date().isoformat(), {}).get(
            'hours', rules['weekly'][str(moment.weekday())])
        if not windows:
            moment += timedelta(days=1)
            closed_day = True
            continue
        if closed_day and all(moment >= datetime.combine(moment.date(), time.fromisoformat(end), moment.tzinfo)
                              for _, end in windows):
            moment = datetime.combine(moment.date(), time.fromisoformat(min(windows)[0]), moment.tzinfo)
        for start, end in sorted(windows):
            opening = datetime.combine(moment.date(), time.fromisoformat(start), moment.tzinfo)
            closing = datetime.combine(moment.date(), time.fromisoformat(end), moment.tzinfo)
            if moment < closing:
                return max(moment, opening)
        moment = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        closed_day = False
    raise ValueError('No opening time available')


def callback_arguments(args, *, naive_timezone=None):
    rules = load_calendar()
    proposed = datetime.fromisoformat(args['callback_at'])
    original = datetime.fromisoformat(args.get('requested_callback_at') or args['callback_at'])
    effective = normalize_callback_at(original, calendar=rules, naive_timezone=naive_timezone)
    if args.get('requested_callback_at') and _local(proposed, rules, naive_timezone) != effective:
        raise ValueError('Callback does not match the normalized request')
    result = {**args, 'callback_at': effective.isoformat()}
    result.pop('requested_callback_at', None)
    if effective != _local(original, rules, naive_timezone):
        result['requested_callback_at'] = original.isoformat()
    return result
