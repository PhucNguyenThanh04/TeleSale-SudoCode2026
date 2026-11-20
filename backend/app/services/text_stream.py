import json

from app.schemas.chat import AITextTurnResponse


async def stream_text_turn(http, payload):
    sequence, answer = 1, ''
    async with http.stream('POST', '/v1/chat/turns/stream', json=payload) as response:
        response.raise_for_status()
        if not response.headers.get('content-type', '').startswith('application/x-ndjson'):
            raise ValueError('invalid_stream_content_type')
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if (not isinstance(event, dict) or any(event.get(key) != payload[key]
                    for key in ('session_id', 'client_msg_id'))):
                raise ValueError('stream_identity_changed')
            if event.get('event') == 'delta':
                text = event.get('text')
                if (type(event.get('seq')) is not int or event['seq'] != sequence
                        or not isinstance(text, str) or not text):
                    raise ValueError('invalid_stream_delta')
                sequence += 1
                answer += text
                yield {'event': 'delta', 'text': text, 'seq': event['seq']}
            elif event.get('event') == 'done':
                reply = AITextTurnResponse.model_validate(event)
                if not answer or reply.agent_text != answer:
                    raise ValueError('stream_answer_changed')
                yield event
                return
            else:
                raise ValueError('upstream_stream_failed')
    raise ValueError('stream_missing_done')
