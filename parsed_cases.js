/* Persistent parsed-case library. Business text and executable plans are separate. */
(() => {
  const card=document.createElement('div');card.className='card';card.id='parsedCaseLibrary';
  const heading=document.createElement('h2');heading.textContent='已解析用例';
  const intro=document.createElement('p');intro.textContent='解析结果自动保存在本机。选择已保存用例即可测试；编辑后自动保存，也可重新 AI 分析。';
  const status=document.createElement('p');status.setAttribute('role','status');status.style.cssText='font-size:13px;min-height:22px';
  const toolbar=document.createElement('div');toolbar.style.cssText='display:flex;gap:8px;flex-wrap:wrap;align-items:center';
  const groups=document.createElement('select');groups.setAttribute('aria-label','已解析用例组');groups.style.cssText='flex:1;min-width:220px;margin:0';
  const button=(text,fn)=>{const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;b.onclick=fn;return b};
  const refresh=button('刷新列表',()=>loadList().catch(fail));
  toolbar.append(groups,refresh);
  const controls=document.createElement('div');controls.hidden=true;
  const nameLabel=document.createElement('label');nameLabel.textContent='用例组名称';
  const name=document.createElement('input');name.setAttribute('aria-label','用例组名称');
  const sourceInfo=document.createElement('p');sourceInfo.style.cssText='font-size:12px;color:#66788c';
  const logPanel=document.createElement('details'),logHeading=document.createElement('summary'),logBody=document.createElement('pre');
  logHeading.textContent='操作与 AI 分析日志';logBody.style.cssText='max-height:260px;overflow:auto;white-space:pre-wrap;font-size:12px';
  const refreshLogs=button('刷新日志',()=>loadLogs().catch(fail));
  const downloadLogs=document.createElement('a');downloadLogs.textContent='下载日志';downloadLogs.style.marginLeft='12px';
  logPanel.append(logHeading,refreshLogs,downloadLogs,logBody);
  const actions=document.createElement('div');actions.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin:12px 0';
  const list=document.createElement('div');list.style.cssText='max-height:330px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:8px';
  const editor=document.createElement('div');
  const all=button('全选',()=>{if(!suite)return;chosen=new Set(suite.cases.map(c=>c.id));renderList()});
  const none=button('清空选择',()=>{chosen.clear();renderList()});
  const run=button('测试所选用例',()=>runSelected().catch(fail));
  const analyze=button('重新 AI 分析所选',()=>analyzeSelected().catch(fail));
  const analyzeAll=button('重新 AI 分析整组',()=>analyzeSelected(true).catch(fail));
  const remove=button('删除本组',()=>deleteGroup().catch(fail));
  actions.append(all,none,run,analyze,analyzeAll,remove);
  const filter=document.createElement('input');filter.placeholder='筛选已解析用例标题';filter.setAttribute('aria-label','筛选已解析用例标题');filter.oninput=renderList;
  const caseLayout=document.createElement('div');caseLayout.className='parsed-case-layout';
  const caseSidebar=document.createElement('div');list.classList.add('parsed-case-list');editor.className='parsed-case-editor';
  caseSidebar.append(filter,list);caseLayout.append(caseSidebar,editor);
  controls.append(nameLabel,name,sourceInfo,actions,logPanel,caseLayout);
  card.append(heading,intro,toolbar,status,controls);
  document.getElementById('excelConversionCard').after(card);
  const open=button('已解析用例',()=>{showWorkspace('config');card.scrollIntoView({behavior:'smooth',block:'start'});loadList().catch(fail)});
  open.id='parsedLibraryEntry';
  excelEntryButton.after(open);
  let suite=null,selectedCase=null,chosen=new Set(),pending=new Map(),timer=null,queue=Promise.resolve(),saveError=null,writing=0;
  const tag=c=>c.needs_reanalysis?'待重新分析':c.plan?(c.partial_reason?'部分步骤':'可测试'):'待绑定';
  const fail=e=>{status.textContent=e.message||String(e);status.style.color='#b42318'};
  const note=text=>{status.textContent=text;status.style.color='';};
  async function request(path,body){
    const r=await fetch('/api/parsed-cases'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await r.json();if(!r.ok)throw Error(data.error||'用例库请求失败');return data;
  }
  async function loadLogs(id=suite?.id){
    if(!id)return;
    const data=await request('/logs/'+encodeURIComponent(id));
    if(suite?.id!==id)return;
    logBody.textContent=data.events.length?data.events.map(event=>new Date(event.time).toLocaleString()+'  '+event.message+(event.case_id?' · '+event.case_id:'')+(event.fields?.length?' · 字段：'+event.fields.join('、'):'')+(event.batch_id?' · 批次：'+event.batch_id:'')).join('\n'):'暂无操作日志，后续解析、编辑、删除、重新分析和测试操作会自动记录。';
    logBody.scrollTop=logBody.scrollHeight;
    downloadLogs.href='/api/parsed-cases/logs/'+encodeURIComponent(id);
    downloadLogs.download=(suite.source_filename||suite.name)+'-操作日志.json';
  }
  function activate(){
    if(!suite)return;
    window.selectedParsedSuite={id:suite.id,revision:suite.revision,case_ids:[...chosen]};
    try{localStorage.setItem('devicecheck-parsed-suite',suite.id)}catch{}
  }
  function readyOptions(rows){
    groups.replaceChildren(new Option(rows.length?'选择已保存的用例组':'暂无解析结果，先在下方读取 Excel 并生成步骤',''));
    for(const item of rows)groups.add(new Option(item.name+' · '+item.total+' 条 / '+item.ready+' 条可测试',item.id));
    if(suite&&rows.some(r=>r.id===suite.id))groups.value=suite.id;
  }
  async function loadList(){
    const rows=await request('');readyOptions(rows);
    if(!suite){let remembered='';try{remembered=localStorage.getItem('devicecheck-parsed-suite')||''}catch{}
      if(rows.length)await loadSuite(rows.some(r=>r.id===remembered)?remembered:rows[0].id);
      else note('暂无已保存用例。新的解析结果会自动保存，也会导入已有的历史解析结果。');
    }
    return rows;
  }
  async function loadSuite(id){
    await flush();suite=await request('/'+encodeURIComponent(id));groups.value=id;selectedCase=suite.cases[0]?.id||null;
    chosen=new Set(suite.cases.map(c=>c.id));name.value=suite.name;controls.hidden=false;saveError=null;activate();renderList();renderEditor();
    sourceInfo.textContent='来源 Excel：'+(suite.source_filename||'历史记录尚未关联原文件');
    await loadLogs(id);
    note('已加载 '+suite.cases.length+' 条 · 保存在本机，修改后自动保存');
  }
  groups.onchange=()=>{if(groups.value)loadSuite(groups.value).catch(fail)};
  function renderList(){
    list.replaceChildren();if(!suite)return;
    const rows=suite.cases.filter(c=>c.title.toLowerCase().includes(filter.value.trim().toLowerCase()));
    for(const c of rows){
      const row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--line)';
      const check=document.createElement('input');check.type='checkbox';check.checked=chosen.has(c.id);check.style.width='auto';check.setAttribute('aria-label','选择用例 '+c.title);
      check.onchange=()=>{if(check.checked)chosen.add(c.id);else chosen.delete(c.id);activate()};
      const title=button(c.title,async()=>{try{await flush();selectedCase=c.id;renderEditor()}catch(e){fail(e)}});title.style.cssText='text-align:left;flex:1;white-space:normal;border:0;background:transparent;color:var(--ink);padding:4px';
      const state=document.createElement('small');state.textContent=tag(c);row.append(check,title,state);list.append(row);
    }
    if(!rows.length){const p=document.createElement('p');p.textContent='没有匹配的用例';list.append(p)}
    run.textContent='测试所选用例（'+chosen.size+'）';activate();
  }
  function schedule(caseId,field,value){
    pending.set((caseId||'suite')+'\0'+field,{caseId,field,value});saveError=null;note('修改待保存…');
    clearTimeout(timer);timer=setTimeout(()=>{timer=null;drain().catch(fail)},650);
  }
  name.oninput=()=>schedule(null,'name',name.value);
  async function drain(){
    const updates=[...pending.values()];pending.clear();if(!updates.length)return queue;
    const id=suite.id;
    writing++;
    queue=queue.then(async()=>{
      for(const [index,update] of updates.entries()){
        const body={id,revision:suite.revision};
        if(update.caseId){body.case_id=update.caseId;body.changes={[update.field]:update.value}}
        else body.name=update.value;
        try{
          const saved=await request('/update',body);suite=saved;activate();
          if(update.caseId&&['steps','expected','precondition','test_data'].includes(update.field)){
            const area=editor.querySelector('[data-plan-editor]');if(area&&document.activeElement!==area)area.value=JSON.stringify(suite.cases.find(c=>c.id===selectedCase)?.plan||null,null,2);
          }
          renderList();const option=[...groups.options].find(o=>o.value===suite.id);if(option)option.textContent=suite.name+' · '+suite.cases.length+' 条 / '+suite.cases.filter(c=>c.plan&&!c.needs_reanalysis).length+' 条可测试';
          await loadLogs();note('已自动保存 · '+new Date().toLocaleTimeString());
        }catch(e){for(const remaining of updates.slice(index)){const key=(remaining.caseId||'suite')+'\0'+remaining.field;if(!pending.has(key))pending.set(key,remaining)}saveError=e;throw e}
      }
    }).catch(e=>{saveError=e;fail(e)}).finally(()=>{writing--});
    return queue;
  }
  async function flush(){clearTimeout(timer);timer=null;await drain();await queue;if(saveError)throw saveError;}
  function renderEditor(){
    editor.replaceChildren();const c=suite?.cases.find(c=>c.id===selectedCase);if(!c)return;
    const h=document.createElement('h3');h.textContent='编辑：'+c.title;editor.append(h);
    const info=document.createElement('p');info.style.fontSize='12px';info.textContent='文本修改后自动保存。业务步骤、预期或测试数据改变后需重新分析；运行步骤 JSON 校验通过后可直接测试。';editor.append(info);
    for(const [field,label,rows] of [['title','标题',1],['precondition','前置条件',3],['test_data','测试数据',3],['steps','业务步骤',5],['expected','预期结果',4]]){
      const l=document.createElement('label');l.textContent=label;const input=rows===1?document.createElement('input'):document.createElement('textarea');
      if(rows>1)input.rows=rows;input.value=c[field]||'';input.setAttribute('aria-label','编辑用例'+label);
      input.oninput=()=>schedule(c.id,field,input.value);input.onblur=()=>flush().catch(fail);editor.append(l,input);
    }
    const technical=document.createElement('details'),summary=document.createElement('summary'),plan=document.createElement('textarea');
    summary.textContent='编辑运行步骤（JSON）';plan.rows=14;plan.value=JSON.stringify(c.plan||null,null,2);plan.dataset.planEditor='true';plan.setAttribute('aria-label','编辑运行步骤JSON');
    plan.oninput=()=>{try{const value=JSON.parse(plan.value);schedule(c.id,'plan',value)}catch{pending.delete(c.id+'\0plan');saveError=Error('运行步骤 JSON 尚未完整，暂未保存');note(saveError.message)}};
    plan.onblur=()=>{try{JSON.parse(plan.value);flush().catch(fail)}catch{saveError=Error('运行步骤 JSON 格式不完整，请修正后再测试');fail(saveError)}};
    technical.append(summary,plan);editor.append(technical);
    if(c.partial_reason||c.needs_reanalysis){const p=document.createElement('p');p.textContent=c.partial_reason||'旧版本解析结果，需重新分析或修改运行步骤';p.style.cssText='font-size:12px;color:#9b702c';editor.append(p)}
    const removeCase=button('删除这条用例',()=>deleteCase(c.id).catch(fail));editor.append(removeCase);
  }
  async function deleteCase(id){
    await flush();suite=await request('/delete',{id:suite.id,revision:suite.revision,case_id:id});chosen.delete(id);selectedCase=suite.cases[0]?.id||null;activate();renderList();renderEditor();await loadLogs();note('用例已删除并保存');
  }
  async function deleteGroup(){
    await flush();await request('/delete',{id:suite.id,revision:suite.revision});suite=null;window.selectedParsedSuite=null;controls.hidden=true;pending.clear();await loadList();
  }
  async function runSelected(){
    await flush();if(!chosen.size)throw Error('请至少选择一条用例');activate();
    if(!$('quickScript').querySelector('option[value=excel]'))$('quickScript').add(new Option('按 Excel 用例运行','excel'));
    $('quickScript').value='excel';$('quickScript').onchange();$('testMode').value='cases';
    note('正在使用已保存的运行步骤创建测试…');await $('run').onclick();await loadLogs();
  }
  async function analyzeSelected(entire=false){
    await flush();if(!entire&&!chosen.size)throw Error('请至少选择一条需要分析的用例');
    if(aiWorking)throw Error('已有 AI 任务，请等待当前任务完成');
    await ensureAIKey();const id=suite.id;aiBusy(true);analyze.disabled=true;analyzeAll.disabled=true;
    try{
      const settings={...aiOptions(),id,revision:suite.revision,excel_observation_mode:true};
      if(!entire)settings.case_ids=[...chosen];
      if($('source').value.trim())settings.source=$('source').value.trim();
      if($('h5Source').value.trim())settings.h5_source=$('h5Source').value.trim();
      const task=await request('/reanalyze',settings);
      for(;;){const r=await fetch('/api/ai/generations/'+encodeURIComponent(task.id));const state=await r.json();if(!r.ok)throw Error(state.error);note(state.label||'AI 正在重新分析…');await loadLogs(id);
        if(state.status==='failed')throw Error(state.error);
        if(state.status==='done'){if(suite?.id===id)await loadSuite(id);await loadList();note('重新分析完成，结果已保存');break}
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }finally{aiBusy(false);analyze.disabled=false;analyzeAll.disabled=false}
  }
  const originalConfig=caseConfig;
  caseConfig=function(){
    if(window.selectedParsedSuite)return {library_id:window.selectedParsedSuite.id,library_revision:window.selectedParsedSuite.revision,case_ids:window.selectedParsedSuite.case_ids,evidence_policy:'assertions'};
    return originalConfig();
  };
  const originalRun=$('run').onclick;
  $('run').onclick=async function(...args){if(window.selectedParsedSuite){try{await flush()}catch(e){fail(e);return}}return originalRun.apply(this,args)};
  const originalPreview=$('previewCases').onclick;
  $('previewCases').onclick=function(...args){window.selectedParsedSuite=null;return originalPreview.apply(this,args)};
  $('casePath').addEventListener('input',()=>{window.selectedParsedSuite=null});
  const originalGenerate=$('generateExcelAI').onclick;
  $('generateExcelAI').onclick=async function(...args){window.selectedParsedSuite=null;await originalGenerate.apply(this,args);await loadList().catch(fail)};
  window.addEventListener('beforeunload',e=>{if(pending.size||writing||saveError){e.preventDefault();e.returnValue='修改尚未保存'}});
  loadList().catch(fail);
})();
