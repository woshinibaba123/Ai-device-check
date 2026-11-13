const { Agent } = require('@midscene/core/agent');
const { spawn } = require('node:child_process');
const path = require('node:path');
async function main(input) {
  let calls = 0;
  const begin=Date.now();
  const trace=(stage, extra={})=>process.stdout.write('DEVICECHECK_TRACE='+JSON.stringify({stage,seconds:(Date.now()-begin)/1000,...extra})+'\n');
  trace('sdk_started');
  const device = {
    interfaceType: 'devicecheck-screenshot',
    screenshotBase64: async () => input.image,
    size: async () => ({ width: input.width, height: input.height }),
    actionSpace: () => [],
    describe: () => 'Read-only screenshot supplied by DeviceCheck',
  };
  const agent = new Agent(device, {
    generateReport: false, autoPrintReportMsg: false,
    modelConfig: {
      MIDSCENE_MODEL_NAME: 'codebuddy-vision', MIDSCENE_MODEL_FAMILY: input.model.startsWith('glm-') ? 'glm-v' : 'gpt-5',
      MIDSCENE_MODEL_API_KEY: 'local-stdio-bridge', MIDSCENE_MODEL_BASE_URL: 'http://127.0.0.1:1/v1',
      MIDSCENE_MODEL_STREAM_MODE: 'non-stream', MIDSCENE_MODEL_RETRY_COUNT: 0,
    },
    createOpenAIClient: async (client) => {
      client.chat.completions.create = async (request) => {
        calls++;
        if (input.operation === 'locate' && input.model.startsWith('glm-')) {
          request = {...request, messages: [...request.messages, {role:'user', content:
            'Coordinate contract for this locate response: use the SDK glm-v normalized coordinate range 0..1000 for every bbox coordinate, NOT screenshot pixels. Normalize x by screenshot width and y by screenshot height. Screenshot dimensions: '+input.width+' x '+input.height+'. Keep the SDK-required response fields and data-json envelope. If the target is absent, use the SDK target-not-found response; do not invent a box.'}]};
        }
        if (input.operation !== 'locate') {
          request={...request,messages:[...request.messages,{role:'user',content:'Return the complete structured result required by the original SDK schema. Include the final valid JSON inside <data-json>...</data-json>, or output the complete JSON object directly. An observation-only answer is invalid. Do not invent a target or coordinates; use the required blocked/not-found output when necessary.'}]};
        }
        trace('model_request_started',{call:calls});
        const data = await new Promise((resolve, reject) => {
          const child = spawn(input.python, [path.join(__dirname, 'codebuddy_worker.py')], { stdio: ['pipe','pipe','pipe'] });
          let stdout = '';
          child.stdout.on('data', b => { stdout += b; if (stdout.length > 2000000) child.kill(); });
          let errors='';
          child.stderr.on('data', b => {
            errors+=b; let idx;
            while ((idx=errors.indexOf('\n'))>=0) {
              const line=errors.slice(0,idx);errors=errors.slice(idx+1);
              try { const v=JSON.parse(line); if (/^(worker_started|payload_converted|cli_[a-z_]+|cli_returned)$/.test(v.stage)) trace(v.stage,{worker_seconds:v.seconds}); } catch {}
            }
          });
          child.on('error', reject);
          child.on('close', code => {
            trace('worker_closed',{code});
            try { const v = JSON.parse(stdout); if (code || v.error) { resolve({text: '', bridgeError: v.error, formatError:v.format_error, timeout:v.timeout, quota:v.quota}); return; } resolve(v); }
            catch { reject(Error('CodeBuddy bridge failed')); }
          });
          child.stdin.end(JSON.stringify({ ...request, codebuddy_model: input.model, region: input.region, timeout: input.timeout }));
        });
        trace('model_request_finished');
        if (data.quota) throw Error('quota_exhausted');
        if (data.formatError) throw Error('JSON response format: '+data.formatError);
        if (data.bridgeError) throw Error('CodeBuddy bridge '+data.bridgeError+(data.timeout ? ' timeout' : ''));
        return { choices: [{ index: 0, finish_reason: 'stop', message: { role:'assistant', content:data.text } }], model: input.model };
      };
      return client;
    },
  });
  const started = Date.now();
  try {
    trace('agent_operation_started');
    const value = input.operation === 'locate' ? await agent.aiLocate(input.prompt) : await agent.aiQuery(input.prompt);
    trace('agent_operation_finished');
    return { engine: 'midscene', version: '1.17.7', value, model_calls: calls, seconds: (Date.now()-started)/1000 };
  } finally { await agent.destroy(); }
}
let raw=''; process.stdin.on('data', b => raw += b);
process.stdin.on('end', async () => {
  try { const result=await main(JSON.parse(raw)); process.stdout.write('\nDEVICECHECK_RESULT='+JSON.stringify(result)+'\n'); }
  catch (e) {
    const message=String(e.message);
    require('node:fs').writeFileSync(path.join(__dirname,'../output/midscene-last-error.json'),JSON.stringify({name:e.name,message,stack:e.stack},null,2));
    const category=/quota_exhausted/i.test(message) ? 'quota' : /not found|failed to locate|cannot locate|no element/i.test(message) ? 'target_not_found' : /parse|json|schema|format|bbox|coordinate/i.test(message) ? 'response_format' : /bridge/i.test(message) ? 'model_bridge' : 'sdk_execution';
    process.stdout.write('\nDEVICECHECK_RESULT='+JSON.stringify({error:'Midscene execution failed',category,detail: /quota_exhausted/.test(message)?'quota_exhausted': /empty_model_response|invalid_json_response|expected_json_object/.exec(message)?.[0] || (/json/i.test(message)?'sdk_json_parse':/coordinate|bbox/i.test(message)?'sdk_coordinate_parse':/schema|format/i.test(message)?'sdk_schema_validation':'sdk_error'),timeout:/timeout/i.test(message)})+'\n'); process.exitCode=1;
  }
});
