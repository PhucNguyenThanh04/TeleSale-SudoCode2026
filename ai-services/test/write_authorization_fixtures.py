from uuid import uuid4

from app.mcp_servers.mcp_order.write_authorization import (
    AuthorizedWriteContext, sign_write_authorization, write_args_digest,
    write_digest, write_operation_key)


WRITE_TEST_SECRET = 'offline-scripted-write-grant'


def scripted_write_context(name, args, *, customer_id, source_channel='hotline', source_identity=None):
    identity = (source_identity or args.get('source_identity') or args.get('customer_phone')
                or args.get('brief', {}).get('customer_phone'))
    on = args.get('on') or str(args.get('callback_at') or args.get('brief', {}).get('generated_at'))[:10]
    context = AuthorizedWriteContext(session_id=uuid4(), request_id=uuid4(),
        customer_id=customer_id, source_channel=source_channel, source_identity=identity,
        on=on, tool=name, args_hash=write_args_digest(name, args),
        customer_text_hash=write_digest('scripted offline customer approval'),
        review_context_hash=write_digest('scripted offline interpretation context'))
    payload = {**args, 'source_channel': source_channel, 'source_identity': identity,
               'operation_key': write_operation_key(context, args)}
    return context, payload


def scripted_write_args(name, args, **context_fields):
    context, payload = scripted_write_context(name, args, **context_fields)
    return {**payload, 'trusted_authorization': sign_write_authorization(
        name, payload, context, WRITE_TEST_SECRET)}
