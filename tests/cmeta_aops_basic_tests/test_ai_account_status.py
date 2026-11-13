"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Hermetic account-status regressions: fake credentials/provider replies only,
with no network, inference, real login reads or changes to a developer's cMeta home.
"""
import json
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
base_import = 'from task_c36be4b9314a45e0.api.ctask import InitCTask'
assert base_import in source
m = types.ModuleType('ai_account_status_under_test')
m.__file__ = str(path)
exec(compile(source.replace(base_import, 'InitCTask = object'), str(path), 'exec'), m.__dict__)

class Tests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
  self.task=object.__new__(m.CTask);self.task.cmeta={'uses_categories':{'task':'task','log':'log'}}
  class FakeCM:
   def access(_,params):
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
  self.assertEqual(identity,'env-secret');read.assert_called_once_with('env-secret','')
 def test_custom_claude_directory(self):
  with patch.dict(os.environ,{'CLAUDE_CONFIG_DIR':str(self.root)},clear=True),patch.object(m,'read_json',return_value={'claudeAiOauth':{'accessToken':'file-secret','subscriptionType':'pro'}}) as read:
   identity,fetch,page=self.task._selection('claude','')
  self.assertEqual(identity,'file-secret');self.assertEqual(read.call_args.args[0],self.root/'.credentials.json')
 def test_opencode_uses_own_account(self):
  with patch.object(m,'read_json',return_value={'openai':{'type':'oauth','access':'opencode-secret','accountId':'account'}}),patch.object(m,'openai_usage',return_value={'available':True}) as read:
   identity,fetch,page=self.task._selection('opencode','openai/model');fetch(self.root)
  read.assert_called_once_with('opencode-secret','account')
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

if __name__=='__main__':unittest.main(verbosity=2)
