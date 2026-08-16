let currentJob=null,latestResults=[];const titles={overview:'Tổng quan',customers:'Dữ liệu khách hàng',analysis:'Phân tích',segments:'Phân nhóm',personas:'Khách hàng đại diện',campaign:'Chiến dịch',simulation:'Mô phỏng',assistant:'Trợ lý',reports:'Báo cáo',system:'Hệ thống',advanced:'A/B & Tối ưu','learning-history':'Lịch sử AI phân tích',help:'Hướng dẫn'};async function api(u,o={}){let r=await fetch(u,o),d={};try{d=await r.json()}catch{}if(r.status===401){location.href='/';throw Error('Phiên đăng nhập đã hết hạn')}if(r.status===403){location.href='/admin';throw Error(d.detail||'Tài khoản không có quyền nhân viên')}if(!r.ok)throw Error(d.detail||d.error||`HTTP ${r.status}`);return d}function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}function toast(t){let x=document.querySelector('#toast');x.textContent=t;x.classList.add('show');setTimeout(()=>x.classList.remove('show'),2500)}function showTab(id){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelector('#'+id).classList.add('active');document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));document.querySelector('#pageTitle').textContent=titles[id];history.replaceState(null,'','#'+id);if(id==='customers'){loadCustomers();loadStagedState();loadDatasetHistory();}if(id==='analysis')loadAnalysis();if(id==='segments')loadSegments();if(id==='personas')loadAllPersonas();if(id==='assistant')loadChatHistory();if(id==='learning-history')loadLearningHistory();if(id==='help')loadHelp();if(id==='reports')loadReports()}window.showTab=showTab;document.querySelectorAll('.nav-item').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));document.querySelector('#logout').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});location.href='/'};document.querySelector('#switchAdminMode').onclick=async()=>{let d=await api('/api/auth/switch-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'admin'})});location.href=d.redirect||'/admin'};async function init(){try{let m=await api('/api/auth/me');const allowed=m.role==='employee'||(m.role==='admin'&&m.active_mode==='employee');if(!allowed){location.href='/admin';return}document.querySelector('#userEmail').textContent=m.email+(m.role==='admin'?' · Chế độ nhân viên':'');if(m.role==='admin')document.querySelector('#switchAdminMode').classList.remove('hidden');const p=m.ai_provider==='ollama'?'ollama':'groq';if(document.querySelector('#provider'))document.querySelector('#provider').value=p;document.querySelector('#providerPill').textContent='AI: '+(p==='ollama'?'Ollama':'Groq')}catch{location.href='/';return}await refreshStats();await loadDatasetHistory();let t=location.hash.slice(1);if(titles[t])showTab(t)}async function refreshStats(){try{let d=await api('/api/overview');let p=d.purchase_intent||{},s=d.sentiment||{};document.querySelector('#statDataset').textContent=d.latest_dataset?.name||'Chưa có';document.querySelector('#statCustomers').textContent=(d.customers_saved||0).toLocaleString();document.querySelector('#statSavedCustomers').textContent=(d.customers_saved||0).toLocaleString();document.querySelector('#statScenarios').textContent=d.projects||0;document.querySelector('#statResponses').textContent=(d.responses||0).toLocaleString();document.querySelector('#statDataConfidence').textContent=(d.data_confidence_pct??0)+'%';document.querySelector('#statDatasets').textContent=d.datasets||0;document.querySelector('#statProvider').textContent=document.querySelector('#provider')?.value==='ollama'?'Ollama':'Groq';document.querySelector('#statBuy').textContent=(p.buy?.pct??0)+'%';document.querySelector('#statHesitate').textContent=(p.hesitate?.pct??0)+'%';document.querySelector('#statNotBuy').textContent=(p.not_buy?.pct??0)+'%';document.querySelector('#statBuyCount').textContent=(p.buy?.count||0).toLocaleString()+' khách hàng';document.querySelector('#statHesitateCount').textContent=(p.hesitate?.count||0).toLocaleString()+' khách hàng';document.querySelector('#statNotBuyCount').textContent=(p.not_buy?.count||0).toLocaleString()+' khách hàng';document.querySelector('#statPositive').textContent=(s.positive?.pct??0)+'%';document.querySelector('#statNeutral').textContent=(s.neutral?.pct??0)+'%';document.querySelector('#statNegative').textContent=(s.negative?.pct??0)+'%';document.querySelector('#statAvgScore').textContent='Điểm trung bình: '+(d.avg_score??0)+'/10';document.querySelector('#overviewLatest').textContent=d.latest_campaign?.name||'Chưa có';document.querySelector('#overviewLatestDetail').textContent=d.latest_campaign?`Đánh giá ${d.latest_campaign.rating??'—'}/5 · ${d.responses||0} phản hồi trong toàn bộ lịch sử dự án.`:'Chưa có dự án mô phỏng.'}catch(e){toast('Không thể tải tổng quan: '+e.message)}}async function loadDatasetHistory(){try{let d=await api('/api/customers/datasets');let st=d.stats||{};document.querySelector('#datasetStats').textContent=`${st.datasets||0} file · ${(st.canonical_customers||0).toLocaleString()} khách hàng đã lưu`;document.querySelector('#datasetHistory').innerHTML=(d.items||[]).map(x=>`<div class="dataset-history-item"><div><b>${esc(x.name)}</b><span>${Number(x.records||0).toLocaleString()} bản ghi · ${esc(x.uploaded_at||'')}</span></div><span class="status ${x.learning_confirmed?'ready':'wait'}">${x.learning_confirmed?'Đã xác nhận':'Chờ xác nhận'}</span></div>`).join('')||'<div class="empty">Chưa có dataset nào được lưu cho tài khoản này.</div>'}catch(e){let x=document.querySelector('#datasetStats');if(x)x.textContent='Không tải được lịch sử'}}
async function loadCustomers(){try{let d=await api('/api/customers?limit=100'),b=document.querySelector('#customerTable tbody');b.innerHTML='';d.items.forEach(x=>{let r=x.row;b.innerHTML+=`<tr><td>${esc(r.customer_id)}</td><td>${esc(r.age)}</td><td>${esc(r.location)}</td><td>${esc(r.job)}</td><td>${esc(r.segment_id??x.segment_id??'—')}</td><td>${esc(r.interest_keywords)}</td></tr>`});document.querySelector('#customerCount').textContent=d.items.length+' bản ghi hiển thị'}catch(e){toast(e.message)}}function renderAnalysis(s){let g=s.segmentation||{};document.querySelector('#analysisCards').innerHTML=`<div class="stat"><span>Số bản ghi</span><b>${(s.rows||0).toLocaleString()}</b></div><div class="stat"><span>Số cột</span><b>${(s.columns||[]).length}</b></div><div class="stat"><span>Số cụm</span><b>${g.n_clusters||0}</b></div><div class="stat"><span>Dữ liệu thật</span><b>${s.audit?.overall_real_data_pct??'—'}%</b></div>`}document.querySelector('#startSim').onclick=async()=>{let c=document.querySelector('#campaignText').value.trim(),n=document.querySelector('#campaignName').value.trim()||'Chiến dịch mô phỏng';if(!c){toast('Nhập nội dung chiến dịch trước.');return}try{let d=await api('/api/simulations/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({campaign:c,name:n,count:+document.querySelector('#personaCount').value,provider:document.querySelector('#provider').value})});currentJob=d.job_id;document.querySelector('#startMsg').textContent=`Đã tạo ${d.count} khách hàng ảo. Đang mô phỏng...`;document.querySelector('#startMsg').className='notice success';showTab('simulation');pollJob()}catch(e){document.querySelector('#startMsg').textContent=e.message;document.querySelector('#startMsg').className='notice error'}};async function pollJob(){if(!currentJob)return;try{let d=await api('/api/simulations/'+currentJob);document.querySelector('#progressBar').style.width=d.progress+'%';document.querySelector('#progressPercent').textContent=d.progress+'%';document.querySelector('#progressText').textContent=d.status==='completed'?'Đã hoàn thành':`Đang mô phỏng: ${d.progress}%`;document.querySelector('#progressDetail').textContent=d.status==='completed'?'Tất cả persona đã có phản hồi.':`Đã xử lý khoảng ${Math.round(d.progress*d.total/100)} / ${d.total} khách hàng ảo.`;if(d.status==='completed'){latestResults=d.results_preview||[];if(d.scenario_id){try{let all=await api('/api/simulations/'+d.scenario_id+'/results');renderResults(all.items||[])}catch{renderResults(latestResults)}}else{renderResults(latestResults)};loadAllPersonas();refreshStats();loadReports();return}if(d.status==='failed'){toast(d.error||'Mô phỏng thất bại');return}setTimeout(pollJob,500)}catch(e){toast(e.message)}}function renderResults(a){
  const count=document.querySelector('#resultCount');
  if(count)count.textContent=a.length+' phản hồi';
  const host=document.querySelector('#comments');
  if(!host)return;
  const pct=v=>{let n=Number(v);if(!Number.isFinite(n))return null;if(n<=1)n*=100;return Math.max(0,Math.min(100,Math.round(n)))+'%'};
  const intentLabel=v=>({buy:'Có xu hướng mua',hesitate:'Đang cân nhắc',not_buy:'Không có xu hướng mua'}[String(v||'').toLowerCase()]||v||'Chưa xác định');
  const sourceLabel=v=>v==='quantitative_with_ai_explanation'?'Điểm định lượng · AI diễn giải':v==='quantitative_fallback'?'Điểm định lượng · không có diễn giải AI':'Phản hồi mô phỏng';
  host.innerHTML=a.map(x=>{
    let p=x.persona||{},r=x.reaction||x,px=p.proxy_scores||{};
    const hasProfile=Object.keys(p).length>0;
    let facts=[];
    if(p.segment_id!=null)facts.push('Phân khúc '+esc(p.segment_id));
    if(p.age!=null)facts.push('Tuổi: '+esc(p.age));
    if(p.gender)facts.push('Giới tính: '+esc(p.gender));
    if(p.job)facts.push('Nghề: '+esc(p.job));
    if(p.location)facts.push('Khu vực: '+esc(p.location));
    if(p.product_category)facts.push('Danh mục: '+esc(p.product_category));
    if(p.rfm_segment)facts.push('RFM: '+esc(p.rfm_segment));
    if(p.customer_value_tier)facts.push('Giá trị KH: '+esc(p.customer_value_tier));

    let behavior=[];
    if(p.interest_keywords)behavior.push('<div><span>Sở thích</span><b>'+esc(p.interest_keywords)+'</b></div>');
    if(p.pain_point)behavior.push('<div><span>Vấn đề / nhu cầu chính</span><b>'+esc(p.pain_point)+'</b></div>');
    if(p.personality)behavior.push('<div><span>Tính cách</span><b>'+esc(p.personality)+'</b></div>');

    let proxies=[];
    const proxyPairs=[
      ['Sẵn sàng mua',px.purchase_readiness_proxy??p.purchase_readiness_proxy],
      ['Nhạy giá',px.price_sensitivity_proxy??p.price_sensitivity_proxy],
      ['Trung thành',px.loyalty_proxy??p.loyalty_proxy],
      ['Rủi ro rời bỏ',px.churn_risk_proxy??p.churn_risk_proxy],
      ['Giá trị',px.value_proxy??p.value_proxy]
    ];
    proxyPairs.forEach(([label,val])=>{let q=pct(val);if(q!==null)proxies.push(`<div><span>${label}</span><b>${q}</b></div>`)});

    let quality=[];
    let conf=pct(p.confidence);if(conf!==null)quality.push('Độ chắc chắn khách hàng ảo '+conf);
    let complete=pct(p.profile_completeness);if(complete!==null)quality.push('Hồ sơ '+complete+' đầy đủ');
    let rel=pct(p.source_data_reliability??p.data_reliability);if(rel!==null)quality.push('Độ tin cậy dữ liệu '+rel);

    const intent=r.purchase_intent||x.purchase_intent;
    const aiSource=r.source||x.source;
    const comment=r.comment||x.reasoning||'Khách hàng chưa để lại bình luận.';
    const reason=r.reason||x.reasoning||'Chưa có lý do chi tiết.';
    const name=p.name||p.twin_id||x.persona_name||'Khách hàng ảo';
    const provenance=p.data_provenance||{};
    let tech=[];
    if(p.generation_method)tech.push(`<div><span>Phương pháp tạo</span><b>${esc(p.generation_method)}</b></div>`);
    if(p.source_segment_size!=null)tech.push(`<div><span>Kích thước phân khúc nguồn</span><b>${esc(p.source_segment_size)}</b></div>`);
    if(provenance.real_source)tech.push(`<div><span>Nguồn tổng hợp</span><b>${esc(provenance.real_source)}</b></div>`);
    if(p.source_row_hash)tech.push(`<div><span>Mã audit nguồn</span><b>${esc(p.source_row_hash)}</b></div>`);

    return `<article class="comment twin-feed-card">
      <div class="twin-feed-head">
        <div><strong>${esc(name)}</strong>${hasProfile&&p.segment_id!=null?`<small>Digital Twin · Segment ${esc(p.segment_id)}</small>`:''}</div>
        <div class="twin-feed-badges">
          <span class="badge ${esc(r.sentiment||x.sentiment||'neutral')}">${esc(r.sentiment||x.sentiment||'neutral')}</span>
          ${intent?`<span class="intent-badge">${esc(intentLabel(intent))}</span>`:''}
        </div>
      </div>
      ${facts.length?`<div class="twin-facts">${facts.join(' · ')}</div>`:''}
      <div class="twin-feed-response">
        <span>Phản ứng khách hàng</span>
        <p>${esc(comment)}</p>
      </div>
      <div class="twin-score-row">
        <div><span>Điểm phản ứng</span><b>${esc(r.score??x.score??'—')}/10</b></div>
        <div class="twin-reason"><span>Lý do</span><p>${esc(reason)}</p></div>
        <span class="simulation-source">${esc(sourceLabel(aiSource))}</span>
      </div>
      ${proxies.length?`<div class="twin-proxy-grid">${proxies.join('')}</div>`:''}
      ${quality.length?`<div class="twin-quality">${quality.map(v=>`<span>${v}</span>`).join('')}</div>`:''}
      ${hasProfile?`<details class="twin-profile-details">
        <summary>Xem hồ sơ khách hàng ảo chi tiết</summary>
        ${behavior.length?`<div class="twin-behavior-grid">${behavior.join('')}</div>`:''}
        ${tech.length?`<div class="twin-tech-grid">${tech.join('')}</div>`:''}
        ${provenance.note?`<p class="twin-provenance-note">${esc(provenance.note)}</p>`:''}
      </details>`:`<div class="legacy-feed-note">Bản ghi mô phỏng cũ chưa lưu hồ sơ Digital Twin chi tiết.</div>`}
    </article>`;
  }).join('');
}function renderPersonas(a){document.querySelector('#personaEmpty').classList.toggle('hidden',a.length>0);document.querySelector('#personaList').innerHTML=a.map(x=>`<div class="persona"><b>${esc(x.persona.name)}</b><small>Nhóm ${esc(x.persona.cluster)} · ${esc(x.persona.age||'')} tuổi · ${esc(x.persona.city||'')}<br>Tính cách: ${esc(x.persona.personality)}<br>Sở thích: ${esc(x.persona.interests||'')}</small></div>`).join('')}async function loadReports(){try{let d=await api('/api/scenarios');document.querySelector('#reportCards').innerHTML=d.items.map(s=>`<div class="card" style="padding:20px"><span class="eyebrow">CHIẾN DỊCH #${s.id}</span><h3>${esc(s.name)}</h3><p><b>Đánh giá:</b> ${esc(s.rating??'—')}/5</p></div>`).join('')||'<div class="card" style="padding:20px">Chưa có báo cáo.</div>'}catch{}}async function checkAll(){try{let d=await api('/api/system/health');paint('groq',d.groq);paint('ollama',d.ollama)}catch(e){toast(e.message)}}function paint(p,d){let s=document.querySelector('#'+p+'Status');s.textContent=d.ok?'Đã kết nối':'Có lỗi';s.className='status '+(d.ok?'ok':'bad');document.querySelector('#'+p+'Info').textContent=d.ok?`Model: ${d.model||'sẵn sàng'}`:(d.error||'Không kết nối được')}document.querySelector('#checkAll').onclick=checkAll;document.querySelector('#checkGroq').onclick=async()=>paint('groq',await api('/api/system/test/groq',{method:'POST'}));document.querySelector('#checkOllama').onclick=async()=>paint('ollama',await api('/api/system/test/ollama',{method:'POST'}));document.querySelector('#provider').onchange=async e=>{await api('/api/system/provider',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:e.target.value})});document.querySelector('#providerPill').textContent='AI: '+(e.target.value==='groq'?'Groq':'Ollama');toast('Đã đổi AI provider')};document.querySelector('#sendChat').onclick=sendChat;
document.querySelector('#chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat()}};
function renderChatHistory(items){
  let l=document.querySelector('#chatLog'); if(!l)return;
  if(!items||!items.length){l.innerHTML='<div class="chat-msg ai">Xin chào. Tôi có thể giải thích dữ liệu, phân nhóm, khách hàng ảo và kết quả chiến dịch.</div>';return}
  l.innerHTML=items.map(m=>`<div class="chat-msg ${m.role==='user'?'user':'ai'}">${esc(m.content||'')}</div>`).join('');
  l.scrollTop=l.scrollHeight;
}
function updateChatMemoryStatus(count){
  let el=document.querySelector('#chatMemoryStatus');if(!el)return;
  count=Number(count||0);
  el.textContent=count>0?`Đang ghi nhớ ${count} thông tin bạn đã nói rõ.`:'Chưa có thông tin được ghi nhớ lâu dài.';
}
async function loadChatHistory(){
  try{let d=await api('/api/chat/history?limit=200');renderChatHistory(d.items||[]);updateChatMemoryStatus(d.memory_count||0)}
  catch(e){toast('Không tải được lịch sử hội thoại: '+e.message)}
}
async function clearChatHistoryUI(){
  if(!confirm('Xóa toàn bộ hội thoại và những thông tin Trợ lý đã ghi nhớ từ cuộc trò chuyện này?'))return;
  try{await api('/api/chat/history',{method:'DELETE'});renderChatHistory([]);updateChatMemoryStatus(0);toast('Đã xóa hội thoại và trí nhớ cuộc trò chuyện')}
  catch(e){toast('Không xóa được lịch sử hội thoại: '+e.message)}
}
if(document.querySelector('#clearChat'))document.querySelector('#clearChat').onclick=clearChatHistoryUI;
async function sendChat(){
  let i=document.querySelector('#chatInput'),t=i.value.trim();if(!t)return;i.value='';
  let l=document.querySelector('#chatLog');l.innerHTML+=`<div class="chat-msg user">${esc(t)}</div>`;l.scrollTop=l.scrollHeight;
  try{
    let d=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,provider:document.querySelector('#provider').value})});
    l.innerHTML+=`<div class="chat-msg ai">${esc(d.answer)}</div>`;updateChatMemoryStatus(d.memory_count||0);l.scrollTop=l.scrollHeight
  }catch(e){l.innerHTML+=`<div class="chat-msg ai">Không thể gọi AI: ${esc(e.message)}</div>`;l.scrollTop=l.scrollHeight}
}
async function loadHelp(){try{let d=await api('/api/help');document.querySelector('#helpList').innerHTML=d.sections.map(x=>`<div class="help-item"><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></div>`).join('')}catch{}}
document.querySelector('#generateTwins').onclick=async()=>{try{let n=+document.querySelector('#twinCount').value;let d=await api('/api/personas/generate/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count_per_segment:n})});pollTwinJob(d.job_id)}catch(e){toast(e.message)}};async function pollTwinJob(id){try{let d=await api('/api/personas/generate/'+id);document.querySelector('#twinProgressBar').style.width=d.progress+'%';document.querySelector('#twinProgressPercent').textContent=d.progress+'%';document.querySelector('#twinProgressText').textContent=d.status==='completed'?'Đã hoàn thành':'Đang tạo khách hàng ảo';document.querySelector('#twinProgressDetail').textContent=`Đã tạo ${d.created||0} / ${d.total||0} khách hàng ảo.`;if(d.status==='completed'){loadAllPersonas();toast('Đã tạo xong khách hàng ảo');return}if(d.status==='failed'){toast(d.error||'Tạo khách hàng ảo thất bại');return}setTimeout(()=>pollTwinJob(id),250)}catch(e){toast(e.message)}}document.querySelector('#runAB').onclick=async()=>{let campaigns=document.querySelector('#abCampaigns').value.split('\n').map(x=>x.trim()).filter(Boolean);if(campaigns.length<2){toast('Nhập ít nhất 2 phương án.');return}try{let d=await api('/api/advanced/ab',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({campaigns})});let box=document.querySelector('#abResult');box.className='notice success';box.textContent=d.results.map((x,i)=>`${i+1}. ${x.campaign}: conversion ${(x.conversion_rate*100).toFixed(1)}%, revenue ${Math.round(x.expected_revenue).toLocaleString()}`).join(' | ')}catch(e){let box=document.querySelector('#abResult');box.className='notice error';box.textContent=e.message}};document.querySelector('#runOpt').onclick=async()=>{try{let d=await api('/api/advanced/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({budget:+document.querySelector('#optBudget').value})});let box=document.querySelector('#optResult');box.className='notice success';box.textContent=d.best?`Đề xuất: ${d.best.campaign} — score ${(d.best.optimization_score*100).toFixed(1)}%`:'Không có kết quả'}catch(e){let box=document.querySelector('#optResult');box.className='notice error';box.textContent=e.message}};

/* === MARKETSIM_FRONTEND_CONNECTOR_FIX_V1 === */
// Chỉ nối giao diện vào các API backend ĐÃ TỒN TẠI.
// Không thay đổi thuật toán, Digital Twin, segmentation, simulation hay AI Learning backend.
let stagedSessionId = null;
let stagedLearningJobId = null;

function el(id){ return document.getElementById(id); }
function setHidden(id, hidden){ const x=el(id); if(x) x.classList.toggle('hidden', !!hidden); }
function setNotice(id, message, type=''){ const x=el(id); if(!x) return; x.textContent=message||''; x.className='notice'+(type?' '+type:''); }
const CANONICAL_FIELDS=['unmapped','customer_id','age','gender','job','location','total_spending','pain_point','personality','interest_keywords','last_purchase_date','order_count','average_order_value','discount_usage','product_category','channel','device','acquisition_source','review_text','monthly_income','signup_date','return_count','website_visits_30d','email_open_rate','cart_abandon_rate','satisfaction_score','loyalty_tier'];
const FRIENDLY_FIELD_LABELS={unmapped:'Chưa xác định',customer_id:'Mã khách hàng',age:'Tuổi',gender:'Giới tính',job:'Nghề nghiệp',location:'Khu vực',total_spending:'Tổng chi tiêu',pain_point:'Vấn đề / nhu cầu chính',personality:'Đặc điểm hành vi',interest_keywords:'Sở thích / mối quan tâm',last_purchase_date:'Lần mua gần nhất',order_count:'Số đơn hàng',average_order_value:'Giá trị đơn hàng trung bình',discount_usage:'Mức sử dụng giảm giá',product_category:'Nhóm sản phẩm',channel:'Kênh mua hàng',device:'Thiết bị',acquisition_source:'Nguồn tiếp cận',review_text:'Nội dung đánh giá',monthly_income:'Thu nhập theo tháng',signup_date:'Ngày bắt đầu',return_count:'Số lần hoàn trả',website_visits_30d:'Lượt truy cập 30 ngày',email_open_rate:'Tỷ lệ mở email',cart_abandon_rate:'Tỷ lệ bỏ giỏ hàng',satisfaction_score:'Mức hài lòng',loyalty_tier:'Mức độ gắn bó'};
const friendlyField=f=>FRIENDLY_FIELD_LABELS[f]||String(f||'').replaceAll('_',' ');
let currentStagedMapping=[];
function setWizardStep(step){
  for(let i=1;i<=5;i++){
    const x=el('wiz'+i); if(!x) continue;
    x.classList.toggle('active', i===step);
    x.classList.toggle('done', i<step);
  }
}
function pct(v){ const n=Number(v); return Number.isFinite(n)?Math.round(n*10)/10:0; }
function parseMaybeJson(v){ if(typeof v!=='string') return v||{}; try{return JSON.parse(v)}catch{return {}} }

function renderInspection(inspection){
  if(!inspection) return;
  setHidden('stagedPreview', false);
  const q=inspection.quality||{}, dims=q.dimensions||{}, issues=q.issues||[];
  const cards=el('stagedSummaryCards');
  if(cards) cards.innerHTML=`
    <div class="stat"><span>Khách hàng / dòng</span><b>${Number(inspection.rows||0).toLocaleString()}</b></div>
    <div class="stat"><span>Số cột</span><b>${Number(inspection.columns_count||0).toLocaleString()}</b></div>
    <div class="stat"><span>Chất lượng dữ liệu</span><b>${pct(q.score)} / 100</b><small>${esc(q.label||'')}</small></div>
    <div class="stat"><span>Vấn đề cần xem</span><b>${Number(issues.length).toLocaleString()}</b></div>`;
  if(el('qualityScore')) el('qualityScore').textContent=`${pct(q.score)} / 100`;
  if(el('qualityLabel')) el('qualityLabel').textContent=q.label||'Chưa đánh giá';
  const dim=el('qualityDimensions'); if(dim) dim.innerHTML=Object.entries({
    'Độ đầy đủ':dims.completeness,'Tính hợp lệ':dims.validity,'Tính nhất quán':dims.consistency,
    'Không trùng lặp':dims.uniqueness,'Độ mới dữ liệu':dims.freshness,'Độ chắc chắn schema':dims.schema_confidence
  }).map(([k,v])=>`<div class="quality-dim"><span>${esc(k)}</span><b>${pct(v)}%</b><div class="quality-meter"><i style="width:${Math.max(0,Math.min(100,Number(v)||0))}%"></i></div></div>`).join('');
  const issueBox=el('qualityIssues'); if(issueBox) issueBox.innerHTML=issues.length?issues.slice(0,20).map(x=>`<div class="quality-issue ${esc(x.severity||'warning')}"><b>${esc(x.column||'Toàn bộ file')}</b><span>${esc(x.message||'')}</span></div>`).join(''):'<div class="quality-ok">✓ Chưa phát hiện vấn đề nghiêm trọng ở bước kiểm tra tự động.</div>';
  if(el('stagedFileName')) el('stagedFileName').textContent=inspection.filename||'';
  const colBody=el('stagedColumnsTable')?.querySelector('tbody');
  if(colBody) colBody.innerHTML=(inspection.columns||[]).map(c=>`<tr>
    <td><b>${esc(c.name)}</b><small>${esc(c.semantic_type||c.dtype)} · tin cậy ${Math.round(Number(c.type_confidence||0)*100)}%</small></td>
    <td>${Number(c.non_null||0).toLocaleString()}</td>
    <td>${Number(c.null_count||0).toLocaleString()} (${pct(c.null_pct)}%)</td>
    <td>${Number(c.unique_count||0).toLocaleString()}</td>
    <td>${Number(c.invalid_count||0)?`<span class="status bad">${Number(c.invalid_count)} lỗi</span>`:'<span class="status ok">Hợp lệ</span>'}</td>
    <td>${esc(c.rule_mapping&&c.rule_mapping!=='unmapped'?c.rule_mapping:'Chưa nhận diện')}</td>
  </tr>`).join('');
  const sample=inspection.sample_rows||[], sampleTable=el('stagedSampleTable');
  if(sampleTable){const keys=sample.length?Object.keys(sample[0]):(inspection.columns||[]).map(x=>x.name);sampleTable.querySelector('thead').innerHTML='<tr>'+keys.map(k=>`<th>${esc(k)}</th>`).join('')+'</tr>';sampleTable.querySelector('tbody').innerHTML=sample.map(r=>'<tr>'+keys.map(k=>`<td>${esc(r[k])}</td>`).join('')+'</tr>').join('')||`<tr><td colspan="${Math.max(1,keys.length)}">Không có dòng mẫu.</td></tr>`;}
  const confirm=el('stagedConfirmInspect'); if(confirm) confirm.disabled=false;
  setWizardStep(2);
}

function renderMapping(mapping, missingRequired=[], extras={}){
  currentStagedMapping=mapping||[];
  setHidden('stagedMapping', false);
  const body=el('stagedMappingTable')?.querySelector('tbody');
  if(body) body.innerHTML=currentStagedMapping.map((m,i)=>{const ignored=m.source==='safe_ignore';const problem=!ignored&&(m.canonical_field==='unmapped'||Number(m.confidence||0)<.8);return `<tr class="${problem?'mapping-problem':''}">
    <td>${esc(m.source_column)}</td><td><select class="mapping-select" data-index="${i}">${CANONICAL_FIELDS.map(f=>`<option value="${esc(f)}" ${f===(m.canonical_field||'unmapped')?'selected':''}>${esc(friendlyField(f))}</option>`).join('')}</select></td>
    <td>${esc(m.confidence_display || Math.round(Number(m.confidence||0)*100)+'%')}</td>
    <td>${m.source==='company_memory'?'<span class="status ok">Đã nhớ</span>':m.source==='human_confirmed'?'<span class="status ok">Bạn xác nhận</span>':m.source==='safe_ignore'?'<span class="status">Bỏ qua an toàn</span>':esc(m.source||'—')}</td><td>${esc(m.reasoning||'')}</td>
  </tr>`}).join('');
  const mapped=new Set(currentStagedMapping.map(m=>m.canonical_field).filter(Boolean));
  const required=['age','job','pain_point','personality','interest_keywords'];
  const grid=el('stagedRequiredGrid'); if(grid) grid.innerHTML=required.map(f=>{const missing=(missingRequired||[]).includes(f)||!mapped.has(f);return `<div class="required-item ${missing?'missing':'ready'}"><b>${esc(friendlyField(f))}</b><span>${missing?'Chưa đủ dữ liệu — AI chỉ bổ sung khi có căn cứ':'Đã có dữ liệu và đã hiểu đúng cột'}</span></div>`}).join('');
  const dup=extras.duplicates||{}; if(el('duplicateSummary')) el('duplicateSummary').innerHTML=`<b>${Number(dup.exact||0)}</b> dòng trùng hoàn toàn · <b>${Number(dup.possible||0)}</b> cặp có khả năng cùng khách hàng`;
  const drift=extras.drift||{}; if(el('driftSummary')) el('driftSummary').innerHTML=!drift.available?'Chưa có dữ liệu lịch sử để so sánh.':((drift.alerts||[]).length?`<b>${drift.alerts.length}</b> thay đổi phân phối cần xem: `+(drift.alerts||[]).slice(0,5).map(x=>esc(x.field)).join(', '):'✓ Phân phối dataset mới chưa có thay đổi lớn so với lịch sử.');
  const start=el('stagedStartLearning'); if(start) start.disabled=false;
  setWizardStep(3);
}

async function saveManualMapping(){
  if(!stagedSessionId)return;
  const btn=el('saveMappingBtn'); if(btn){btn.disabled=true;btn.textContent='Đang lưu...';}
  try{
    const mappings=currentStagedMapping.map((m,i)=>({...m,canonical_field:document.querySelector(`.mapping-select[data-index="${i}"]`)?.value||m.canonical_field}));
    const d=await api(`/api/customers/inspect/${encodeURIComponent(stagedSessionId)}/mapping`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mappings})});
    renderMapping(d.mapping||[],d.missing_required_fields||[],{duplicates:d.duplicates||{},drift:d.drift||{}}); setNotice('stagedMsg',d.message||'Đã lưu mapping.','success');
  }catch(e){setNotice('stagedMsg','Không thể lưu mapping: '+e.message,'error');}
  finally{if(btn){btn.disabled=false;btn.textContent='Lưu cách hiểu các cột';}}
}

