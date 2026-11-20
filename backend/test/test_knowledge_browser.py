from contextlib import asynccontextmanager
import json
import base64
from pathlib import Path
import socket
import threading
import time
from copy import deepcopy

import httpx
import pytest
import uvicorn
from app.configs import VoiceSettings
from gateway_fixture import create_app
from test_voice_browser import browser


@pytest.fixture
def review_site():
    data = {
        'gaps': [{'id':'G1','title':'Điều kiện đổi hàng <img src=x onerror=alert(1)>',
                  'version':1,'status':'new','category':'content','event_ids':['E1'],
                  'suggested_source_ids':['DT-01']},
                 {'id':'G2','title':'Model lỗi tool','version':1,'status':'technical_followup',
                  'category':'technical','event_ids':[]}],
        'events':[{'id':'E1','source':'evaluation_result','signal':'evaluation_failure',
                   'question':'Đổi khi nào?','answer':'<b>Không rõ</b>','reason':'Thiếu điều kiện'}],
        'sources':[{'id':'DT-01','chunk_id':'DT-01','title':'Đổi trả','body':'Cần còn nguyên tem.',
                    'source_hash':'sourcehash','effective_from':'2026-10-01','date_basis':'order_date'}],
        'revisions':[], 'regression_cases':[], 'releases':[], 'verification_runs':[]}
    state = {'active':None,'commands':[],'error':None,'queries':[],'error_action':None,'error_id':None}
    async def handler(request):
        assert request.headers['X-AI-Internal-Token'] == 'server-secret'
        assert 'review-access' not in request.headers.values()
        resource = request.url.path.split('/')[-1]
        if resource == 'commands':
            payload = json.loads(request.content); assert payload['actor_id'] == 'reviewer-1'
            state['commands'].append(payload)
            if (state['error'] and (not state['error_action'] or payload['action'] == state['error_action'])
                    and (not state['error_id'] or payload['payload'].get('id') == state['error_id'])):
                code = state['error']; state['error'] = None
                return httpx.Response(code, text='private server-secret')
            action, p = payload['action'], payload['payload']
            if action == 'classify':
                gap = next(g for g in data['gaps'] if g['id'] == p['id']); gap.update(category=p['category'],version=gap['version']+1); result=gap
            elif action in {'create_revision','edit_revision','edit_test'}:
                old = next((r for r in data['revisions'] if r['id'] == p.get('id')), {})
                result = {**old, **(p.get('changes', {}) if action=='edit_revision' else p if action=='create_revision' else {}),
                          'id':'R'+str(len(data['revisions'])+1),'content_hash':'hash'+str(len(data['revisions'])+1),'status':'draft'}
                data['revisions'].append(result)
                data['regression_cases'].append({'id':result['id'],'record_hash':'testhash',
                    'input':{'question':result['question']},'expected':p.get('expected',{'answer':result.get('answer'),'source_ids':result['source_ids']}),
                    'variations':p.get('variations',[result['question']]),'approved':False})
            elif action in {'approve','reject'}:
                result=next(r for r in data['revisions'] if r['id']==p['id'])
                assert p['content_hash']==result['content_hash']
                if action=='approve':assert p['approve_test'] is True
                result['status']='approved' if action=='approve' else 'rejected'
            elif action=='prepare_release':
                assert p['expected_active_id']==state['active']
                result={'id':'K'+str(len(data['releases'])+1),'status':'ready','manifest':{
                    'items':[deepcopy(r) for r in data['revisions'] if r['id'] in p['revision_ids']],
                    'offline_checks':[{'status':'passed','kind':'lexical_retrieval','llm_answer_evaluated':False}]}}
                data['releases'].append(result)
            else:
                assert action in {'activate_release','rollback_release'}
                assert p['expected_active_id']==state['active']
                state['active']=p['id']; result={'release_id':p['id']}
            return httpx.Response(200,json=deepcopy(result))
        items=data[resource]
        state['queries'].append((resource, dict(request.url.params)))
        run_id = request.url.params.get('run_id')
        if run_id:
            events = {e['id'] for e in data['events'] if e.get('run_id') == run_id}
            gaps = {g['id'] for g in data['gaps'] if events.intersection(g.get('event_ids', []))}
            revisions = {r['id'] for r in data['revisions'] if r.get('gap_id') in gaps}
            scoped = {'events': events, 'gaps': gaps, 'revisions': revisions, 'regression_cases': revisions}
            if resource in scoped: items = [i for i in items if i['id'] in scoped[resource]]
        for key in ['status','gap_id']:
            value=request.url.params.get(key)
            if value:items=[r for r in items if r.get(key)==value]
        item_id=request.url.params.get('item_id')
        if item_id:items=[r for r in items if r['id']==item_id]
        offset=int(request.url.params.get('offset',0)); limit=int(request.url.params.get('limit',30))
        return httpx.Response(200,json={'items':deepcopy(items[offset:offset+limit]),'total':len(items),'active_release_id':state['active']})
    app=create_app(VoiceSettings(_env_file=None,knowledge_reviewer_id='reviewer-1',ai_internal_token='server-secret'))
    original=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            async with httpx.AsyncClient(base_url='http://offline',headers={'X-AI-Internal-Token':'server-secret'},transport=httpx.MockTransport(handler)) as client:
                app.state.ai_http=client; yield
    app.router.lifespan_context=lifespan
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True); thread.start()
    deadline=time.monotonic()+5
    while not server.started:
        assert time.monotonic()<deadline; time.sleep(.02)
    try:yield f'http://127.0.0.1:{port}/knowledge',data,state
    finally:server.should_exit=True;thread.join(5);listener.close()


