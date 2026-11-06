"""Self-reviewed language labels; matching never uses scenario truth or scores."""
import json
from pathlib import Path
from eval_harness.extractor import extract_detailed

LABEL_PATH = Path(__file__).with_name('fixtures')/'extraction_integrity_labels.json'


def normalize(text):
    import re
    return re.sub(r'[\W_]+', ' ', text.casefold()).strip()


def measure(cases):
    """Match by frozen speech anchor and occurrence order, never predicted label.

    Same-span atomic requests (size/color, price/offer) use their frozen ordinal.
    Missing/extra candidates are detection errors, mismatched fields are separate.
    """
    counts = dict(expected=0, detected=0, matched=0, false_positive=0, false_negative=0,
                  classification_errors=0, field_value_type_errors=0, disposition_errors=0, qualifier_errors=0)
    errors = []
    for case in cases:
        actual = extract_detailed(case['text'])['candidates']
        labels = case['units']
        unused = set(range(len(actual)))
        counts['expected'] += len(labels)
        counts['detected'] += len(actual)
        for label in labels:
            matching = [i for i in sorted(unused) if actual[i]['kind'] == label['kind'] and
                        (normalize(label['anchor']) in normalize(actual[i]['text']) or normalize(actual[i]['text']) in normalize(label['anchor']))]
            if not matching:
                counts['false_negative'] += 1
                errors.append({'text':case['text'], 'error':'missing', 'label':label})
                continue
            index = matching[0]
            unused.remove(index)
            counts['matched'] += 1
            candidate = actual[index]
            projection = candidate['projection'] or {}
            classification = [projection.get(k) for k in ('slot','type') if k in projection] if label['kind'] == 'question' else [projection.get('field'),projection.get('value')]
            bad_class = 'projection' in label and (classification != label['projection'] or bool(candidate['uncertainty']))
            bad_disp = candidate['disposition'] != label['disposition'] or ('reason' in label and candidate['reason'] != label['reason'])
            bad_qualifier = 'qualifiers' in label and candidate['qualifiers'] != label['qualifiers']
            counts['field_value_type_errors'] += int(bad_class)
            counts['disposition_errors'] += int(bad_disp)
            counts['qualifier_errors'] += int(bad_qualifier)
            if bad_class or bad_disp or bad_qualifier or candidate['disposition'] == 'unresolved':
                counts['classification_errors'] += 1
                errors.append({'text':case['text'], 'error':'classification', 'label':label, 'actual':candidate})
        counts['false_positive'] += len(unused)
        errors.extend({'text':case['text'], 'error':'extra', 'actual':actual[i]} for i in sorted(unused))
    counts['detection_precision'] = counts['matched']/counts['detected'] if counts['detected'] else None
    counts['detection_recall'] = counts['matched']/counts['expected'] if counts['expected'] else None
    return {'counts':counts, 'errors':errors, 'label_review':'self-reviewed; not independent human calibration or hidden tests'}


def quality_report():
    cases = json.loads(LABEL_PATH.read_text())['cases']
    return {split: measure([case for case in cases if case['split'] == split])
            for split in ('regression', 'development', 'verification')}


def test_frozen_language_labels():
    report = quality_report()
    assert all(not result['errors'] for result in report.values()), json.dumps(report,ensure_ascii=False,indent=2)


def test_matching_does_not_hide_wrong_values_or_missing_extra_candidates():
    case = {'text':'Giá 700.000đ.', 'units':[{'kind':'claim','anchor':'Giá 700.000đ','projection':['price_vnd',1], 'disposition':'emitted'}]}
    counts = measure([case])['counts']
    assert counts['classification_errors'] == 1 and counts['matched'] == 1
    case['units'] *= 2
    assert measure([case])['counts']['false_negative'] == 1
    case['units'] = []
    assert measure([case])['counts']['false_positive'] == 1


def test_matching_accepts_context_prefix_without_using_predicted_field():
    case = {'text': 'Để lên đơn, anh chọn size nào?', 'units': [
        {'kind': 'question', 'anchor': 'Để lên đơn, anh chọn size nào', 'projection': ['size','open'], 'disposition':'emitted'}]}
    assert measure([case])['errors'] == []