function renderAudit(audit, confirmed=false){
  audit=audit||{}; setHidden('stagedAudit', false);
  const ready=audit.digital_twin_readiness||{}, quality=audit.data_quality||{};
  const k=el('stagedAuditKpis'); if(k) k.innerHTML=`
    <div class="stat"><span>Dữ liệu gốc</span><b>${pct(audit.overall_real_data_pct)}%</b></div>
    <div class="stat"><span>Tính từ dữ liệu gốc</span><b>${pct(audit.overall_derived_real_pct)}%</b></div>
    <div class="stat"><span>AI bổ sung</span><b>${pct(audit.overall_ai_inferred_pct)}%</b></div>
    <div class="stat"><span>Còn thiếu</span><b>${pct(audit.overall_missing_pct)}%</b></div>`;
  const body=el('stagedAuditTable')?.querySelector('tbody'),coverage=audit.field_coverage||{};
  if(body) body.innerHTML=Object.entries(coverage).map(([field,x])=>`<tr><td>${esc(field)}</td><td>${pct(x.real_pct)}%</td><td>${pct(x.derived_real_pct)}%</td><td>${pct(x.ai_inferred_pct)}%</td><td>${pct(x.missing_pct)}%</td><td>${x.invalid>0?'<span class="status bad">Nguồn lỗi</span>':(x.missing>0?'<span class="status wait">Còn thiếu</span>':(x.ai_inferred>0?'<span class="status ready">AI bổ sung</span>':'<span class="status ok">Dữ liệu gốc</span>'))}</td></tr>`).join('');
  const learned=el('stagedLearnedList'),items=audit.learned_fields||audit.learned_summary||[];
  if(learned) learned.innerHTML=items.length?items.map(x=>`<div class="learned-item"><div><b>${esc(x.field)}</b><span class="status ${x.learned?'ready':'wait'}">${x.learned?'Đã học có bằng chứng':'AI nói: chưa biết'}</span></div><p>${esc(x.evidence||x.notes||'Không có bằng chứng bổ sung.')}</p><small>Độ chắc chắn: ${Math.round(Number(x.confidence||0)*100)}%${x.strategy?` · Cách xử lý: ${esc(x.strategy)}`:''}</small></div>`).join(''):'<div class="empty">Không có trường nào cần AI bổ sung.</div>';
  if(el('readinessOverall')) el('readinessOverall').textContent=`${pct(ready.overall)}%`;
  if(el('readinessStatus')){el('readinessStatus').textContent=ready.status==='READY'?'Sẵn sàng':ready.status==='CAUTION'?'Cần cân nhắc':'Chưa khuyến nghị';el('readinessStatus').className='status '+(ready.status==='READY'?'ok':ready.status==='CAUTION'?'wait':'bad');}
  const areas=el('readinessAreas');if(areas)areas.innerHTML=Object.entries(ready.areas||{}).map(([n,v])=>`<div class="readiness-row"><span>${esc(n)}</span><div class="quality-meter"><i style="width:${Number(v)||0}%"></i></div><b>${pct(v)}%</b></div>`).join('');
  if(el('readinessMessage'))el('readinessMessage').textContent=ready.message||'';
  if(el('stagedAuditExplain')) el('stagedAuditExplain').textContent=`Dữ liệu gốc ${pct(audit.overall_real_data_pct)}% · Tính từ dữ liệu gốc ${pct(audit.overall_derived_real_pct)}% · AI bổ sung ${pct(audit.overall_ai_inferred_pct)}% · Còn thiếu ${pct(audit.overall_missing_pct)}%. ${Number(audit.invalid_cells||0)} ô không hợp lệ đã được tách riêng trước khi AI phân tích.`;
  const confirm=el('stagedConfirmLearning'); if(confirm){confirm.disabled=!!confirmed;confirm.textContent=confirmed?'Đã xác nhận dữ liệu':'5. Xác nhận & cho phép tạo Digital Twin';}
  if(el('auditReliability'))el('auditReliability').textContent=`Quality ${pct(quality.score||audit.overall_real_data_pct)} / 100`;
  if(el('auditDetail'))el('auditDetail').textContent=`Dữ liệu gốc ${pct(audit.overall_real_data_pct)}% · Dẫn xuất ${pct(audit.overall_derived_real_pct)}% · AI ${pct(audit.overall_ai_inferred_pct)}% · Thiếu ${pct(audit.overall_missing_pct)}%.`;
  if(el('stagedReadyBadge')){el('stagedReadyBadge').textContent=confirmed?'Đã xác nhận':(ready.status==='READY'?'Sẵn sàng — chờ xác nhận':'Cần kiểm tra');el('stagedReadyBadge').className='status '+(confirmed||ready.status==='READY'?'ready':'wait');}
  setWizardStep(5);
}

