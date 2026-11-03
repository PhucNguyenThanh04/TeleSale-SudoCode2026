"""Deterministic date/applicability decisions; no intent or product classifier."""
from app.knowledge.schemas import Applicability, Evidence


def apply_policy_rules(chunks, request, context):
    if request.on != context.on:
        raise ValueError('Business date does not match trusted context')
    if request.order_date and request.order_date != context.verified_order_date:
        raise ValueError('Unverified order date')
    result = []
    for chunk in chunks:
        missing = list(chunk.required_context)
        basis = context.on
        source = 'runtime'
        conditional = False
        if chunk.date_basis == 'order_date':
            basis = context.verified_order_date or request.customer_reported_order_date
            source = context.date_source if context.verified_order_date else 'customer_reported' if basis else None
            conditional = not bool(context.verified_order_date)
            if basis is None and 'order_date' not in missing:
                missing.append('order_date')
        if basis and ((chunk.effective_from and basis < chunk.effective_from)
                      or (chunk.effective_until and basis > chunk.effective_until)):
            continue
        if context.verified_order_date and 'order_date' in missing:
            missing.remove('order_date')
        applied_rules = []
        for rule in chunk.rules:
            rule_date = context.verified_order_date or request.customer_reported_order_date if rule.date_basis == 'order_date' else context.on
            if rule_date and ((rule.effective_from and rule_date < rule.effective_from)
                              or (rule.effective_until and rule_date > rule.effective_until)):
                continue
            applied_rules.append(rule)
            for field in rule.required_context:
                if field == 'order_date' and context.verified_order_date:
                    continue
                if field not in missing:
                    missing.append(field)
        status = 'conflict' if chunk.conflict else 'conditional' if conditional or missing else 'applicable'
        result.append(Evidence(chunk_id=chunk.chunk_id, section_id=chunk.section_id,
            document_id=chunk.document_id, content=chunk.content, source=chunk.source,
            evidence_type=chunk.evidence_type, applicability=Applicability(status=status,
                date_basis=chunk.date_basis, date_used=basis, date_source=source,
                effective_from=chunk.effective_from, effective_until=chunk.effective_until,
                required_context=missing, rules=applied_rules)))
    return result
