"""Use existing track contracts with the offline macOS agent boundary."""
from .isolation import isolated_agent

TRACKS=('workflow','supply-chain','procurement','sensors','cad','documents')


def contracts(track):
    if track=='workflow':
        from .shopfloor_cases import catalog
        from .shopfloor_runner import run,summary
        from .shopfloor import replay
    elif track=='supply-chain':
        from .supply_cases import catalog
        from .supply_chain import run,replay
        from .grading import summarize as summary
    elif track=='procurement':
        from .procurement_cases import catalog
        from .procurement import run,replay,summary
    elif track=='sensors':
        from .sensor_cases import catalog
        from .sensors import run,replay
        from .grading import summarize as summary
    elif track=='documents':
        from .document_cases import catalog
        from .documents import run,replay
        from .grading import summarize as summary
    elif track=='cad':
        from .cad_cases import catalog
        from .cad import run,replay,summary
    else:raise ValueError('unsupported offline isolation track')
    return catalog,run,replay,summary


def run_task(track,task,source,timeout=120,kernel_timeout=30,checkpoint=None):
    _,run,_,_=contracts(track)
    with isolated_agent(source,timeout,max_reply_bytes=7100000 if track=='cad' else 100000) as agent:
        if track=='cad':episode=run(task,agent,kernel_timeout)
        elif track=='documents':episode=run(task,agent)
        else:episode=run(task,agent,checkpoint)
        episode['isolation']=agent.isolation
    return episode


def replay_episode(track,task,episode):
    _,_,replay,_=contracts(track)
    if track in ('cad','documents'):return replay(task,episode)
    result=replay(task,episode['trace'])
    if result!=episode['result']:raise ValueError('isolated terminal replay mismatch')
    return result