async function loadStagedState(){
  try{
    const d=await api('/api/customers/learning/audit/latest');
    if(d.session_id) stagedSessionId=d.session_id;
    if(d.audit && Object.keys(d.audit).length) renderAudit(d.audit, !!d.confirmed);
  }catch(e){ /* không có audit cũ không phải lỗi fatal */ }
}

async function inspectSelectedDataset(){
  const file=el('stagedDatasetFile')?.files?.[0];
  if(!file){ setNotice('stagedMsg','Hãy chọn file CSV/XLSX/XLS trước.','error'); return; }
  const btn=el('stagedInspectBtn'); if(btn){btn.disabled=true;btn.textContent='Đang đọc dữ liệu...';}
  setNotice('stagedMsg',`Đang đọc ${file.name}. Bước này chưa gọi AI...`,'');
  try{
    const fd=new FormData(); fd.append('file',file);
    const d=await api('/api/customers/inspect',{method:'POST',body:fd});
    stagedSessionId=d.session_id;
    renderInspection(d.inspection);
    setNotice('stagedMsg',d.message||'Đã đọc dữ liệu. Hãy kiểm tra preview trước khi xác nhận.','success');
  }catch(e){ setNotice('stagedMsg','Không thể đọc dữ liệu: '+e.message,'error'); }
  finally{ if(btn){btn.disabled=false;btn.textContent='1. Đọc & kiểm tra dữ liệu';} }
}

