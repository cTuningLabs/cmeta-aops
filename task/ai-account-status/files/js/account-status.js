/* Shared account-status display. Licensed under the Apache License, Version 2.0.
 * See the COPYRIGHT and LICENSE files in the project root for details. */
((scope) => {
  'use strict';
  const harnessName = value => ({codex:'Codex',claude:'Claude',opencode:'OpenCode',vibe:'Vibe',gemini:'Gemini',antigravity:'Antigravity',openclaw:'OpenClaw',hermes:'Hermes'}[value] || value || 'AI');
  function describe(out, {compact=false, includeAccount=false}={}) {
    const parts=[], a=out.account||{};
    if(includeAccount)parts.push(...[a.email||a.type,a.planType].filter(Boolean));
    for(const w of out.windows||[]) {
      if(typeof w.usedPercent!=='number'||!Number.isFinite(w.usedPercent))continue;
      const mins=w.windowDurationMins;
      const label=w.label||(mins>=1440?`${mins/1440}d`:mins>=60?`${mins/60}h`:mins?`${mins}min`:'Quota');
      let part=`${label}: ${Math.max(0,Math.min(100,100-w.usedPercent)).toFixed(0)}% ${compact?'left':'remaining'}`;
      if(w.resetsAt)part+='; resets '+new Date(w.resetsAt*1000).toLocaleString(undefined,compact?{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}:{});
      parts.push(part);
    }
    if(out.credits?.unlimited)parts.push('Credits: unlimited');
    else if(out.credits?.balance!=null)parts.push('Credits remaining: '+(Number.isFinite(Number(out.credits.balance))?Number(out.credits.balance).toLocaleString(undefined,{maximumFractionDigits:1}):out.credits.balance));
    if(out.message)parts.push(out.message);
    if(out.stale)parts.unshift('Last known quota (refresh pending)');
    else if(out.cached&&!compact)parts.push('Cached for up to 2 minutes');
    return harnessName(out.harness)+': '+(parts.join(' · ')||'Quota not reported');
  }
  function details(out) {
    return [out.message||'',out.checked_at?'Checked '+new Date(out.checked_at*1000).toLocaleString()+'.':'',
      out.stale?'Last known values; the latest refresh failed.':'',
      'Server account allowance, shared with other sessions using this account. Percentages are usage allowances, not a numeric credit balance.',
      out.usage_url?'Usage page: '+out.usage_url:''].filter(Boolean).join(' ');
  }
  function mount({get,query,values,onChange=()=>{},isDisabled=()=>false}) {
    let checking=false,pending=false;
    async function refresh() {
      if(checking){pending=true;return;}checking=true;get('usage-refresh').disabled=true;
      const selection=values(), key=JSON.stringify(selection);
      get('account-status').textContent='Checking the AI account on this server…';
      try {
        const out=await query('account_status',selection);
        if(key!==JSON.stringify(values())){pending=true;return;}
        const element=get('account-status');element.textContent=describe(out,{includeAccount:true});element.title=details(out);
        if(/^https:\/\//.test(out.usage_url||'')) {
          const link=document.createElement('a');link.href=out.usage_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open usage page';
          element.append(document.createTextNode(' · '),link);
        }
        onChange(out);
      } catch(e) {
        if(key===JSON.stringify(values())){const out={harness:selection.harness,available:false,message:e.message};get('account-status').textContent=describe(out);onChange(out);}
        else pending=true;
      } finally {checking=false;get('usage-refresh').disabled=isDisabled();if(pending){pending=false;refresh();}}
    }
    function record(usage) {
      if(!usage)return;const t=usage.tokens||{},parts=[];
      if(t.sent!=null||t.input!=null)parts.push(Number(t.sent??t.input).toLocaleString()+' input tokens');
      if(t.cached!=null)parts.push(Number(t.cached).toLocaleString()+' cached');
      if(t.output!=null)parts.push(Number(t.output).toLocaleString()+' output tokens');
      if(usage.seconds!=null)parts.push(Number(usage.seconds).toFixed(1)+' seconds');
      parts.push(usage.cost_usd!=null?'$'+Number(usage.cost_usd).toFixed(4):'Cost not reported');
      get('run-usage').textContent='Last run: '+parts.join(' · ');refresh();
    }
    get('usage-refresh').addEventListener('click',refresh);
    return {refresh,record};
  }
  const api={mount,describe,details,harnessName};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else scope.CMetaAIAccountStatus=api;
})(typeof window!=='undefined'?window:globalThis);
