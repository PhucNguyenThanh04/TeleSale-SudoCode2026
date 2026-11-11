"""Replay truncated local tool responses without a live model."""
import asyncio
import json
from unittest.mock import patch

import httpx2 as httpx
import pytest

from app.configs import Settings
from app.infarstructure.llm import build_llm


TOOL = {'type': 'function', 'function': {'name': 'remember', 'description': 'Remember',
    'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}}


def response(request, reason, prompt=1000):
    message = {'role': 'assistant', 'content': '<tool_call>{"name":"remember","arguments":{"value":"'}
    if reason == 'tool_calls':
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'call-ok', 'type': 'function',
            'function': {'name': 'remember', 'arguments': '{"value":"safe"}'}}]}
    return httpx.Response(200, request=request, json={
        'id': 'local-test', 'object': 'chat.completion', 'created': 0,
        'model': 'local', 'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
        'usage': {'prompt_tokens': prompt, 'completion_tokens': 100, 'total_tokens': prompt + 100}})


@pytest.mark.parametrize('asynchronous', [False, True])
def test_local_retries_truncated_tool_response_once_with_more_output_room(asynchronous):
    llm = build_llm(Settings(_env_file=None, llm_backend='local', llm_max_tokens=1024))
    requests = []

    def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        return response(request, 'length' if len(requests) == 1 else 'tool_calls')

    async def async_send(client, request, **kwargs):
        return send(client, request, **kwargs)

    with patch.object(httpx.Client, 'send', send), patch.object(httpx.AsyncClient, 'send', async_send):
        bound = llm.bind_tools([TOOL])
        result = asyncio.run(bound.ainvoke('Remember')) if asynchronous else bound.invoke('Remember')
    assert [r['max_completion_tokens'] for r in requests] == [1024, 2048]
    assert requests[0]['messages'] == requests[1]['messages']
    assert result.tool_calls[0]['args'] == {'value': 'safe'}
    assert result.usage_metadata['total_tokens'] == 2200


@pytest.mark.parametrize('prompt,expected_budgets', [(8190, [1024]), (7000, [1024, 1192]), (1000, [1024, 2048])])
def test_local_never_returns_truncated_tool_calls_or_retries_without_headroom(prompt, expected_budgets):
    llm = build_llm(Settings(_env_file=None, llm_backend='local', llm_max_tokens=1024))
    requests = []

    def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        return response(request, 'length', prompt)

    with patch.object(httpx.Client, 'send', send), pytest.raises(ValueError, match='local_tool_output_truncated') as caught:
        llm.bind_tools([TOOL]).invoke('Remember')
    assert [r['max_completion_tokens'] for r in requests] == expected_budgets
    assert caught.value.code == 'local_tool_output_truncated'