async function confirmInspectionAndMap(){
  if(!stagedSessionId){ setNotice('stagedMsg','Chưa có phiên dữ liệu. Hãy bấm Đọc & kiểm tra dữ liệu trước.','error'); return; }
  const btn=el('stagedConfirmInspect'); if(btn){btn.disabled=true;btn.textContent='Đang xác định ý nghĩa cột...';}
  setNotice('stagedMsg','Đã xác nhận dữ liệu mẫu. Hệ thống đang xác định ý nghĩa từng cột; AI chỉ hỗ trợ các cột còn chưa rõ...','');
  try{
    const d=await api(`/api/customers/inspect/${encodeURIComponent(stagedSessionId)}/confirm`,{method:'POST'});
    renderMapping(d.mapping||[], d.missing_required_fields||[], {duplicates:d.duplicates||{},drift:d.drift||{}});
    setNotice('stagedMsg',d.message||'Đã xác định xong ý nghĩa các cột.','success');
  }catch(e){ setNotice('stagedMsg','Không thể xác định ý nghĩa các cột: '+e.message,'error'); if(btn)btn.disabled=false; }
  finally{ if(btn)btn.textContent='3. Xác nhận cột & tiếp tục'; }
}

async function startStagedLearning(){
  if(!stagedSessionId){ setNotice('stagedMsg','Không tìm thấy phiên dữ liệu để AI Learning.','error'); return; }
  const btn=el('stagedStartLearning'); if(btn){btn.disabled=true;btn.textContent='Đang khởi động AI Learning...';}
  try{
    const d=await api(`/api/customers/learning/start/${encodeURIComponent(stagedSessionId)}`,{method:'POST'});
    stagedLearningJobId=d.job_id;
    setHidden('stagedLearning', false); setWizardStep(3);
    pollStagedLearning();
  }catch(e){ setNotice('stagedMsg','Không thể bắt đầu AI Learning: '+e.message,'error'); if(btn){btn.disabled=false;btn.textContent='4. Bắt đầu AI Learning';} }
}

