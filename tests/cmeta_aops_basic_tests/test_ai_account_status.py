"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Hermetic account-status regressions: fake credentials/provider replies only,
with no network, inference, real login reads or changes to a developer's cMeta home.
"""
import json
import base64
import io
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

SOURCE = Path(__file__).resolve().parents[2]
path = SOURCE / 'task/ai-account-status/api_v1.py'
source = path.read_text(encoding='utf-8')
base_import = 'from task_c36be4b9314a45e0.api.ctask import InitCTask, drop_provider_variables'
assert base_import in source
m = types.ModuleType('ai_account_status_under_test')
m.__file__ = str(path)
# Keep the real environment policy: login reads drop parent gateway/API variables.
env_source = (SOURCE/'category/task/api/ctask.py').read_text(encoding='utf-8').split('def gateway_into_environment',1)[0]
env_module = types.ModuleType('environment_policy')
exec(compile(env_source, 'environment_policy', 'exec'), env_module.__dict__)
m.drop_provider_variables = env_module.drop_provider_variables
exec(compile(source.replace(base_import, 'InitCTask = object'), str(path), 'exec'), m.__dict__)

class Tests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
  self.task=object.__new__(m.CTask);self.task.cmeta={'uses_categories':{'task':'task','log':'log','config':'config'}}
  self.config={};self.gateways={};self.machine={'return':0,'gateway':'login','how':'no default'}
  self.tools={}  # what cMeta's tool detection finds: <tool cRef> -> the setup task's answer (none: the harness is not found)
  self.harnesses={'return':0,'harnesses':[],'index':{},'conflicts':{}}  # none declared: the tuples of before
  class FakeCM:
   def access(_,params):
    if params['category']=='config':return {'return':0,'config_cmeta':self.config}
    if params['category']==m.GATEWAY_CATEGORY:
     assert params['command']=='list',params
     return {'return':0,'gateways':[dict(alias=params['arg1'],auth=self.gateways[params['arg1']])] if params['arg1'] in self.gateways else []}
    if params['category']=='task':
     if params.get('command')=='harnesses':return dict(self.harnesses)  # cx task harnesses: what the graph declares
     if params['arg1']==m.SETUP_TASK:return dict(self.tools.get(params['name'],{'return':16,'error':'not found'}))
     assert params['arg1']==m.SET_AI_GATEWAY and params['connect'] is False,params
     return dict(self.machine)
    assert params['category']=='log',params
    return {'return':0,'artifact':{'path':str(self.root)}}
  self.task.cm=FakeCM()
 def tearDown(self):self.directory.cleanup()
 def run_task(self,**kw):return self.task.run({},**kw)
 def test_window_validation(self):
  for value in (True,None,float('nan'),float('inf'),-1,101,'20'):
   self.assertIsNone(m.window(value,300))
  self.assertEqual(m.window(0,300,'2030-01-01T00:00:00Z')['resetsAt'],1893456000)
  self.assertNotIn('resetsAt',m.window(100,300,'invalid'))
 def test_claude_allowlist(self):
  raw={'five_hour':{'utilization':12,'resets_at':'2030-01-01T00:00:00Z'},'seven_day':{'utilization':35},'seven_day_opus':{'utilization':3},'accessToken':'secret','unknown':{'utilization':99}}
  with patch.object(m,'get_usage',return_value=raw):out=m.claude_usage('secret','pro')
  self.assertEqual([w['usedPercent'] for w in out['windows']],[12,35,3])
  self.assertNotIn('secret',json.dumps(out));self.assertEqual(out['account']['planType'],'pro')
 def test_null_windows_not_zero_allowance(self):
  with patch.object(m,'get_usage',return_value={'five_hour':None,'seven_day':{'utilization':True}}):out=m.claude_usage('secret')
  self.assertFalse(out['available']);self.assertEqual(out['windows'],[])
 def test_openai_normalization(self):
  with patch.object(m,'get_usage',return_value={'plan_type':'pro','accessToken':'secret','rate_limit':{'primary_window':{'used_percent':20,'limit_window_seconds':604800,'reset_at':2000000000}},'credits':{'balance':'3.5','token':'secret'}}):out=m.openai_usage('secret')
  self.assertEqual(out['windows'][0]['windowDurationMins'],10080);self.assertEqual(out['credits'],{'balance':'3.5'});self.assertNotIn('secret',json.dumps(out))
 def test_http_errors_sanitized(self):
  for code,reason in ((401,'login_expired'),(403,'scope_required'),(429,'rate_limited'),(500,'provider_error'),(302,'provider_error')):
   opener=unittest.mock.Mock();opener.open.side_effect=HTTPError(m.CLAUDE_URL,code,'private credential in error',{'retry-after':'0'},None)
   with patch.object(m,'build_opener',return_value=opener):
    with self.assertRaises(m.StatusError) as error:m.get_usage(m.CLAUDE_URL,'secret')
   self.assertEqual(error.exception.reason,reason);self.assertNotIn('private',error.exception.message);self.assertNotIn('secret',error.exception.message)
   if code==429:self.assertGreaterEqual(error.exception.retry,120)
 def test_network_error_sanitized(self):
  opener=unittest.mock.Mock();opener.open.side_effect=URLError('Bearer secret')
  with patch.object(m,'build_opener',return_value=opener):
   with self.assertRaises(m.StatusError) as error:m.get_usage(m.CLAUDE_URL,'secret')
  self.assertNotIn('secret',error.exception.message)
 def test_redirects_disabled(self):self.assertIsNone(m.NoRedirect().redirect_request(None,None,None,None,None,None))
 def test_only_fixed_urls(self):
  with self.assertRaises(AssertionError):m.get_usage('https://example.test/','secret')
 def test_claude_environment_precedence(self):
  with patch.dict(os.environ,{'CLAUDE_CODE_OAUTH_TOKEN':'env-secret'},clear=True),patch.object(m,'read_json',side_effect=AssertionError('must not read another login')),patch.object(m,'claude_usage',return_value={'available':True}) as read:
   identity,fetch,page=self.task._selection('claude','');fetch(self.root)
  self.assertEqual(identity,'env-secret');read.assert_called_once_with('env-secret','',include_identity=True)
 def test_custom_claude_directory(self):
  with patch.dict(os.environ,{'CLAUDE_CONFIG_DIR':str(self.root)},clear=True),patch.object(m,'read_json',return_value={'claudeAiOauth':{'accessToken':'file-secret','subscriptionType':'pro'}}) as read:
   identity,fetch,page=self.task._selection('claude','')
  self.assertEqual(identity,'file-secret');self.assertEqual(read.call_args.args[0],self.root/'.credentials.json')
 def test_opencode_uses_own_account(self):
  with patch.object(m,'read_json',return_value={'openai':{'type':'oauth','access':'opencode-secret','accountId':'account'}}),patch.object(m,'openai_usage',return_value={'available':True}) as read:
   identity,fetch,page=self.task._selection('opencode','openai/model');fetch(self.root)
  read.assert_called_once_with('opencode-secret','account',include_identity=True)
 def test_opencode_never_borrows_other_login(self):
  with patch.object(m,'read_json',return_value={}):out=self.run_task(harness='opencode',model='openai/model')
  self.assertEqual(out['reason'],'provider_login_required')
 def test_provider_not_guessed(self):
  for harness in ('opencode','openclaw'):
   with patch.object(m,'read_json',side_effect=AssertionError('no credentials without provider')):out=self.run_task(harness=harness)
   self.assertEqual(out['reason'],'provider_required')
 def test_gateway_does_not_read_personal_credentials(self):
  with patch.object(self.task,'_selection',side_effect=AssertionError('no login read')):out=self.run_task(harness='claude',gateway='company')
  self.assertEqual(out['reason'],'gateway');self.assertFalse(out['available'])
 def test_unknown_and_manual_harnesses(self):
  for h in ('vibe','gemini','antigravity','agy','hermes','custom'):
   out=self.run_task(harness=h);self.assertEqual(out['return'],0);self.assertFalse(out['available']);self.assertTrue(out['message'])
 def test_input_types(self):
  for value in ([],{},True,None,'x'*301):self.assertEqual(self.run_task(harness=value)['return'],1)
 def test_cache_and_secret_isolation(self):
  calls=[]
  def fetch(folder):calls.append(folder);return {'available':True,'windows':[{'usedPercent':3,'windowDurationMins':300}]}
  with patch.object(self.task,'_selection',return_value=('secret-identity',fetch,m.PAGES['claude'])):
   a=self.run_task(harness='claude');b=self.run_task(harness='claude')
  self.assertEqual(len(calls),1);self.assertFalse(a['cached']);self.assertTrue(b['cached']);self.assertEqual(a['checked_at'],b['checked_at'])
  cached=''.join(p.read_text() for p in self.root.glob('*.json'));self.assertNotIn('secret-identity',cached)
 def test_cache_accounts_do_not_mix(self):
  fetch=unittest.mock.Mock(return_value={'available':True,'windows':[]})
  for identity in ('first-secret','second-secret'):
   with patch.object(self.task,'_selection',return_value=(identity,fetch,m.PAGES['claude'])):self.run_task(harness='claude')
  self.assertEqual(fetch.call_count,2);self.assertEqual(len(list(self.root.glob('*.json'))),2)
 def test_backoff_and_stale(self):
  state={'error':False};now=[1000]
  def fetch(folder):
   if state['error']:raise m.StatusError('rate_limited','Please wait',300)
   return {'available':True,'windows':[{'usedPercent':10}]}
  with patch.object(self.task,'_selection',return_value=('secret',fetch,m.PAGES['claude'])),patch.object(m.time,'time',side_effect=lambda:now[0]):
   self.run_task(harness='claude');state['error']=True;now[0]=1121;out=self.run_task(harness='claude');now[0]=1122;cached=self.run_task(harness='claude')
  self.assertFalse(out['available']);self.assertTrue(out['stale']);self.assertEqual(out['checked_at'],1000);self.assertEqual(out['windows'][0]['usedPercent'],10);self.assertTrue(cached['cached'])
 def test_old_stale_not_shown(self):
  fetch=unittest.mock.Mock(side_effect=[{'available':True,'windows':[{'usedPercent':10}]},m.StatusError('rate_limited','Wait',300)])
  with patch.object(self.task,'_selection',return_value=('secret',fetch,m.PAGES['claude'])),patch.object(m.time,'time',side_effect=[1000,1000,2000,2000]):
   self.run_task(harness='claude');out=self.run_task(harness='claude')
  self.assertFalse(out.get('stale',False));self.assertEqual(out['windows'],[])
 def test_openclaw_provider_allowlist(self):
  payload={'privateSetting':'secret','usage':{'providers':[{'provider':'openai','windows':[{'usedPercent':99}]},{'provider':'anthropic','plan':'Pro','authProfileId':'secret','windows':[{'usedPercent':7,'label':'5h','resetAt':2000000000000}]}]}}
  result=subprocess.CompletedProcess([],0,stdout=json.dumps(payload).encode())
  with patch.object(m.shutil,'which',return_value='openclaw'),patch.object(m.subprocess,'run',return_value=result) as run:out=self.task._openclaw(self.root,'anthropic')
  self.assertEqual(out['windows'][0]['usedPercent'],7);self.assertEqual(out['windows'][0]['resetsAt'],2000000000);self.assertNotIn('secret',json.dumps(out));self.assertNotIn('--probe',run.call_args.args[0])
 def test_openclaw_ambiguous_accounts(self):
  payload={'usage':{'providers':[{'provider':'anthropic'},{'provider':'anthropic'}]}}
  with patch.object(m.shutil,'which',return_value='openclaw'),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=json.dumps(payload).encode())):
   with self.assertRaises(m.StatusError):self.task._openclaw(self.root,'anthropic')
 def test_shared_client_has_no_email_dependency(self):
  out=self.run_task(client_script=True);self.assertIn('CMetaAIAccountStatus',out['script']);self.assertNotIn('EmailStudioSettings',out['script'])
 def test_claude_profile_matches_quota_token(self):
  calls=[]
  def get(url,token):
   calls.append((url,token))
   return {'account':{'email':'right@example.test','display_name':'Right','accessToken':'secret'}} if url==m.CLAUDE_PROFILE_URL else {'five_hour':{'utilization':12}}
  with patch.object(m,'get_usage',side_effect=get):out=m.claude_usage('same-secret')
  self.assertEqual(calls,[(m.CLAUDE_PROFILE_URL,'same-secret'),(m.CLAUDE_URL,'same-secret')])
  self.assertEqual(out['account']['email'],'right@example.test');self.assertNotIn('secret',json.dumps(out))
 def test_profile_failure_does_not_break_quota(self):
  with patch.object(m,'get_usage',side_effect=[m.StatusError('scope_required','No profile'),{'five_hour':{'utilization':9}}]):out=m.claude_usage('secret')
  self.assertTrue(out['available']);self.assertNotIn('email',out['account']);self.assertEqual(out['account']['authType'],'login')
 def test_identity_survives_quota_failure(self):
  with patch.object(m,'get_usage',side_effect=[{'account':{'email':'active@example.test'}},m.StatusError('rate_limited','Wait')]):
   with self.assertRaises(m.StatusError) as error:m.claude_usage('secret')
  self.assertEqual(error.exception.account['email'],'active@example.test')
 def test_hidden_claude_skips_profile_request(self):
  with patch.object(m,'get_usage',return_value={'five_hour':{'utilization':0}}) as get:out=m.claude_usage('secret',include_identity=False)
  get.assert_called_once_with(m.CLAUDE_URL,'secret');self.assertNotIn('email',out['account'])
 def test_hide_config_redacts_response_and_cache(self):
  self.config={'show_identity':False}
  fetch=unittest.mock.Mock(return_value={'available':True,'account':{'authType':'login','email':'hide@example.test','username':'Hide'},'windows':[]})
  with patch.object(self.task,'_selection',return_value=('secret',fetch,'')) as selection:
   first=self.run_task(harness='claude');second=self.run_task(harness='claude')
  # (since 2026-11-20 the call also names the way chosen for the harness's version and the program cMeta found)
  selection.assert_called_with('claude','',include_identity=False,way='claude-oauth-usage',executable='')
  for out in (first,second):
   self.assertFalse(out['identity_visible']);self.assertNotIn('identity',out);self.assertNotIn('hide@example.test',json.dumps(out));self.assertNotIn('username',out['account'])
  self.assertNotIn('hide@example.test',''.join(p.read_text() for p in self.root.glob('*.json')))
 def test_hide_override_and_config_validation(self):
  self.config={'show_identity':True}
  self.assertFalse(self.run_task(gateway='company',show_identity=False)['identity_visible'])
  for value in ('false',1,[]):self.assertEqual(self.run_task(show_identity=value)['return'],1)
  self.config={'show_identity':'invalid'};self.assertEqual(self.run_task()['return'],1)
 def test_settings_config_yes_no_values(self):
  for value,expected in ((True,True),(False,False),('yes',True),('no',False),('true',True),('false',False),(' ON ',True),('off',False),('1',True),('0',False)):
   self.config={'show_identity':value}
   out=self.run_task(gateway='company')
   self.assertEqual(out['return'],0);self.assertIs(out['identity_visible'],expected)
   self.assertEqual('identity' in out,expected)
 def test_invalid_config_values_are_rejected(self):
  for value in ('maybe','',1,0,[],{},None):
   self.config={'show_identity':value}
   self.assertEqual(self.run_task(gateway='company')['return'],1)
 def test_settings_metadata_uses_yes_no_control(self):
  import yaml
  spec=yaml.safe_load((SOURCE/'task/ai-account-status/_desc.yaml').read_text())['configs']['task-ai-account-status']['keys']['show_identity']
  self.assertEqual(spec['type'],'yes/no');self.assertIs(spec['default'],True)
 def test_gateway_identity_is_api_without_reading_personal_login(self):
  with patch.object(self.task,'_selection',side_effect=AssertionError('no personal login')):out=self.run_task(gateway='company')
  self.assertEqual(out['identity'],{'kind':'api','label':'API'});self.assertFalse(out['available'])
 def test_unknown_identity_does_not_imply_api(self):
  out=self.run_task(harness='vibe');self.assertEqual(out['identity']['kind'],'unknown');self.assertNotEqual(out['identity']['label'],'API')
 def test_opencode_api_uses_selected_provider_only(self):
  with patch.object(m,'read_json',return_value={'mistral':{'type':'api','key':'secret-key'},'openai':{'type':'oauth','access':'wrong'}}):
   out=self.run_task(harness='opencode',model='mistral/model')
  self.assertEqual(out['identity']['label'],'API');self.assertNotIn('secret-key',json.dumps(out));self.assertFalse(out['available'])
 def test_openai_email_from_same_authenticated_access_token(self):
  claims={'https://api.openai.com/profile':{'email':'own@example.test'},'private':'secret'}
  token='header.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.signature'
  with patch.object(m,'get_usage',return_value={'rate_limit':{'primary_window':{'used_percent':1}}}):out=m.openai_usage(token)
  self.assertEqual(out['account']['email'],'own@example.test');self.assertNotIn('secret',json.dumps(out))
 def test_malformed_openai_token_keeps_quota(self):
  for token in ('not-jwt','a.@@@@.b','a.'+base64.urlsafe_b64encode(b'[]').decode()+'.b'):
   with patch.object(m,'get_usage',return_value={'rate_limit':{'primary_window':{'used_percent':1}}}):out=m.openai_usage(token)
   self.assertTrue(out['available']);self.assertNotIn('email',out['account'])
 def test_codex_cache_changes_on_login_switch(self):
  home=self.root/'codex';home.mkdir();auth=home/'auth.json';auth.write_text('{"account":"one"}')
  with patch.dict(os.environ,{'CODEX_HOME':str(home)},clear=True):
   one=self.task._selection('codex','')[0];auth.write_text('{"account":"two"}');two=self.task._selection('codex','')[0]
  self.assertNotEqual(one,two);self.assertNotIn('"account"',one+two)
 def codex_reply(self,account,limits=None,error=False):
  replies=[{'id':1,'result':{}},{'id':2,'result':{'account':account}}]
  replies.append({'id':3,'error':{'message':'private secret'}} if error else {'id':3,'result':limits or {}})
  class Input(io.BytesIO):
   def close(self):pass
  proc=unittest.mock.Mock(stdin=Input(),stdout=io.BytesIO(('\n'.join(json.dumps(r) for r in replies)+'\n').encode()))
  proc.poll.return_value=0
  with patch.object(m.shutil,'which',return_value='codex'),patch.object(m.subprocess,'Popen',return_value=proc) as popen:
   out=self.task._codex(self.root)
  return out,popen.call_args,proc.stdin.getvalue().decode()
 def test_codex_api_account_skips_subscription_rpc(self):
  out,args,sent=self.codex_reply({'type':'apiKey','key':'secret'})
  self.assertEqual(out['account']['authType'],'api');self.assertNotIn('rateLimits/read',sent);self.assertNotIn('secret',json.dumps(out))
 def test_codex_login_identity_and_environment_match_run_ai(self):
  with patch.dict(os.environ,{'OPENAI_API_KEY':'wrong-key','CODEX_API_KEY':'wrong-key'},clear=True):
   out,args,sent=self.codex_reply({'type':'chatgpt','email':'own@example.test','planType':'pro','token':'secret'},{'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300}}})
  self.assertEqual(out['account']['email'],'own@example.test');self.assertNotIn('secret',json.dumps(out));self.assertNotIn('OPENAI_API_KEY',args.kwargs['env']);self.assertNotIn('CODEX_API_KEY',args.kwargs['env'])
 def test_codex_identity_survives_quota_rpc_failure(self):
  with self.assertRaises(m.StatusError) as error:self.codex_reply({'type':'chatgpt','email':'own@example.test'},error=True)
  self.assertEqual(error.exception.account['email'],'own@example.test');self.assertNotIn('secret',error.exception.message)
 def test_display_rejects_control_characters(self):
  for text in ('x\n@example.test','x'*255,{},None):self.assertEqual(m.display_text(text),'')

 # Gateways: one that passes the harness's own login on (local-login) reads that login; the machine's default
 # gateway, as a run-ai run without a gateway flag takes it, with machine_default (2026-11-19)
 def login_read(self):
  return patch.object(self.task,'_selection',return_value=('id',lambda folder:{'available':True,'account':{'authType':'login','email':'own@example.test'},'windows':[{'usedPercent':10}]},'page'))
 def test_pass_through_gateway_reads_own_login(self):
  self.gateways={'local-login':'login'}
  with self.login_read():out=self.run_task(harness='claude',gateway='local-login')
  self.assertTrue(out['available']);self.assertTrue(out['own_login']);self.assertEqual(out['gateway'],'local-login');self.assertEqual(out['identity']['label'],'own@example.test')
 def test_pass_through_gateway_only_for_login_harnesses(self):
  self.gateways={'local-login':'login'}
  with patch.object(self.task,'_selection',side_effect=AssertionError('no login read')):out=self.run_task(harness='opencode',model='openai/x',gateway='local-login')
  self.assertEqual(out['reason'],'gateway');self.assertIn('claude and codex',out['message']);self.assertNotIn('own_login',out)
 def test_the_harnesses_declare_their_gateway_and_login_facts(self):
  # what each harness declares (cx task harnesses) over the tuples of before: a harness of one's own included
  mine={'name':'mine','takes':['gateway'],'declared':{'name':'mine','login_pass_through':True}}
  codex={'name':'codex','takes':['yes'],'declared':{'name':'codex','login_pass_through':False}}
  self.harnesses={'return':0,'harnesses':[mine,codex],'index':{'mine':mine,'codex':codex},'conflicts':{}}
  self.assertTrue(self.task._takes_gateway('mine'));self.assertTrue(self.task._passes_login('mine'))
  self.assertFalse(self.task._takes_gateway('codex'));self.assertFalse(self.task._passes_login('codex'))
  self.assertTrue(self.task._takes_gateway('opencode'));self.assertFalse(self.task._passes_login('opencode'))  # not declared: the tuples
 def test_key_gateway_named_without_secret(self):
  self.gateways={'company':'x-api-key (company-secret)','local':'none'}
  with patch.object(self.task,'_selection',side_effect=AssertionError('no login read')):
   key=self.run_task(harness='claude',gateway='company');free=self.run_task(harness='claude',gateway='local')
  self.assertIn('company with its key',key['message']);self.assertNotIn('company-secret',json.dumps(key));self.assertEqual(key['identity']['label'],'API')
  self.assertIn('without a key',free['message']);self.assertEqual(free['gateway'],'local')
 def test_unknown_gateway_said(self):
  with patch.object(self.task,'_selection',side_effect=AssertionError('no login read')):out=self.run_task(harness='claude',gateway='gone')
  self.assertEqual(out['reason'],'gateway');self.assertIn('not on this machine',out['message'])
 def test_machine_default_gateway(self):
  self.gateways={'company':'x-api-key (company-secret)','local-login':'login'}
  self.machine={'return':0,'gateway':'company','how':'config run_ai_gateway','general':True}
  with patch.object(self.task,'_selection',side_effect=AssertionError('no login read')):out=self.run_task(harness='claude',gateway='',machine_default=True)
  self.assertEqual((out['gateway'],out['gateway_how'],out['reason']),('company','config run_ai_gateway','gateway'))
  # The general default is not for a harness without gateway support: its own login, as run-ai
  with self.login_read():out=self.run_task(harness='vibe',gateway='',machine_default=True)
  self.assertEqual(out['gateway'],'login');self.assertIn('takes no gateway',out['gateway_how']);self.assertTrue(out['available'])
  self.machine={'return':0,'gateway':'local-login','how':'config run_ai_gateway_claude'}
  with self.login_read():out=self.run_task(harness='claude',gateway='',machine_default=True)
  self.assertTrue(out['own_login']);self.assertTrue(out['available'])
  self.machine={'return':16,'error':'not found'}
  with self.login_read():out=self.run_task(harness='claude',gateway='',machine_default=True)
  self.assertEqual(out['gateway'],'login');self.assertTrue(out['available'])
  self.machine={'return':1,'error':'broken config'}
  out=self.run_task(harness='claude',gateway='',machine_default=True)
  self.assertEqual(out['reason'],'gateway_unavailable');self.assertFalse(out['available'])
 def test_empty_gateway_stays_login_without_machine_default(self):
  self.machine={'return':0,'gateway':'company','how':'config run_ai_gateway'}
  with self.login_read():out=self.run_task(harness='claude',gateway='')
  self.assertEqual(out['gateway'],'login');self.assertNotIn('gateway_how',out);self.assertTrue(out['available'])
  self.assertEqual(self.run_task(harness='claude',machine_default='yes')['return'],1)

if __name__=='__main__':unittest.main(verbosity=2)