def test_cloud_does_not_receive_local_retry_policy():
    llm = build_llm(Settings(_env_file=None, llm_api_key='cloud-test', llm_model='cloud'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(request)
        return response(request, 'length')

    with patch.object(httpx.Client, 'send', send):
        result = llm.bind_tools([TOOL]).invoke('Remember')
    assert len(requests) == 1
    assert result.response_metadata['finish_reason'] == 'length'


def test_local_timeout_allows_serial_gpu_generation_and_cloud_keeps_its_timeout():
    local = build_llm(Settings(_env_file=None, llm_backend='local', llm_timeout_seconds=12))
    cloud = build_llm(Settings(_env_file=None, llm_api_key='cloud', llm_model='cloud', llm_timeout_seconds=12))
    assert local.request_timeout == 120
    assert cloud.request_timeout == 12


def test_local_bad_request_is_not_blindly_retried():
    llm = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(request)
        return httpx.Response(400, request=request, json={'error': {
            'message': 'input exceeds context', 'type': 'BadRequestError', 'param': 'input_tokens', 'code': 400}})

    with patch.object(httpx.Client, 'send', send), pytest.raises(Exception) as caught:
        llm.bind_tools([TOOL]).invoke('Remember')
    assert getattr(caught.value, 'status_code', None) == 400
    assert len(requests) == 1


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('structured', [False, True])
def test_local_recovers_parser_failure_even_when_finish_reason_is_stop(asynchronous, structured):
    llm = build_llm(Settings(_env_file=None, llm_backend='local', llm_max_tokens=1024))
    requests = []

    def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        reply = response(request, 'stop' if len(requests) == 1 else 'tool_calls')
        if structured and len(requests) == 1:
            data = reply.json()
            data['choices'][0]['message'] = {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': 'bad', 'type': 'function', 'function': {'name': 'remember', 'arguments': '{bad json'}}]}
            reply = httpx.Response(200, request=request, json=data)
        return reply

    async def async_send(client, request, **kwargs):
        return send(client, request, **kwargs)

    with patch.object(httpx.Client, 'send', send), patch.object(httpx.AsyncClient, 'send', async_send):
        bound = llm.bind_tools([TOOL])
        result = asyncio.run(bound.ainvoke('Remember')) if asynchronous else bound.invoke('Remember')
    assert len(requests) == 2
    assert requests[1]['messages'] == requests[0]['messages']
    assert requests[1]['tool_choice'] == 'required'
    assert requests[1]['parallel_tool_calls'] is False
    assert requests[1]['max_completion_tokens'] == 1024
    assert result.tool_calls[0]['args'] == {'value': 'safe'}
    assert not result.invalid_tool_calls
    assert result.usage_metadata['total_tokens'] == 2200


@pytest.mark.parametrize('asynchronous', [False, True])
def test_local_rejects_repeated_parser_failure_without_persisting_raw_tool_text(asynchronous):
    llm = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(request)
        return response(request, 'stop')

    async def async_send(client, request, **kwargs):
        return send(client, request, **kwargs)

    with patch.object(httpx.Client, 'send', send), patch.object(httpx.AsyncClient, 'send', async_send):
        with pytest.raises(ValueError, match='local_tool_output_invalid'):
            bound = llm.bind_tools([TOOL])
            asyncio.run(bound.ainvoke('Remember')) if asynchronous else bound.invoke('Remember')
    assert len(requests) == 2


def test_local_does_not_accept_plain_text_in_place_of_recovered_tool_call():
    llm = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(request)
        reply = response(request, 'stop')
        if len(requests) == 2:
            data = reply.json()
            data['choices'][0]['message']['content'] = 'Đã nhớ thông tin.'
            reply = httpx.Response(200, request=request, json=data)
        return reply

    with patch.object(httpx.Client, 'send', send), pytest.raises(ValueError, match='local_tool_output_invalid'):
        llm.bind_tools([TOOL]).invoke('Remember')
    assert len(requests) == 2


def test_local_normal_text_with_available_tools_is_not_forced_into_a_call():
    llm = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(request)
        data = response(request, 'stop').json()
        data['choices'][0]['message']['content'] = 'Xin chào chị.'
        return httpx.Response(200, request=request, json=data)

    with patch.object(httpx.Client, 'send', send):
        result = llm.bind_tools([TOOL]).invoke('Chào')
    assert result.content == 'Xin chào chị.'
    assert len(requests) == 1


@pytest.mark.parametrize('choice', ['auto', 'any', 'remember'])
def test_local_first_request_constrains_schema_and_preserves_tool_choice(choice):
    llm = build_llm(Settings(_env_file=None, llm_backend='local'))
    requests = []

    def send(client, request, **kwargs):
        requests.append(json.loads(request.content))
        return response(request, 'tool_calls')

    with patch.object(httpx.Client, 'send', send):
        llm.bind_tools([TOOL], tool_choice=choice).invoke('Remember')
    payload = requests[0]
    assert 'parallel_tool_calls' not in payload
    assert payload['tools'][0]['function']['strict'] is True
    assert payload['tool_choice'] == ({'type': 'function', 'function': {'name': 'remember'}}
                                     if choice == 'remember' else 'required' if choice == 'any' else 'auto')
    assert len(requests) == 1