async function pollStagedLearning(){
  if(!stagedLearningJobId) return;
  try{
    const d=await api(`/api/customers/learning/status/${encodeURIComponent(stagedLearningJobId)}`);
    const p=pct(d.progress);
    if(el('stagedLearningBar')) el('stagedLearningBar').style.width=p+'%';
    if(el('stagedLearningPercent')) el('stagedLearningPercent').textContent=p+'%';
    if(el('stagedLearningText')) el('stagedLearningText').textContent=d.status==='completed'?'AI Learning hoàn thành':(d.step||'AI đang học dữ liệu');
    if(el('stagedLearningDetail')) el('stagedLearningDetail').textContent=d.step||'AI đang học từ dữ liệu real đã xác nhận.';
    if(d.status==='completed'){
      renderAudit(d.audit||{}, false);
      if(el('stagedStartLearning')){el('stagedStartLearning').textContent='AI Learning đã hoàn thành';el('stagedStartLearning').disabled=true;}
      loadDatasetHistory();
      return;
    }
    if(d.status==='failed'){ setNotice('stagedMsg','AI Learning thất bại: '+(d.error||'Không rõ lỗi'),'error'); if(el('stagedStartLearning')){el('stagedStartLearning').disabled=false;el('stagedStartLearning').textContent='3. Bắt đầu AI Learning';} return; }
    setTimeout(pollStagedLearning,700);
  }catch(e){ setNotice('stagedMsg','Không đọc được tiến trình AI Learning: '+e.message,'error'); }
}

async function confirmStagedLearning(){
  const btn=el('stagedConfirmLearning'); if(btn){btn.disabled=true;btn.textContent='Đang xác nhận...';}
  try{
    let d;
    if(stagedSessionId){
      try{ d=await api(`/api/customers/learning/confirm/${encodeURIComponent(stagedSessionId)}`,{method:'POST'}); }
      catch(e){ d=await api('/api/customers/learning/confirm-latest',{method:'POST'}); }
    }else d=await api('/api/customers/learning/confirm-latest',{method:'POST'});
    setNotice('stagedMsg',d.message||'Đã xác nhận AI Learning. Digital Twin đã được mở.','success');
    if(el('stagedReadyBadge')){el('stagedReadyBadge').textContent='Sẵn sàng tạo Digital Twin';el('stagedReadyBadge').className='status ready';}
    if(btn){btn.textContent='Đã xác nhận AI Learning';btn.disabled=true;}
    loadDatasetHistory(); loadCustomers(); refreshStats();
  }catch(e){ setNotice('stagedMsg','Không thể xác nhận AI Learning: '+e.message,'error'); if(btn){btn.disabled=false;btn.textContent='5. Xác nhận & cho phép tạo Digital Twin';} }
}

const FIELD_LABELS={
  age:'Tuổi',gender:'Giới tính',job:'Nghề nghiệp',location:'Khu vực',total_spending:'Tổng chi tiêu',order_count:'Số đơn',
  average_order_value:'Giá trị đơn hàng TB gốc',average_order_value_final:'Giá trị đơn hàng TB',discount_usage:'Dùng khuyến mãi',last_purchase_date:'Lần mua gần nhất',
  product_category:'Danh mục',channel:'Kênh ưu tiên',device:'Thiết bị',acquisition_source:'Nguồn tiếp cận',review_text:'Đánh giá',
  monthly_income:'Thu nhập/tháng',signup_date:'Ngày tham gia',return_count:'Số đơn hoàn',website_visits_30d:'Truy cập web 30 ngày',
  email_open_rate:'Tỷ lệ mở email',cart_abandon_rate:'Tỷ lệ bỏ giỏ',satisfaction_score:'Điểm hài lòng',loyalty_tier:'Hạng thành viên',
  recency_days:'Số ngày từ lần mua gần nhất',purchase_frequency_per_month:'Tần suất mua/tháng',return_rate:'Tỷ lệ hoàn',discount_dependency:'Mức phụ thuộc khuyến mãi',
  engagement_score:'Mức tương tác',customer_value_score:'Giá trị khách hàng',behavioral_loyalty_index:'Mức độ gắn bó',churn_signal_score:'Nguy cơ rời bỏ'
};
function fieldLabel(k){return FIELD_LABELS[k]||String(k||'').replaceAll('_',' ')}
function sourceLabelFriendly(k){return ({REAL:'Dữ liệu gốc',DERIVED_REAL:'Tính từ dữ liệu gốc',AI_INFERRED:'AI bổ sung',MISSING:'Còn thiếu',MISSING_SOURCE:'Nguồn không có',MISSING_INVALID:'Nguồn không hợp lệ',NOT_APPLICABLE:'Không áp dụng',original:'Dữ liệu gốc',ai_inferred:'AI bổ sung',default_fallback:'Giá trị dự phòng'})[String(k||'')]||String(k||'').replaceAll('_',' ')}
function qualityTone(status){status=String(status||'').toUpperCase();return status==='READY'||status==='HIGH'?'good':status==='CAUTION'||status==='MEDIUM'?'warn':'bad'}
function renderBarRow(label,value){let v=Math.max(0,Math.min(100,Number(value||0)));return `<div class="coverage-item"><div class="coverage-row"><span>${esc(label)}</span><b>${pct(v)}%</b></div><div class="mini-bar"><i style="width:${v}%"></i></div></div>`}
function moneyCompact(v){if(v==null||Number.isNaN(Number(v)))return '—';let n=Number(v);if(Math.abs(n)>=1e9)return (n/1e9).toFixed(1)+' tỷ';if(Math.abs(n)>=1e6)return (n/1e6).toFixed(1)+' triệu';if(Math.abs(n)>=1e3)return Math.round(n/1e3).toLocaleString()+' nghìn';return Math.round(n).toLocaleString()}

