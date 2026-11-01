"""Manufacturing tool decisions, saved transitions, and balanced workflow summaries."""
from collections import defaultdict
from copy import deepcopy
from .shopfloor import ManufacturingWorkflow,TOOLS


from .shopfloor_views import AgentView,public_task


def summary(results):
    families=defaultdict(list);disruptions=defaultdict(list)
    for r in results:families[r['family']].append(r);disruptions[r['disruption']].append(r)
    def group(rows):
        return dict(cases=len(rows),strict_successes=sum(r['strict_success'] for r in rows),
                    mean_score=sum(r['score'] for r in rows)/len(rows),critical_failures=sum(bool(r['critical_violations']) for r in rows))
    if not results:return dict(cases=0)
    return dict(**group(results),macro_family_strict_rate=sum(sum(r['strict_success'] for r in rows)/len(rows) for rows in families.values())/len(families),
                families={k:group(v) for k,v in sorted(families.items())},disruptions={k:group(v) for k,v in sorted(disruptions.items())})


def run(task,agent,checkpoint=None):
    world=ManufacturingWorkflow(task);last=None;error=None;view=AgentView();agent_trace=[]
    visible_task=public_task(task,view.episode_id)
    try:
        while not world.finished and len(world.trace)<task['max_tool_calls']:
            payload=dict(clock_minute=world.clock,calls_remaining=task['max_tool_calls']-len(world.trace),last_result=last)
            if not world.trace:payload.update(task=visible_task,tools=deepcopy(TOOLS))
            decision=agent.decide('workflow',payload)
            if set(decision)!={'tool','arguments'} or not isinstance(decision['tool'],str) or not isinstance(decision['arguments'],dict):raise ValueError('workflow decision requires tool and arguments fields')
            try:arguments=view.decode(decision['arguments'])
            except ValueError:
                last=dict(ok=False,error='unissued_identifier',clock_minute=world.clock)
                raise ValueError('agent used an identifier absent from business observations')
            raw=world.call(decision['tool'],**arguments)
            last=view.result(raw)
            agent_trace.append(dict(decision=deepcopy(decision),result=deepcopy(last)))
            if checkpoint:checkpoint(dict(task=visible_task,evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=deepcopy(agent_trace),status='running'))
    except (ValueError,OSError) as exc:error=type(exc).__name__
    result=dict(task=visible_task,evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=deepcopy(agent_trace),status='stopped' if error else 'finished' if world.finished else 'budget_exhausted')
    if error:result['error_type']=error
    if checkpoint:checkpoint(result)
    return result
