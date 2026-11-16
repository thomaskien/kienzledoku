"""Additive v1.8 endpoints. Existing endpoints keep their own validation."""
import math

from .benchmark import VERSION, choices, inventory, cache_metadata
from .errors import Busy, CommanderError, InvalidRequest

SESSION_HEADER = 'X-Kienzledoku-Benchmark-Session'


def context(commander):
    cfg=commander.settings
    return dict(source='local_commander', roles=[r for r in cfg.enabled_roles if (r!='llm' or not cfg.remote_llm_url) and (r!='diar' or not cfg.remote_diar_url)],
                remote_llm_url=cfg.remote_llm_url or None, remote_diar_url=cfg.remote_diar_url or None, gpu_index=cfg.gpu_index,
                commander_version=VERSION)


def capabilities(commander):
    cfg=commander.settings
    return dict(schema_version=1, commander_version=VERSION, api_version='1.8',
        hardware_inventory=True, current_temperatures=True, temperature_history=False,
        benchmark_control=True, benchmark_unavailable_reason=None,
        benchmark_authentication='configured_commander_bearer_token' if cfg.auth_enabled else 'none',
        benchmark_roles=[r for r in cfg.enabled_roles if r=='asr' or (r=='llm' and not cfg.remote_llm_url)],
        benchmark_modes=['serial','parallel'], parallel_requires_approved_model_profile=True,
        raw_prompt=True, streaming=False, ttft=False, verified_cold_filesystem_cache=False,
        benchmark_active=commander._benchmark is not None,
        effective_settings=dict(memory_mode=cfg.memory_mode,asr_on_demand=cfg.asr_on_demand,
            diarization_mode=cfg.diarization_mode,resident_quality=cfg.baseline_llm,
            cache=cache_metadata(cfg)),context=context(commander))


def raw_llm(value):
    allowed={'model_id','request_id','messages','temperature','max_tokens','top_p','top_k','min_p','repeat_penalty','seed','response_format'}
    if set(value)-allowed:raise InvalidRequest()
    messages=value.get('messages')
    if not isinstance(messages,list) or not 1<=len(messages)<=256:raise InvalidRequest()
    for message in messages:
        if (not isinstance(message,dict) or set(message)!={'role','content'} or
            message['role'] not in ('system','user','assistant') or not isinstance(message['content'],str)):
            raise InvalidRequest()
    if not any(m['role']=='user' and m['content'].strip() for m in messages):raise InvalidRequest()
    bounds={'temperature':(0,2),'max_tokens':(1,32768),'top_p':(0,1),'top_k':(0,200),
            'min_p':(0,1),'repeat_penalty':(0,2),'seed':(-1,2147483647)}
    for key,(low,high) in bounds.items():
        if key not in value:continue
        v=value[key]
        if type(v) not in (float,int) or not math.isfinite(v) or not low<=v<=high:raise InvalidRequest()
        if key in ('max_tokens','top_k','seed') and type(v) is not int:raise InvalidRequest()
    if 'response_format' in value and value['response_format']!={'type':'json_object'}:raise InvalidRequest()
    payload={k:v for k,v in value.items() if k not in ('model_id','request_id')}
    payload.setdefault('max_tokens',1600)
    return payload


def dispatch(handler, path, post):
    server=handler.server;cmd=server.commander;cfg=cmd.settings
    metadata=('/v1/runtime/hardware','/v1/runtime/temperatures','/v1/runtime/inventory','/v1/runtime/capabilities')
    if not post and path in metadata:
        if not server.hardware_slots.acquire(blocking=False):raise Busy()
        try:
            if path.endswith('/hardware'):
                locations=[(e['_path'],'llm:'+e['id']) for e in choices(cfg) if not cfg.remote_llm_url]
                locations += [(p,role) for role,p in [('asr',cfg.asr_model_path),('diar',cfg.diar_model_path)] if p and role in cfg.enabled_roles]
                model_paths=list(dict.fromkeys(p for p,_ in locations))
                value=server.hardware.inventory(model_paths)
                for volume in value['storage']:
                    if volume['role'].startswith('model:'):
                        index=int(volume['role'].split(':')[1])
                        volume['models']=[label for p,label in locations if p==model_paths[index]]
                for gpu in value['gpus']:
                    gpu['selected_for_llm']=gpu.get('id')=='nvidia:'+str(cfg.gpu_index) if cfg.platform=='linux' else None
            elif path.endswith('/temperatures'):value=server.hardware.temperatures()
            elif path.endswith('/inventory'):value=dict(schema_version=1,models=inventory(cfg,cmd.status()['loaded']['llm']))
            else:value=capabilities(cmd)
            value['context']=context(cmd)
            if not handler.headers.get('X-Kienzledoku-Commander-Hop'):
                fetched = {}
                for role in ('llm', 'diar'):
                    target = getattr(cfg, 'remote_'+role+'_url')
                    if not target or role not in cfg.enabled_roles:
                        continue
                    # One query per configured target, using only its own configured token.
                    key = target.rstrip('/').lower()
                    if key not in fetched:
                        try:
                            remote = cmd.runtime._http(target.rstrip('/')+path,timeout=cfg.metadata_timeout,
                                token=__import__('os').environ.get(getattr(cfg,'remote_'+role+'_token_env')),
                                extra_headers={'X-Kienzledoku-Commander-Hop':'1'})
                            fetched[key] = dict(source=target,data=remote,status='available')
                        except CommanderError:
                            fetched[key] = dict(source=target,data=None,status='unavailable',reason='remote_query_failed')
                    value['remote_'+role] = fetched[key]
            return True,value
        finally:server.hardware_slots.release()
    if not path.startswith('/v1/benchmark/'):return False,None
    # Authentication is handled uniformly by Handler._auth; token protection is optional.
    session=handler.headers.get(SESSION_HEADER)
    if not post and path=='/v1/benchmark/session':return True,cmd.benchmark_status(session)
    if not post and path.startswith('/v1/benchmark/jobs/'):
        return True,cmd.benchmark_job(session,path.removeprefix('/v1/benchmark/jobs/'))
    if post and path=='/v1/benchmark/session':
        value=handler._json()
        if set(value)-{'model_id','mode','lease_seconds'} or 'model_id' not in value or 'mode' not in value:raise InvalidRequest()
        return True,cmd.benchmark_begin(value['model_id'],value['mode'],value.get('lease_seconds',120))
    if post and path in ('/v1/benchmark/session/keepalive','/v1/benchmark/session/end'):
        if handler._json():raise InvalidRequest()
        return True,(cmd.benchmark_keepalive(session) if path.endswith('/keepalive') else cmd.benchmark_end(session))
    if post and path=='/v1/benchmark/chat/completions':
        value=handler._json();payload=raw_llm(value)
        with cmd._condition:
            b=cmd._benchmark_require(session)
            if value.get('model_id')!=b['model_id']:raise InvalidRequest()
            quality=b['quality']
        request_id=handler._id(value.get('request_id'))
        if not request_id:raise InvalidRequest()
        job=cmd.submit('llm',{'llm':payload},quality,request_id,benchmark_session=session)
        return True,job.future.result()
    if post and path=='/v1/benchmark/asr/final-block':
        if handler.headers.get_content_type()!='multipart/form-data' or not handler._id():raise InvalidRequest()
        payload={'body':handler._body(256*1024*1024),'content_type':handler.headers.get('Content-Type'),'query':''}
        job=cmd.submit('asr',payload,request_id=handler._id(),benchmark_session=session)
        return True,job.future.result()
    raise InvalidRequest()