async function loadAnalysis(){
  const msg=el('analysisMsg');
  try{
    const d=await api('/api/analysis'), i=d.intelligence||{}, seg=d.segmentation||{}, audit=d.audit||{}, q=i.quality||{}, k=i.kpis||{};
    const hero=el('intelligenceQuality');
    if(hero){
      const tone=qualityTone(q.status);hero.className='quality-hero '+tone;
      hero.innerHTML=`<div><span class="eyebrow">MỨC SẴN SÀNG PHÂN TÍCH</span><div class="quality-score">${pct(q.score||0)}<small>/100</small></div></div><div class="quality-copy"><h3>${q.status==='READY'?'Dữ liệu hành vi đủ tốt để phân nhóm':q.status==='CAUTION'?'Có thể phân tích nhưng còn vùng dữ liệu yếu':'Chưa nên phụ thuộc vào phân nhóm để ra quyết định'}</h3><p>${esc((q.warnings||[])[0]||'MarketSim ưu tiên dữ liệu thật và các chỉ số tính bằng công thức trước khi phân nhóm.')}</p></div>`;
    }
    const cards=el('analysisCards');
    if(cards) cards.innerHTML=`
      <div class="stat"><span>Khách hàng</span><b>${Number(i.customers||seg.count||0).toLocaleString()}</b><small>Dữ liệu đã kiểm tra</small></div>
      <div class="stat"><span>Độ tin cậy nguồn</span><b>${pct(i.avg_reliability_pct)}%</b><small>Ưu tiên dữ liệu gốc và dữ liệu tính trực tiếp</small></div>
      <div class="stat"><span>Đủ dữ liệu hành vi mua hàng</span><b>${pct(i.rfm_available_pct)}%</b><small>Lần mua gần nhất + số lần mua + tổng chi tiêu</small></div>
      <div class="stat"><span>Số phân khúc</span><b>${Number(seg.n_clusters||0)}</b><small>${seg.quality?.status?`Chất lượng: ${esc(seg.quality.status)}`:'Chưa đánh giá'}</small></div>`;

    const kpi=el('analysisKpis');
    if(kpi) kpi.innerHTML=[
      ['Số ngày từ lần mua gần nhất (điển hình)',k.median_recency_days==null?'—':`${Math.round(k.median_recency_days)} ngày`],
      ['Số đơn hàng điển hình',k.median_order_count==null?'—':Number(k.median_order_count).toFixed(1)],
      ['Tổng chi tiêu điển hình',moneyCompact(k.median_total_spending)],
      ['Giá trị đơn hàng TB điển hình',moneyCompact(k.median_aov)],
      ['Mức tương tác trung bình',k.mean_engagement_score==null?'—':`${Math.round(Number(k.mean_engagement_score)*100)}%`],
      ['Mức độ gắn bó trung bình',k.mean_loyalty_index==null?'—':`${Math.round(Number(k.mean_loyalty_index)*100)}%`],
      ['Khách hàng giá trị cao',Number(k.high_value_customers||0).toLocaleString()+' KH'],
      ['Nguy cơ rời bỏ cao',Number(k.high_churn_signal_customers||0).toLocaleString()+' KH'],
    ].map(([a,b])=>`<div class="metric-line"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('');

    const sources=el('analysisSources');
    if(sources) sources.innerHTML=Object.entries(i.source_breakdown||{}).sort((a,b)=>b[1]-a[1]).map(([name,v])=>renderBarRow(sourceLabelFriendly(name),v)).join('')||'<p class="muted">Bộ dữ liệu cũ chưa lưu chi tiết nguồn hình thành từng giá trị.</p>';
    const coverage=el('analysisCoverage');
    if(coverage) coverage.innerHTML=Object.entries(i.fields_with_data||{}).filter(([,v])=>Number(v)>0).sort((a,b)=>b[1]-a[1]).map(([k,v])=>renderBarRow(fieldLabel(k),v)).join('')||'<p class="muted">Chưa có dữ liệu để tính độ phủ.</p>';
    const derived=el('analysisDerived');
    if(derived) derived.innerHTML=Object.entries(i.derived_metrics||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>renderBarRow(fieldLabel(k),v)).join('')||'<p class="muted">Chưa đủ trường nguồn để tính feature dẫn xuất.</p>';
    const rfm=el('analysisRfm');
    if(rfm) rfm.innerHTML=Object.entries(i.segments||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="metric-line"><span>${esc(k)}</span><b>${Number(v||0).toLocaleString()}</b></div>`).join('')||'<p class="muted">Chưa đủ dữ liệu RFM.</p>';
    const warnings=el('analysisWarnings');
    if(warnings) warnings.innerHTML=(q.warnings||[]).map(x=>`<div class="quality-warning">${esc(x)}</div>`).join('')||'<div class="quality-ok">Không có cảnh báo Intelligence quan trọng.</div>';
    const cat=el('featureCatalog');
    if(cat) cat.innerHTML=Object.entries(i.feature_catalog||{}).map(([k,v])=>`<div class="feature-formula"><b>${esc(fieldLabel(k))}</b><span>${esc(v)}</span></div>`).join('');
    if(msg){ msg.textContent=d.learning_confirmed?'Đang phân tích từ bộ dữ liệu đã xác nhận. Các điểm hành vi chỉ dùng để hỗ trợ so sánh, không phải xác suất mua hàng thực tế.':'Bộ dữ liệu hiện tại chưa được xác nhận hoàn toàn.'; msg.className='notice '+(d.learning_confirmed?'success':''); }
    if(Object.keys(audit).length && el('auditReliability')) el('auditReliability').textContent=`Dữ liệu gốc ${pct(audit.overall_real_data_pct)}%`;
  }catch(e){ if(msg){msg.textContent='Không thể tải phân tích: '+e.message;msg.className='notice error';} }
}

function renderSegmentQuality(q){
  const hero=el('segmentQuality'), metrics=el('segmentQualityMetrics'), warnings=el('segmentWarnings'), features=el('segmentFeatureGroups'), candidates=el('segmentKCandidates');
  if(!q||!Object.keys(q).length){
    if(hero){hero.className='quality-hero warn';hero.innerHTML='<div class="quality-copy"><h3>Bộ dữ liệu cũ chưa có đánh giá chất lượng phân nhóm</h3><p>Hãy chạy lại bước AI phân tích dữ liệu để MarketSim lưu đầy đủ kết quả kiểm tra.</p></div>';}
    if(metrics)metrics.innerHTML='';if(warnings)warnings.innerHTML='';if(features)features.innerHTML='';if(candidates)candidates.innerHTML='';return;
  }
  const tone=qualityTone(q.status);
  if(hero){hero.className='quality-hero '+tone;hero.innerHTML=`<div><span class="eyebrow">CHẤT LƯỢNG PHÂN NHÓM</span><div class="quality-score">${pct(q.score||0)}<small>/100</small></div></div><div class="quality-copy"><h3>${esc(q.interpretation||'Đã đánh giá chất lượng phân nhóm')}</h3><p>Độ chắc chắn trung bình của từng khách hàng: <b>${pct(q.avg_customer_confidence||0)}%</b>. ${Number(q.low_confidence_customers||0).toLocaleString()} khách hàng có độ chắc chắn rất thấp.</p></div>`;}
  if(metrics)metrics.innerHTML=`
    <div class="stat"><span>Mức tách biệt giữa các nhóm</span><b>${q.silhouette==null?'—':Number(q.silhouette).toFixed(3)}</b><small>Càng cao, các nhóm càng khác biệt rõ</small></div>
    <div class="stat"><span>Độ ổn định khi chạy lại</span><b>${q.stability==null?'—':pct(Number(q.stability)*100)+'%'}</b><small>Chạy lại vẫn cho kết quả tương tự?</small></div>
    <div class="stat"><span>Nhóm nhỏ nhất</span><b>${pct(q.balance?.min_pct||0)}%</b><small>Tránh tạo nhóm quá ít khách hàng</small></div>
    <div class="stat"><span>Chất lượng thông tin phân nhóm</span><b>${pct(q.feature_quality_avg||0)}%</b><small>${Number(q.selected_feature_count||0)} thông tin được dùng</small></div>`;
  if(warnings)warnings.innerHTML=(q.warnings||[]).map(x=>`<div class="quality-warning">${esc(x)}</div>`).join('')||'<div class="quality-ok">Không phát hiện cảnh báo phân nhóm quan trọng.</div>';
  const selected=q.selected_features||{};
  if(features)features.innerHTML=['numeric','categorical','text'].map(type=>`<div class="feature-group"><b>${type==='numeric'?'Số liệu':type==='categorical'?'Phân loại':'Văn bản'}</b><div>${(selected[type]||[]).map(x=>`<span class="feature-chip">${esc(fieldLabel(x))}</span>`).join('')||'<span class="muted">Không dùng</span>'}</div></div>`).join('');
  if(candidates)candidates.innerHTML=(q.k_candidates||[]).map(x=>`<div class="k-candidate"><b>${esc(x.k)} nhóm</b><span>Mức tách biệt ${Number(x.silhouette||0).toFixed(3)}</span><small>Nhóm nhỏ nhất ${pct(x.balance?.min_pct||0)}%</small></div>`).join('')||'<p class="muted">Số nhóm đã được chọn sẵn hoặc bộ dữ liệu quá nhỏ nên hệ thống không cần thử nhiều phương án.</p>';
}

async function loadSegments(){
  const box=el('segmentCards'); if(!box) return;
  try{
    const d=await api('/api/segments'), rows=d.items||[], q=d.quality||{}; renderSegmentQuality(q);
    if(!rows.length){ box.innerHTML='<div class="card" style="padding:20px">Chưa có kết quả phân nhóm. Hãy hoàn tất AI Learning trước.</div>'; return; }
    const grouped={};
    rows.forEach(r=>{
      const key=String(r.segment_id??0), profile=parseMaybeJson(r.profile_json);
      if(!grouped[key]) grouped[key]={count:0,name:r.segment_name||`Phân khúc ${key}`,sil:r.silhouette_score,profile,conf:[]};
      grouped[key].count++; if(r.segment_confidence!=null)grouped[key].conf.push(Number(r.segment_confidence));
    });
    box.innerHTML=Object.entries(grouped).sort((a,b)=>Number(a[0])-Number(b[0])).map(([id,g])=>{
      const p=g.profile||{}, avg=g.conf.length?g.conf.reduce((a,b)=>a+b,0)/g.conf.length:Number(p.avg_segment_confidence||0);
      const diffs=(p.differentiators||[]).slice(0,3);
      return `<div class="card segment-card-v2">
        <div class="segment-card-top"><span class="eyebrow">PHÂN KHÚC ${Number(id)+1}</span><span class="confidence-pill">${Math.round(avg*100)}% chắc chắn</span></div>
        <h3>${esc(g.name)}</h3><div class="segment-pop"><b>${g.count.toLocaleString()}</b><span>khách hàng · ${pct(p.share_pct||0)}%</span></div>
        <p class="segment-explain">${esc(p.explanation||'Nhóm được tạo từ các thông tin khách hàng có độ tin cậy đủ cao.')}</p>
        <div class="segment-diffs">${diffs.map(x=>`<span>${esc(x.type==='numeric'?`${fieldLabel(x.field)} ${x.direction==='higher'?'↑':'↓'}`:`${fieldLabel(x.field)}: ${x.value}`)}</span>`).join('')}</div>
        <div class="segment-meta"><span>RFM: <b>${esc(p.top_rfm_segment||'—')}</b></span><span>Danh mục: <b>${esc(p.top_category||'—')}</b></span><span>Nghề: <b>${esc(p.top_job||'—')}</b></span></div>
      </div>`;
    }).join('');
  }catch(e){ box.innerHTML=`<div class="card" style="padding:20px">Không thể tải phân khúc: ${esc(e.message)}</div>`; }
}