def open_review(browser,url):
    command,evaluate=browser
    command('Page.enable'); command('Emulation.setDeviceMetricsOverride',width=1440,height=1000,deviceScaleFactor=1,mobile=False); command('Page.navigate',url=url)
    deadline=time.monotonic()+8
    while not evaluate("document.querySelector('#gap-count')?.textContent.includes('gap') && !document.body.hasAttribute('aria-busy')"):
        assert time.monotonic()<deadline;time.sleep(.02)
    evaluate("""window.errors=[];
      addEventListener('error',e=>errors.push(e.message));
      addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
      window.waitFor=predicate=>new Promise((resolve,reject)=>{const started=Date.now();const poll=()=>{
        if(predicate()&&!document.body.hasAttribute('aria-busy'))resolve(true);
        else if(Date.now()-started>7000)reject(Error(document.body.innerText));else setTimeout(poll,20);
      };poll();});
      window.clickText=text=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent===text);if(!b)throw Error('Missing '+text);b.click();};
      window.fill=(label,value)=>{const l=[...document.querySelectorAll('#detail label')].find(l=>l.firstChild.textContent===label);if(!l)throw Error('Missing '+label);l.querySelector('input,textarea,select').value=value;};
      waitFor(()=>!document.querySelector('#workspace').hidden);
    """)
    return command,evaluate


def draft(evaluate):
    evaluate("document.querySelector('[data-gap-id=G1]').click();waitFor(()=>document.querySelector('#detail').textContent.includes('Tạo đề xuất mới'))")
    evaluate("clickText('Tạo đề xuất mới');waitFor(()=>document.querySelector('#detail').textContent.includes('Câu trả lời đề xuất'))")
    evaluate("""fill('Câu hỏi','Đổi khi nào?');fill('Câu trả lời đề xuất','Cần còn nguyên tem.');
      fill('Kết quả đối chiếu nguồn và điều kiện áp dụng','Đã đối chiếu nguồn.');
      clickText('Lưu bản nháp');waitFor(()=>document.querySelector('#detail').textContent.includes('Quyết định duyệt'));
    """)


def approve(evaluate):
    evaluate("""fill('Lý do quyết định','Đúng nguồn và điều kiện');document.querySelector('#detail input[type=checkbox]').checked=true;
      clickText('Phê duyệt nội dung và test');waitFor(()=>document.querySelector('#detail').textContent.includes('Thêm vào danh sách phát hành'));
    """)


def seed_bulk(data, count):
    for number in range(count):
        revision = {'id': f'R{number}', 'gap_id': 'G1', 'status': 'draft',
            'content_hash': f'hash{number}', 'kind': 'faq', 'question': f'Đổi khi nào {number}?',
            'answer': 'Cần còn nguyên tem.', 'source_ids': ['DT-01'], 'source_review_note': 'Đã đối chiếu.'}
        data['revisions'].append(revision)
        data['regression_cases'].append({'id': revision['id'], 'expected': {'answer': revision['answer']},
            'variations': [revision['question']], 'approved': False})


