"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

set-ai-gateway - login or a gateway for an AI harness (README.md). The dependency of run-claude, run-codex,
run-opencode and run-ai: it makes the choice - the flag, the project's _desc.yaml, this machine's config, else the
tool's own login - and, for a gateway, asks the ai.gateway category what the harness needs (the environment, the
extra words, the model). Never cached: a key passes through its result, into the environment of the harness only.
"""

from task_c36be4b9314a45e0.api.ctask import InitCTask

CONFIG_CATEGORY = 'config,cc6bfe174be847ed'
CONFIG_ARTIFACT = 'default'
GATEWAY_CATEGORY = 'ai.gateway,ae1ae632e0ec4f75'

# the keys of config::default: the general default, the gateway it means, and one per harness (login | <alias>)
CONFIG_ON = 'run_ai_gateway'
CONFIG_NAME = 'run_ai_gateway_name'
CONFIG_HARNESS = 'run_ai_gateway_'

LOGIN = 'login'
TRUE_WORDS = ('true', 'yes', 'on', '1')


def _truthy(v):
    return v is True or str(v).strip().lower() in TRUE_WORDS


def _bare(v):
    """A flag given without a value (-gw): True from the CLI, or an empty word."""
    return v is True or str(v).strip().lower() in ('', 'true')


class CTask(InitCTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    def _config(self):
        """The keys of config::default (cx config set default --meta.run_ai_gateway=true ...), or {}."""
        try:
            r = self.cm.access({'category': CONFIG_CATEGORY, 'command': 'read', 'arg1': CONFIG_ARTIFACT, 'con': False})
            cfg = r.get('config_cmeta', {}) if r.get('return', 1) == 0 else {}
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    def choose(self, harness, gateway = '', gw = '', ln = False, project = ''):
        """-> (the gateway alias or 'login', how it was chosen, an error or '')."""
        harness = str(harness or '').strip().lower()
        if ln:
            return LOGIN, 'the flag -ln', ''
        named = str(gateway or '').strip()
        if not named and gw not in (None, False, '', 'False', 'false'):
            named = '' if _bare(gw) else str(gw).strip()
            if not named:
                cfg = self._config()
                named = str(cfg.get(CONFIG_NAME) or '').strip()
                if not named:
                    return '', '', '-gw asks for the configured gateway, but config::default has no %s (cx config set default --meta.%s=<alias>)' % (CONFIG_NAME, CONFIG_NAME)
                return named, 'the flag -gw (config %s)' % CONFIG_NAME, ''
        if named:
            return (LOGIN if named.lower() == LOGIN else named), 'the flag --gateway', ''
        if str(project or '').strip():
            p = str(project).strip()
            return (LOGIN if p.lower() == LOGIN else p), "the project's _desc.yaml (ai_gateway)", ''
        cfg = self._config()
        if harness and cfg.get(CONFIG_HARNESS + harness):
            v = str(cfg[CONFIG_HARNESS + harness]).strip()
            return (LOGIN if v.lower() == LOGIN else v), 'config %s%s' % (CONFIG_HARNESS, harness), ''
        if _truthy(cfg.get(CONFIG_ON)):
            name = str(cfg.get(CONFIG_NAME) or '').strip()
            if not name:
                return '', '', 'config::default has %s on but no %s (cx config set default --meta.%s=<alias>)' % (CONFIG_ON, CONFIG_NAME, CONFIG_NAME)
            return name, 'config %s' % CONFIG_ON, ''
        return LOGIN, 'the default', ''

    def run(self,
            ctx: dict,
            harness: str = '',      # claude | codex | opencode | ... (the caller's name)
            gateway: str = '',      # an ai.gateway alias, or "login" (the tool's own account); empty: the project, the config, else login
            gw: str = '',           # the configured gateway (bare -gw), or an alias (-gw=<alias>)
            ln: bool = False,       # the tool's own login, whatever the config says (-ln)
            project: str = '',      # what the project's _desc.yaml says (ai_gateway: <alias> | login) - run-ai passes it
            model: str = '',        # the model the caller wants (empty: the gateway's default for this harness)
            connect: bool = True,   # for a gateway: also what the harness needs (environment, words, model); off = the choice only
    ):
        """
        Login or a gateway for an AI harness: the choice (flag > the project's _desc.yaml > config::default
        run_ai_gateway_<harness> > run_ai_gateway + run_ai_gateway_name > login), then, for a gateway, what the
        harness needs from the ai.gateway category.

            cx task run set-ai-gateway --harness=claude                    # the choice this machine makes, and the environment it means
            cx task run set-ai-gateway --harness=codex -gw                 # the configured gateway
            cx task run set-ai-gateway --harness=opencode --gateway=llama-cpp-local --connect-
        """
        con = ctx['control'].get('con', False)
        harness = str(harness or '').strip().lower()
        choice, how, err = self.choose(harness, gateway, gw, ln, project)
        if err:
            return self.cm.error(err)
        out = {'return': 0, 'harness': harness, 'gateway': choice, 'how': how}
        if choice == LOGIN or not connect:
            if con:
                print('AI gateway: %s (%s)' % (choice, how))
            return out
        if not harness:
            return self.cm.error('--harness=<claude|codex|opencode> is needed to connect to the gateway "%s"' % choice)
        r = self.cm.access({'category': GATEWAY_CATEGORY, 'command': 'connect', 'arg1': choice, 'harness': harness,
                            'model': model, 'con': False})
        if r.get('return', 1) > 0:
            return self.cm.error('gateway "%s" for %s: %s' % (choice, harness, r.get('error', 'cannot connect')))
        for k in ('env', 'args', 'model', 'wire', 'notes', 'opencode_config', 'base_url', 'provided_by'):
            if k in r:
                out[k] = r[k]
        if con:
            print('AI gateway: %s (%s) - the %s wire of %s; model %s' % (choice, how, out.get('wire', ''), out.get('base_url', ''),
                                                                       out.get('model') or 'the harness decides'))
            print('  environment: ' + (', '.join(sorted(out.get('env') or {})) or 'nothing'))
            if out.get('args'):
                print('  words: ' + ' '.join(out['args']))
            for n in out.get('notes') or []:
                print('  note: ' + n)
        return out