async function loadAllPersonas(){
  const list=el('personaList'), empty=el('personaEmpty'); if(!list) return;
  try{
    const d=await api('/api/personas?limit=5000'), items=d.items||[];
    if(empty) empty.classList.toggle('hidden', items.length>0);
    list.innerHTML=items.map(t=>`<div class="persona"><b>${esc(t.twin_id||t.name||'Khách hàng ảo')}</b><small>
      Phân khúc ${esc(t.segment_id??'—')} · Tuổi ${esc(t.age??'—')} · ${esc(t.location||'')}<br>
      Nghề: ${esc(t.job||'—')}<br>Sở thích: ${esc(t.interest_keywords||t.interests||'—')}<br>
      Độ chắc chắn: ${Math.round(Number(t.confidence||0)*100)}%
    </small></div>`).join('');
  }catch(e){ if(empty){empty.textContent='Không thể tải danh sách khách hàng ảo: '+e.message;empty.classList.remove('hidden');} }
}

function trendScore(value){if(value===null||value===undefined||value==='')return '—';const n=Number(value);return Number.isFinite(n)?n.toFixed(n%1?1:0):'—'}
function renderTrends(items, message='', source=''){
  const body=el('trendTable')?.querySelector('tbody');
  if(body) body.innerHTML=(items||[]).map(r=>`<tr>
    <td>${esc(r.keyword??'—')}${r.search_volume?`<small class="trend-volume">Khoảng ${esc(r.search_volume)} lượt tìm kiếm</small>`:''}</td>
    <td>${trendScore(r.trend_score)}</td>
    <td>${trendScore(r.latest_score)}</td>
    <td>${trendScore(r.peak_score)}</td>
  </tr>`).join('') || '<tr><td colspan="4">Google Trends chưa trả dữ liệu. Xem thông báo phía trên để biết nguyên nhân.</td></tr>';
  if(el('trendStatus')) el('trendStatus').textContent=[source,message].filter(Boolean).join(' · ') || `${(items||[]).length} xu hướng được cập nhật`;
}

async function collectPytrends(){
  const btn=el('collectTrends'), msg=el('analysisMsg'); if(btn){btn.disabled=true;btn.textContent='Đang lấy xu hướng tìm kiếm...';}
  try{
    const d=await api('/api/trends/collect',{method:'POST'}); renderTrends(d.items||[], d.message||d.error||'Hoàn thành', d.source||'');
    const fallback=['rss_fallback','stale_cache','partial'].includes(d.status);
    if(msg){msg.textContent=d.ok?(d.message||'Đã cập nhật Google Trends.'):(d.error||d.message||'Chưa nhận được dữ liệu xu hướng.');msg.className='notice '+(d.ok?(fallback?'warning':'success'):'error');}
  }catch(e){ if(msg){msg.textContent='Pytrends lỗi: '+e.message;msg.className='notice error';} }
  finally{ if(btn){btn.disabled=false;btn.textContent='Lấy xu hướng tìm kiếm';} }
}

// Gắn các nút workflow hiện có vào API backend hiện hữu.
if(el('stagedInspectBtn')) el('stagedInspectBtn').onclick=inspectSelectedDataset;
if(el('stagedConfirmInspect')) el('stagedConfirmInspect').onclick=confirmInspectionAndMap;
if(el('saveMappingBtn')) el('saveMappingBtn').onclick=saveManualMapping;
if(el('stagedStartLearning')) el('stagedStartLearning').onclick=startStagedLearning;
if(el('stagedConfirmLearning')) el('stagedConfirmLearning').onclick=confirmStagedLearning;
if(el('collectTrends')) el('collectTrends').onclick=collectPytrends;

// File gốc có hàm init nhưng chưa gọi. Gọi một lần sau khi tất cả connector đã được khai báo.
init().catch(e=>{ console.error('MarketSim init error',e); toast('Khởi tạo giao diện lỗi: '+e.message); });
/* === END MARKETSIM_FRONTEND_CONNECTOR_FIX_V1 === */



// Additive AI Learning History UI. Existing customer/AI logic is untouched.
let learningHistoryItems=[];
function learningHistoryChecked(){return [...document.querySelectorAll('.learning-history-check:checked')].map(x=>Number(x.value)).filter(Boolean)}
function updateLearningHistoryDeleteButton(){const b=document.querySelector('#deleteSelectedLearning');if(b)b.disabled=learningHistoryChecked().length===0}
function learningFieldSummary(details){
  const items=details?.learned_fields||details?.learned_summary||[];
  if(!items.length)return '<span class="muted">Bản ghi cũ chưa lưu chi tiết từng trường.</span>';
  return items.map(x=>`<div class="history-field"><b>${esc(x.field||'')}</b><span>${x.learned?'Đã phân tích':'Chưa đủ căn cứ'} · Độ chắc chắn ${Math.round(Number(x.confidence||0)*100)}%${x.strategy?` · ${esc(x.strategy)}`:''}</span>${x.evidence?`<small>${esc(x.evidence)}</small>`:''}</div>`).join('');
}
function renderLearningHistory(items){
  learningHistoryItems=items||[]; const list=document.querySelector('#learningHistoryList'); if(!list)return;
  const count=document.querySelector('#learningHistoryCount'); if(count)count.textContent=`${learningHistoryItems.length} lần học`;
  if(!learningHistoryItems.length){list.innerHTML='<div class="empty">Chưa có lịch sử AI Learning.</div>';updateLearningHistoryDeleteButton();return;}
  list.innerHTML=learningHistoryItems.map(x=>`<article class="learning-history-item"><div class="history-item-head"><label class="history-check"><input class="learning-history-check" type="checkbox" value="${Number(x.upload_id)}"><span><b>${esc(x.upload_name||('Dataset #'+x.upload_id))}</b><small>${esc(x.learned_at||x.uploaded_at||'')} · ${Number(x.total_records||0).toLocaleString()} bản ghi</small></span></label><div class="history-badges"><span class="status ${x.confirmed?'ok':'wait'}">${x.confirmed?'Đã xác nhận':'Chưa xác nhận'}</span><span class="status">REAL ${Number(x.real_data_pct||0).toFixed(1)}%</span></div></div><details><summary>Xem AI đã học được gì</summary><div class="history-details"><div class="coverage-row"><span>Nguồn</span><b>${esc(x.source||'')}</b></div><div class="coverage-row"><span>Số cột</span><b>${(x.columns||[]).length}</b></div><div class="coverage-row"><span>Thời điểm xác nhận</span><b>${esc(x.confirmed_at||'—')}</b></div><div class="history-field-list">${learningFieldSummary(x.learning_details||{})}</div></div></details></article>`).join('');
  document.querySelectorAll('.learning-history-check').forEach(x=>x.onchange=updateLearningHistoryDeleteButton); updateLearningHistoryDeleteButton();
}
async function loadLearningHistory(){
  const n=document.querySelector('#learningHistoryNotice'); if(n){n.className='notice hidden';n.textContent=''}
  try{const d=await api('/api/customers/learning/history');renderLearningHistory(d.items||[])}catch(e){if(n){n.textContent='Không tải được lịch sử học AI: '+e.message;n.className='notice error'}}
}
async function deleteSelectedLearningHistory(){
  const ids=learningHistoryChecked(); if(!ids.length)return;
  const names=learningHistoryItems.filter(x=>ids.includes(Number(x.upload_id))).map(x=>x.upload_name).filter(Boolean);
  if(!confirm(`Xóa ${ids.length} nguồn AI Learning đã chọn?\n\n${names.slice(0,6).join('\n')}\n\nCác nguồn này sẽ bị loại khỏi knowledge base tích lũy. Lịch sử chiến dịch/mô phỏng không bị xóa.`))return;
  const b=document.querySelector('#deleteSelectedLearning'); if(b){b.disabled=true;b.textContent='Đang xóa...'}
  const errors=[]; for(const id of ids){try{await api('/api/customers/learning/history/'+id,{method:'DELETE'})}catch(e){errors.push(`#${id}: ${e.message}`)}}
  if(b)b.textContent='Xóa dữ liệu đã chọn'; const n=document.querySelector('#learningHistoryNotice');
  if(n){n.textContent=errors.length?`Đã xử lý, nhưng có ${errors.length} lỗi: ${errors.join(' | ')}`:`Đã xóa ${ids.length} nguồn học AI. Các lần học sau sẽ không dùng những dữ liệu này.`;n.className='notice '+(errors.length?'error':'success')}
  const all=document.querySelector('#selectAllLearningHistory'); if(all)all.checked=false; await loadLearningHistory(); try{await loadDatasetHistory();await refreshStats()}catch{}
}
if(document.querySelector('#refreshLearningHistory'))document.querySelector('#refreshLearningHistory').onclick=loadLearningHistory;
if(document.querySelector('#deleteSelectedLearning'))document.querySelector('#deleteSelectedLearning').onclick=deleteSelectedLearningHistory;
if(document.querySelector('#selectAllLearningHistory'))document.querySelector('#selectAllLearningHistory').onchange=e=>{document.querySelectorAll('.learning-history-check').forEach(x=>x.checked=e.target.checked);updateLearningHistoryDeleteButton()};