def open_combined(evaluate, count):
    evaluate(f"clickText('Duyệt và phát hành');waitFor(()=>document.querySelector('#detail').innerText.includes('{count} đề xuất'))")


def confirm_combined(evaluate):
    evaluate("""fill('Lý do duyệt hàng loạt','Đã đối chiếu nguồn và test');
      [...document.querySelectorAll('#detail label')].find(l=>l.textContent.includes('Tôi đã đối chiếu')).querySelector('input').checked=true;
    """)


def test_combined_review_publishes_only_selected_and_keeps_base(review_site, browser):
    url, data, state = review_site
    data['events'][0]['run_id'] = 'experiment'
    seed_bulk(data, 3)
    old = dict(data['revisions'][0], id='OLD', gap_id='old', status='approved')
    foreign = dict(old, id='FOREIGN', gap_id='other')
    data['revisions'].extend([old, foreign])
    data['releases'].append({'id':'K0','status':'ready','manifest':{'items':[{'id':'OLD'}]}})
    state['active'] = 'K0'
    command, evaluate = open_review(browser, url+'?run_id=experiment')
    open_combined(evaluate, 3)
    assert not state['commands']
    assert evaluate("document.querySelectorAll('#detail input[data-revision-id]').length") == 3
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert not state['commands']
    evaluate("document.querySelector('[data-revision-id=R0]').checked=true;document.querySelector('[data-revision-id=R2]').checked=true")
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert not state['commands']
    confirm_combined(evaluate)
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>document.querySelector('#notice').textContent.includes('Đã phát hành'))")
    assert [c['action'] for c in state['commands']] == ['approve', 'approve', 'prepare_release', 'activate_release']
    assert [c['payload']['id'] for c in state['commands'][:2]] == ['R0', 'R2']
    assert set(state['commands'][2]['payload']['revision_ids']) == {'OLD','R0','R2'}
    assert state['active'] == 'K2'
    assert data['revisions'][1]['status'] == 'draft'
    assert evaluate("document.querySelector('#gaps-tab').getAttribute('aria-selected')") == 'true'
    command('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
    assert evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    assert evaluate('errors') == []


@pytest.mark.parametrize('stage', ['approve','prepare_release','activate_release'])
def test_combined_failure_does_not_activate_and_can_retry(review_site, browser, stage):
    url, data, state = review_site
    count = 2 if stage == 'approve' else 1
    seed_bulk(data, count)
    data['releases'].append({'id':'K0','status':'ready','manifest':{'items':[]}})
    state['active'] = 'K0'
    _, evaluate = open_review(browser, url)
    open_combined(evaluate, count)
    evaluate("document.querySelectorAll('[data-revision-id]').forEach(c=>c.checked=true)")
    confirm_combined(evaluate)
    state['error'], state['error_action'] = 409, stage
    if stage == 'approve': state['error_id'] = 'R1'
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert state['active'] == 'K0'
    assert state['commands'][-1]['action'] == stage
    if stage == 'approve':
        assert not any(c['action']=='prepare_release' for c in state['commands'])
        assert [r['status'] for r in data['revisions']] == ['approved', 'draft']
    if stage == 'prepare_release': assert not any(c['action']=='activate_release' for c in state['commands'])
    open_combined(evaluate, count)
    evaluate("document.querySelectorAll('[data-revision-id]').forEach(c=>c.checked=true)")
    confirm_combined(evaluate)
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>document.querySelector('#notice').textContent.includes('Đã phát hành'))")
    assert state['active'] != 'K0'
    assert evaluate('errors') == []


def test_combined_stops_before_approval_when_active_release_changed(review_site, browser):
    url, data, state = review_site
    seed_bulk(data, 1)
    _, evaluate = open_review(browser, url)
    open_combined(evaluate, 1)
    evaluate("document.querySelector('[data-revision-id=R0]').checked=true")
    confirm_combined(evaluate)
    state['active'] = 'changed-by-another-reviewer'
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert not state['commands']
    assert state['active'] == 'changed-by-another-reviewer'


