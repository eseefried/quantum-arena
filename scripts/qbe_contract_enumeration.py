import ast,itertools,json,re,operator
from pathlib import Path
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Eq:operator.eq,ast.LtE:operator.le,ast.GtE:operator.ge}
def evaluate(n,env):
 if isinstance(n,ast.Expression):return evaluate(n.body,env)
 if isinstance(n,ast.Name):return env[n.id]
 if isinstance(n,ast.Constant) and type(n.value) in (int,float):return n.value
 if isinstance(n,ast.BinOp):return OPS[type(n.op)](evaluate(n.left,env),evaluate(n.right,env))
 if isinstance(n,ast.Compare):
  values=[evaluate(v,env) for v in [n.left,*n.comparators]]
  return all(OPS[type(op)](a,b) for op,a,b in zip(n.ops,values,values[1:]))
 raise ValueError(ast.dump(n))
def enumerate_task(t):
 field=next(k for k in ['priority','scientific_value','urgency_score','slot1_fidelity','revenue','performance_score','operational_cost','value'] if k in t['resources'][0])
 expressions=[c['expression'] for c in t['constraints'] if 'expression' in c]
 def normalize(s):
  s=s.split(' (equivalently')[0];s=re.sub(r'(?<![<>=])=(?!=)','==',s);return re.sub(r'(\d)(x\d+)',r'\1*\2',s)
 trees=[ast.parse(normalize(s),mode='eval') for s in expressions]
 rows=[]
 for bits in itertools.product((0,1),repeat=t['num_variables']):
  env={f'x{i+1}':x for i,x in enumerate(bits)}
  if all(evaluate(tree,env) for tree in trees):rows.append((sum(r[field]*x for r,x in zip(t['resources'],bits)),[i+1 for i,x in enumerate(bits) if x]))
 best=(min if field=='operational_cost' else max)(v for v,s in rows)
 return {'objective_field':field,'optimum':best,'optimal_selections':[s for v,s in rows if v==best],'feasible_assignments':len(rows),'constraint_expressions':expressions}
if __name__=='__main__':
 for t in json.load(open('qbe_export/datasets/QuantumBenchEval_T2.json'))['tasks']:print(t['task_id'],enumerate_task(t))
