"""Browser smoke of the real console against a synthetic, credential-free API."""
import re
import shutil
import subprocess
from pathlib import Path
import pytest


def test_console_can_review_publish_and_submit_feedback(tmp_path):
    chrome = shutil.which('google-chrome')
    if not chrome:
        pytest.skip('Chrome is unavailable; no browser dependency installed')
    root = Path(__file__).resolve().parents[2]/'frontend'
    html = re.sub(r'<script[^>]*src=[^>]*></script>', '', (root/'index.html').read_text())
    fixture = r'''
    let active=null, commands=[], revision=null;
    const gap={id:'g',title:'Đổi hàng',event_ids:['e'],version:1,category:'content',status:'new'};
    const testCase={id:'rev',record_hash:'casehash',input:{question:'đổi'},expected:{answer:'Còn tem'},variations:['đổi']};
    window.fetch=async function(url, options={}) {
      const u=new URL(url,location.href), res=u.pathname.split('/').pop(); let data={};
      if(res==='identity') data={actor_id:'local-demo:staff'};
      else if(res==='commands') {
        const c=JSON.parse(options.body); commands.push(c);
        if(c.action==='create_revision') { revision={...c.payload,id:'rev',content_hash:'hash',status:'draft'}; data=revision; }
        if(c.action==='approve') { revision.status='approved'; data=revision; }
        if(c.action==='prepare_release') data={id:'release',status:'ready'};
        if(c.action==='activate_release') { active='release'; data={release_id:active}; }
      } else if(res==='feedback') { commands.push({action:'feedback',payload:JSON.parse(options.body)}); data={status:'queued'}; }
      else { const rows=res==='gaps'?[gap]:res==='events'?[{id:'e',question:'đổi?',answer:'chưa rõ'}]:res==='regression_cases'?[testCase]:res==='revisions'?[revision]:[];
        data={items:rows,total:rows.length,active_release_id:active}; }
      return {ok:true,status:200,json:async()=>data};
    };
    window.browserErrors=[];
    window.addEventListener('error',e=>browserErrors.push(e.message));
    window.addEventListener('unhandledrejection',e=>browserErrors.push(String(e.reason)));
    '''
    driver = r'''
    const tick=()=>new Promise(r=>setTimeout(r,10));
    const click=async text=>{ const b=[...document.querySelectorAll('button')].find(x=>x.textContent===text); if(!b) throw new Error('Missing button '+text); b.click(); await tick(); };
    const fill=(text,value)=>{const l=[...document.querySelectorAll('#knowledge-detail label')].find(x=>x.firstChild.textContent===text); if(!l)throw new Error('Missing field '+text); l.querySelector('input,textarea,select').value=value;};
    (async()=>{
      try {
        await TeleSaleKnowledge.refresh();
        document.querySelector('#knowledge-list button').click(); await tick();
        fill('Câu hỏi','Đổi hàng?'); fill('Câu trả lời FAQ','Cần còn nguyên tem.');
        fill('Mã chunk nguồn (cách nhau dấu phẩy)','DT-01');
        fill('Kết quả rà soát nguồn và phạm vi hiệu lực','Đã đối chiếu nguồn.');
        await click('Lưu bản nháp');
        document.querySelector('#knowledge-detail input[type=checkbox]').checked=true;
        fill('Lý do quyết định','Đúng nguồn');
        await click('Duyệt nội dung và test');
        await click('Thêm mã vào danh sách phát hành');
        document.querySelector('#knowledge-prepare').click(); await tick();
        await click('Phát hành phiên bản này');
        TeleSaleKnowledge.attachFeedback(document.body,'11111111-1111-4111-8111-111111111111',1);
        const feedback=[...document.querySelectorAll('details')].find(x=>x.querySelector('summary')?.textContent==='Đánh giá câu trả lời');
        feedback.querySelector('textarea').value='Câu trả lời cần sửa';
        feedback.querySelector('button').click(); await tick();
        if(active!=='release')throw new Error('Release not activated');
        if(commands.find(x=>x.action==='feedback')?.payload.turn_no!==1)throw new Error('Feedback mapped to wrong turn');
        if(browserErrors.length)throw new Error(browserErrors.join(';'));
        document.body.append(Object.assign(document.createElement('pre'),{id:'browser-result',textContent:'KNOWLEDGE_BROWSER_PASS'}));
      } catch(e) { document.body.append(Object.assign(document.createElement('pre'),{id:'browser-result',textContent:'FAIL: '+e.stack})); }
    })();
    '''
    scripts = fixture + '\n' + (root/'knowledge.js').read_text() + '\n' + (root/'workspace.js').read_text() + '\n' + driver
    page = tmp_path/'smoke.html'
    page.write_text(html.replace('</body>', '<script>'+scripts+'</script></body>'))
    result = subprocess.run([chrome,'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--disable-background-networking','--no-first-run','--no-default-browser-check',
        '--user-data-dir='+str(tmp_path/'profile'),'--virtual-time-budget=3000','--dump-dom',page.as_uri()],
        capture_output=True,text=True,timeout=30)
    match=re.search(r'<pre id="browser-result">(.*?)</pre>',result.stdout,re.S)
    assert match and match.group(1)=='KNOWLEDGE_BROWSER_PASS', (match.group(1) if match else result.stderr[-1500:])
