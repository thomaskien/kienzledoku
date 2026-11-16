"""Shared installer choices, independent of platform and private configuration."""
SERVER_ROLES = {'full': ('asr','diar','llm'), 'asr': ('asr','diar'),
                'llm': ('llm',), 'llm_diar': ('diar','llm'), 'diar': ('diar',)}
ASR_MODELS = ('large-v3','turbo-int8')
def roles(cfg):
    result=list(SERVER_ROLES[cfg.get('server_role','full')])
    if not cfg.get('diarization',True) and 'diar' in result: result.remove('diar')
    if cfg.get('remote_llm_url') and 'llm' not in result: result.append('llm')
    return tuple(result)
def local_role(cfg, role):
    return role in roles(cfg) and not cfg.get('remote_'+role+'_url')