// Click-to-inspect dataset learning details in the account data warehouse.
// Function declarations are intentionally additive so older deployments keep
// the separate AI Learning History page while the customer-data page gains a
// direct, accessible drill-down.
var selectedDatasetId;

function datasetLearningState(dataset){
  if(dataset.learning_confirmed||dataset.learning_state==='confirmed')return {label:'Đã xác nhận',tone:'ready'};
  if(dataset.has_audit||dataset.learning_state==='awaiting_confirmation')return {label:'Chờ xác nhận audit',tone:'wait'};
  return {label:'Chưa có kết quả AI',tone:'pending'};
}

function datasetStrategyLabel(value){
  return ({observed_distribution:'Phân phối quan sát',observed_categories:'Nhóm giá trị quan sát',not_enough_evidence:'Chưa đủ bằng chứng'})[String(value||'')]||String(value||'').replaceAll('_',' ');
}

function datasetCandidateLabels(values){
  const list=Array.isArray(values)?values:(values==null?[]:[values]);
  return list.map(value=>value&&typeof value==='object'?value.value:value).filter(value=>value!=null&&String(value).trim()).map(value=>String(value).trim()).slice(0,8);
}

function closeDatasetLearningDetail(){
  selectedDatasetId=undefined;
  document.querySelectorAll('.dataset-select').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false')});
  const panel=document.querySelector('#datasetLearningPanel');if(panel)panel.classList.add('hidden');
}

function renderDatasetLearningDetail(dataset){
  const title=document.querySelector('#datasetLearningTitle'),meta=document.querySelector('#datasetLearningMeta'),body=document.querySelector('#datasetLearningBody');
  if(!title||!meta||!body)return;
  const state=datasetLearningState(dataset),audit=dataset.audit||{};
  title.textContent=dataset.name||`Dataset #${dataset.id}`;
  meta.textContent=`${Number(dataset.records||0).toLocaleString()} bản ghi · ${Number((dataset.columns||[]).length).toLocaleString()} cột · Tải lên ${dataset.uploaded_at||'—'}`;
  if(!dataset.has_audit){
    body.innerHTML=`<div class="dataset-learning-empty"><span class="status pending">${esc(state.label)}</span><h4>AI chưa có báo cáo học cho bộ dữ liệu này</h4><p>Phiên AI Learning có thể chưa được chạy, đang xử lý hoặc đã dừng trước khi lưu audit. Bộ dữ liệu này chưa được đưa vào nguồn học tích lũy.</p><div class="dataset-learning-basic"><div><span>Số bản ghi khai báo</span><b>${Number(dataset.records||0).toLocaleString()}</b></div><div><span>Khách hàng chuẩn hóa đã lưu</span><b>${Number(dataset.canonical_customers||0).toLocaleString()}</b></div><div><span>Số cột</span><b>${Number((dataset.columns||[]).length).toLocaleString()}</b></div></div></div>`;
    return;
  }
  const learned=audit.learned_fields||audit.learned_summary||[],coverage=audit.field_coverage||{};
  const learnedCount=learned.filter(item=>item&&item.learned).length;
  const provider=String(audit.learning_provider||'').toUpperCase();
  const fieldCards=learned.length?learned.map(item=>{
    const candidates=datasetCandidateLabels(item.candidate_values);
    return `<article class="dataset-learned-field ${item.learned?'learned':'insufficient'}"><div><b>${esc(fieldLabel(item.field||''))}</b><span class="status ${item.learned?'ready':'wait'}">${item.learned?'Đã học':'Chưa đủ căn cứ'}</span></div><p>${esc(item.evidence||item.notes||'Không có mô tả bằng chứng.')}</p><small>Độ chắc chắn ${Math.round(Number(item.confidence||0)*100)}%${item.strategy?` · ${esc(datasetStrategyLabel(item.strategy))}`:''}</small>${candidates.length?`<div class="candidate-values"><span>Giá trị AI được phép dùng:</span>${candidates.map(value=>`<i>${esc(value)}</i>`).join('')}</div>`:''}</article>`;
  }).join(''):'<div class="empty">Bản ghi này chưa lưu chi tiết từng trường. Bảng nguồn dữ liệu bên cạnh vẫn cho biết AI đã bổ sung bao nhiêu.</div>';
  const coverageRows=Object.entries(coverage).map(([field,value])=>`<tr><td><b>${esc(fieldLabel(field))}</b></td><td>${pct(value.real_pct)}%</td><td>${pct(value.derived_real_pct)}%</td><td>${pct(value.ai_inferred_pct)}%</td><td>${pct(value.missing_pct)}%</td></tr>`).join();
  body.innerHTML=`<div class="dataset-learning-summary"><div><span class="status ${state.tone}">${esc(state.label)}</span>${provider?`<span class="status">AI: ${esc(provider)}</span>`:''}</div><p>${dataset.confirmed?`Đã xác nhận lúc ${esc(dataset.confirmed_at||'—')}. Bộ dữ liệu này đang được phép tham gia nguồn học tích lũy.`:'AI đã tạo báo cáo nhưng bộ dữ liệu chỉ được dùng cho các lần phân tích sau khi bạn xác nhận audit.'}</p></div><div class="dataset-learning-kpis"><div class="stat"><span>Dữ liệu gốc</span><b>${pct(audit.overall_real_data_pct)}%</b></div><div class="stat"><span>Dữ liệu dẫn xuất</span><b>${pct(audit.overall_derived_real_pct)}%</b></div><div class="stat"><span>AI bổ sung</span><b>${pct(audit.overall_ai_inferred_pct)}%</b></div><div class="stat"><span>Còn thiếu</span><b>${pct(audit.overall_missing_pct)}%</b></div><div class="stat"><span>Trường AI học được</span><b>${learnedCount}/${learned.length}</b></div></div><div class="dataset-learning-grid"><section><div class="dataset-learning-section-title"><h4>AI đã học được những gì?</h4><span>${learned.length} trường đã đánh giá</span></div><div class="dataset-learned-list">${fieldCards}</div></section><section><div class="dataset-learning-section-title"><h4>Nguồn hình thành dữ liệu</h4><span>${Object.keys(coverage).length} trường</span></div><div class="table-wrap"><table class="dataset-coverage-table"><thead><tr><th>Trường</th><th>Gốc</th><th>Dẫn xuất</th><th>AI</th><th>Thiếu</th></tr></thead><tbody>${coverageRows||'<tr><td colspan="5">Bản ghi cũ chưa có bảng độ phủ.</td></tr>'}</tbody></table></div></section></div>`;
}

async function selectDatasetLearning(uploadId,options={}){
  const id=Number(uploadId);if(!id)return;
  selectedDatasetId=id;
  document.querySelectorAll('.dataset-select').forEach(button=>{const active=Number(button.dataset.uploadId)===id;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',active?'true':'false')});
  const panel=document.querySelector('#datasetLearningPanel'),title=document.querySelector('#datasetLearningTitle'),meta=document.querySelector('#datasetLearningMeta'),body=document.querySelector('#datasetLearningBody');
  if(panel)panel.classList.remove('hidden');if(title)title.textContent='Đang tải chi tiết AI Learning...';if(meta)meta.textContent='';if(body)body.innerHTML='<div class="empty">Đang đọc báo cáo audit của bộ dữ liệu đã chọn...</div>';
  if(options.scroll!==false&&panel)panel.scrollIntoView({behavior:'smooth',block:'start'});
  try{
    const response=await api(`/api/customers/datasets/${encodeURIComponent(id)}/learning`);
    if(Number(selectedDatasetId)!==id)return;
    renderDatasetLearningDetail(response.dataset||{});
  }catch(error){
    if(Number(selectedDatasetId)!==id)return;
    if(title)title.textContent='Không thể mở bộ dữ liệu';if(body)body.innerHTML=`<div class="notice error">${esc(error.message)}</div>`;
  }
}

async function loadDatasetHistory(){
  try{
    const response=await api('/api/customers/datasets'),stats=response.stats||{},items=response.items||[],box=document.querySelector('#datasetHistory');
    document.querySelector('#datasetStats').textContent=`${stats.datasets||0} file · ${(stats.canonical_customers||0).toLocaleString()} khách hàng đã lưu`;
    box.innerHTML=items.map(dataset=>{const state=datasetLearningState(dataset),active=Number(selectedDatasetId)===Number(dataset.id);return `<button type="button" class="dataset-history-item dataset-select${active?' selected':''}" data-upload-id="${Number(dataset.id)}" aria-pressed="${active?'true':'false'}" aria-controls="datasetLearningPanel"><span class="dataset-item-copy"><b>${esc(dataset.name)}</b><span>${Number(dataset.records||0).toLocaleString()} bản ghi · ${esc(dataset.uploaded_at||'')}</span><small>Xem AI đã học được gì →</small></span><span class="status ${state.tone}">${esc(state.label)}</span></button>`}).join('')||'<div class="empty">Chưa có dataset nào được lưu cho tài khoản này.</div>';
    box.querySelectorAll('.dataset-select').forEach(button=>button.onclick=()=>selectDatasetLearning(button.dataset.uploadId));
    if(selectedDatasetId&&items.some(item=>Number(item.id)===Number(selectedDatasetId)))selectDatasetLearning(selectedDatasetId,{scroll:false});
    else if(selectedDatasetId)closeDatasetLearningDetail();
  }catch(error){const stats=document.querySelector('#datasetStats');if(stats)stats.textContent='Không tải được lịch sử'}
}

const closeDatasetLearningButton=document.querySelector('#closeDatasetLearning');
if(closeDatasetLearningButton)closeDatasetLearningButton.onclick=closeDatasetLearningDetail;
window.selectDatasetLearning=selectDatasetLearning;