def test_combined_checks_release_limit_before_approving(review_site, browser):
    url, data, state = review_site
    seed_bulk(data, 1)
    data['releases'].append({'id':'K0','status':'ready','manifest':{
        'items':[{'id':f'OLD{i}'} for i in range(100)]}})
    state['active'] = 'K0'
    _, evaluate = open_review(browser, url)
    open_combined(evaluate, 1)
    evaluate("document.querySelector('[data-revision-id=R0]').checked=true")
    confirm_combined(evaluate)
    evaluate("clickText('Duyệt và phát hành các mục đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert not state['commands'] and state['active'] == 'K0'
    assert evaluate("document.querySelector('#error').textContent.includes('100')")


def test_experiment_review_filters_gaps_and_keeps_active_revisions(review_site, browser):
    url, data, state = review_site
    data['events'][0]['run_id'] = 'experiment'
    seed_bulk(data, 1)
    old = dict(data['revisions'][0], id='OLD', gap_id='old-gap', status='approved')
    unrelated = dict(old, id='OTHER', gap_id='other-gap')
    data['revisions'].extend([old, unrelated])
    data['releases'].append({'id': 'K0', 'status': 'ready', 'manifest': {'items': [
        {k: old[k] for k in ('id', 'gap_id', 'kind', 'content_hash')}]}})
    state['active'] = 'K0'
    _, evaluate = open_review(browser, url+'?run_id=experiment')
    assert evaluate("document.querySelectorAll('.gap-row').length") == 1
    assert evaluate("document.querySelector('#experiment-scope').textContent.includes('experiment')")
    evaluate("clickText('Duyệt hết');waitFor(()=>document.querySelector('#detail').innerText.includes('1 bản nháp'))")
    evaluate("fill('Lý do duyệt hàng loạt','Đã đọc nguồn và test');document.querySelector('#detail input[type=checkbox]').checked=true;clickText('Duyệt 1 bản nháp');waitFor(()=>document.querySelector('#notice').innerText.includes('Đã duyệt 1/1'))")
    assert state['active'] == 'K0'
    evaluate("document.querySelector('#releases-tab').click();waitFor(()=>document.querySelector('#releases-view').innerText.includes('Chuẩn bị release'))")
    assert evaluate("document.querySelectorAll('#releases-view input:checked').length") == 2
    assert evaluate("document.querySelectorAll('#releases-view input:disabled:checked').length") == 1
    assert not evaluate("document.querySelector('#releases-view').textContent.includes('undefined')")
    assert not evaluate("document.querySelector('#releases-view').textContent.includes('OTHER')")
    evaluate("clickText('Chuẩn bị release từ các bản đã chọn');waitFor(()=>!!document.querySelector('#release-detail'))")
    prepared = state['commands'][-1]
    assert prepared['action'] == 'prepare_release'
    assert set(prepared['payload']['revision_ids']) == {'OLD', 'R0'}
    assert prepared['payload']['expected_active_id'] == 'K0'
    evaluate("window.confirm=()=>true;clickText('Phát hành release này');waitFor(()=>document.querySelector('#releases-view').innerText.includes('Đang hoạt động: K2'))")
    assert state['active'] == 'K2' and evaluate('errors') == []
    assert all(p.get('run_id') == 'experiment' for r, p in state['queries']
        if r in {'gaps', 'events', 'revisions', 'regression_cases'} and not p.get('item_id'))


def test_bulk_approve_all_pages_requires_review_and_never_publishes(review_site, browser):
    url, data, state = review_site
    seed_bulk(data, 101)
    data['revisions'].append({'id': 'R-approved', 'status': 'approved'})
    _, evaluate = open_review(browser, url)
    evaluate("clickText('Duyệt hết');waitFor(()=>document.querySelector('#detail').innerText.includes('101 bản nháp'))")
    evaluate("clickText('Duyệt 101 bản nháp');waitFor(()=>!document.querySelector('#error').hidden)")
    assert not state['commands']
    evaluate("fill('Lý do duyệt hàng loạt','Đã đọc nguồn và test');clickText('Duyệt 101 bản nháp');waitFor(()=>!document.querySelector('#error').hidden)")
    assert evaluate("document.querySelector('#error').innerText.includes('Cần xác nhận')")
    assert not state['commands']
    evaluate("fill('Lý do duyệt hàng loạt','Đã đối chiếu nguồn và test');document.querySelector('#detail input[type=checkbox]').checked=true;clickText('Duyệt 101 bản nháp');waitFor(()=>document.querySelector('#notice').innerText.includes('Đã duyệt 101/101'))")
    assert len(state['commands']) == 101
    assert all(c['action'] == 'approve' and c['payload']['approve_test'] for c in state['commands'])
    assert not data['releases'] and state['active'] is None
    evaluate("document.querySelector('#releases-tab').click();waitFor(()=>document.querySelector('#releases-view').innerText.includes('Chuẩn bị release'))")
    assert evaluate("document.querySelectorAll('#releases-view input:checked').length") == 101
    evaluate("clickText('Chuẩn bị release từ các bản đã chọn');waitFor(()=>!document.querySelector('#error').hidden)")
    assert evaluate("document.querySelector('#error').innerText.includes('tối đa 100')")
    assert not data['releases']


def test_bulk_partial_failure_keeps_successes_and_reports_remaining(review_site, browser):
    url, data, state = review_site
    seed_bulk(data, 2)
    _, evaluate = open_review(browser, url)
    evaluate("clickText('Duyệt hết');waitFor(()=>document.querySelector('#detail').innerText.includes('2 bản nháp'))")
    state['error'] = 409
    evaluate("fill('Lý do duyệt hàng loạt','Đã đọc nguồn và test');document.querySelector('#detail input[type=checkbox]').checked=true;clickText('Duyệt 2 bản nháp');waitFor(()=>document.querySelector('#notice').innerText.includes('Đã duyệt 1/2'))")
    assert [r['status'] for r in data['revisions']] == ['draft', 'approved']
    assert evaluate("document.querySelector('#detail').innerText.includes('R0')")
    assert not data['releases'] and state['active'] is None


def test_bulk_skips_technical_rejected_and_approved_revisions(review_site, browser):
    url, data, state = review_site
    seed_bulk(data, 3)
    data['revisions'][0]['gap_id'] = 'G2'
    data['revisions'][1]['status'] = 'approved'
    data['revisions'][2]['status'] = 'rejected'
    _, evaluate = open_review(browser, url)
    evaluate("clickText('Duyệt hết');waitFor(()=>document.querySelector('#notice').innerText.includes('Không có bản nháp'))")
    assert not state['commands']


def test_review_prepare_activate_rollback_without_login(review_site,browser):
    url,data,state=review_site;command,evaluate=open_review(browser,url)
    assert evaluate("document.querySelector('#gap-list img')===null")
    draft(evaluate)
    assert evaluate("[...document.querySelectorAll('#detail textarea')].some(n=>n.value==='Cần còn nguyên tem.')")
    evaluate("[...document.querySelectorAll('#detail details')].find(d=>d.querySelector('summary').textContent.includes('DT-01')).open=true")
    Path('/tmp/knowledge-review-desktop.png').write_bytes(base64.b64decode(command('Page.captureScreenshot',format='png')['data']))
    assert not state['active'] and not data['releases']
    approve(evaluate)
    assert not state['active']
    evaluate("clickText('Thêm vào danh sách phát hành');waitFor(()=>document.querySelector('#notice').innerText.includes('Đã chọn'))")
    evaluate("document.querySelector('#releases-tab').click();waitFor(()=>document.querySelector('#releases-view').innerText.includes('Chuẩn bị release'))")
    evaluate("clickText('Chuẩn bị release từ các bản đã chọn');waitFor(()=>!!document.querySelector('#release-detail'))")
    assert not state['active']
    evaluate("document.querySelector('#release-detail details').open=true")
    assert evaluate("document.querySelector('#release-detail').innerText.includes('llm_answer_evaluated')")
    evaluate("window.confirm=()=>true;clickText('Phát hành release này');waitFor(()=>document.querySelector('#releases-view').innerText.includes('Đang hoạt động: K1'))")
    assert state['active']=='K1'
    data['releases'].append({'id':'K0','status':'ready','manifest':{'items':[]}})
    evaluate("document.querySelector('#refresh').click();waitFor(()=>document.querySelector('#releases-view').innerText.includes('K0'))")
    evaluate("[...document.querySelectorAll('.release-row')].find(r=>r.textContent.includes('K0')).querySelector('button').click();waitFor(()=>document.querySelector('#release-detail').innerText.includes('Release K0'))")
    evaluate("clickText('Khôi phục về release này');waitFor(()=>document.querySelector('#releases-view').innerText.includes('Đang hoạt động: K0'))")
    assert state['commands'][-1]['action']=='rollback_release' and state['commands'][-1]['payload']['expected_active_id']=='K1'
    assert evaluate("localStorage.length===0&&sessionStorage.length===0")
    assert evaluate("document.querySelector('#access-form')===null&&document.querySelector('#logout')===null")
    assert evaluate('errors')==[]


def test_conflict_unsaved_content_and_technical_gap_are_not_approved(review_site,browser):
    url,data,state=review_site;_,evaluate=open_review(browser,url);draft(evaluate)
    evaluate("fill('Lý do quyết định','Đã đọc');clickText('Phê duyệt nội dung và test')")
    assert evaluate("document.querySelector('#error').innerText.includes('Cần xác nhận')")
    evaluate("document.querySelector('#detail input[type=checkbox]').checked=true;fill('Câu trả lời đề xuất','Thay đổi chưa lưu');clickText('Phê duyệt nội dung và test')")
    assert evaluate("document.querySelector('#error').innerText.includes('chưa lưu')")
    assert not any(c['action']=='approve' for c in state['commands'])
    evaluate("fill('Câu trả lời đề xuất','Cần còn nguyên tem.')")
    state['error']=409
    evaluate("clickText('Phê duyệt nội dung và test');waitFor(()=>!document.querySelector('#error').hidden)")
    assert evaluate("document.querySelector('#error').innerText.includes('Dữ liệu đã thay đổi')")
    assert data['revisions'][0]['status']=='draft'
    evaluate("clickText('← Quay lại bằng chứng');waitFor(()=>document.querySelector('#detail').innerText.includes('Lưu phân loại'))")
    evaluate("document.querySelector('[data-gap-id=G2]').click();waitFor(()=>document.querySelector('#detail').innerText.includes('Không tạo FAQ'))")
    assert evaluate("![...document.querySelectorAll('#detail button')].some(b=>b.textContent==='Tạo đề xuất mới')")
    assert evaluate('errors')==[]


def test_edit_regression_creates_new_draft_and_mobile_layout(review_site,browser):
    url,data,state=review_site;command,evaluate=open_review(browser,url);draft(evaluate)
    evaluate("fill('Biến thể kiểm thử (mỗi dòng một câu)','Đổi hàng cần gì?');clickText('Lưu test thành bản nháp mới');waitFor(()=>document.querySelector('#detail').innerText.includes('Revision R2'))")
    assert state['commands'][-1]['action']=='edit_test'
    assert state['commands'][-1]['payload']['test_hash']=='testhash'
    assert data['revisions'][-1]['status']=='draft'
    command('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=True)
    assert evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    Path('/tmp/knowledge-review-mobile.png').write_bytes(base64.b64decode(command('Page.captureScreenshot',format='png')['data']))
    assert evaluate('errors')==[]


def test_revision_edit_reject_and_queue_pagination(review_site,browser):
    url,data,state=review_site
    data['gaps'].extend({'id':f'G{i}','title':f'Gap {i}','version':1,'status':'new','category':'content','event_ids':[]} for i in range(3,36))
    _,evaluate=open_review(browser,url)
    assert evaluate("document.querySelectorAll('.gap-row').length") == 30
    evaluate("document.querySelector('#next').click();waitFor(()=>document.querySelector('#page-number').textContent==='Trang 2')")
    assert evaluate("document.querySelectorAll('.gap-row').length") == 5
    evaluate("document.querySelector('#previous').click();waitFor(()=>document.querySelector('#page-number').textContent==='Trang 1')")
    draft(evaluate)
    evaluate("fill('Câu trả lời đề xuất','Đổi khi hàng còn tem.');clickText('Lưu thành bản nháp mới');waitFor(()=>document.querySelector('#detail').innerText.includes('Revision R2'))")
    assert state['commands'][-1]['action']=='edit_revision'
    assert state['commands'][-1]['payload']['content_hash']=='hash1'
    assert data['revisions'][0]['answer']=='Cần còn nguyên tem.'
    evaluate("fill('Lý do quyết định','Cần rà soát thêm điều kiện');clickText('Từ chối bản này');waitFor(()=>document.querySelector('#detail').innerText.includes('Đã từ chối'))")
    assert data['revisions'][1]['status']=='rejected'
    assert not data['releases']
    assert evaluate('errors')==[]
