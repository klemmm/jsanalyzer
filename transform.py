#!/usr/bin/env pypy3
import esprima
import sys
import re
import config
import pickle
import json
import code_transformers
import argparse
sys.setrecursionlimit(1000000)

parser = argparse.ArgumentParser()
parser.add_argument("--no-simplify-expr", help="Disable simplify expressions", action='store_true')
parser.add_argument("--no-simplify-calls", help="Disable simplify function calls", action='store_true')
parser.add_argument("--no-simplify-flow", help="Disable simplify control flow", action='store_true')
parser.add_argument("--no-remove-dead-code", help="Disable remove dead code", action='store_true')
parser.add_argument("--no-eval-handling", help="Disable eval() and Function.constructor() handling", action='store_true')
parser.add_argument("--no-rename-variable", help="Disable variable renaming", action='store_true')
parser.add_argument("--no-constant-member-rewrite", help="Do not rewrite constant member access", action='store_true')
parser.add_argument("--pure", help="comma-separated list of pure functions")
parser.add_argument("input", help="input file")
parser.add_argument("output", help="output file")
args = parser.parse_args()

print("\n======== Transform Settings: ========")
print("Simplify expressions:\t\t", not args.no_simplify_expr)
print("Simplify function calls:\t", not args.no_simplify_calls)
print("Simplify control flow:\t\t", not args.no_simplify_flow)
print("Remove dead code:\t\t", not args.no_remove_dead_code)
print("Rename variables:\t\t", not args.no_rename_variable)
print("Handle eval() / fn cons: \t", not args.no_eval_handling)
print("Rewrite constant member access:\t", not args.no_constant_member_rewrite)
print("=====================================\n")

if args.pure is not None:
    print("Additional pure functions:", args.pure)
    print("")

print("Opening input file:", args.input)
f = open(args.input, "rb")
ast = pickle.load(f)
f.close()

#Order matters, because some transformers will introduce some code that will be processed by other transformers
#code_transformers.EvalReplacer(ast).run()
#code_transformers.LoopUnroller(ast).run()
#code_transformers.FunctionInliner(ast).run()
#code_transformers.DeadCodeRemover(ast).run()
#code_transformers.VariableRenamer(ast).run()
code_transformers.VarDefInterpreter(ast).run()
code_transformers.UselessVarRemover(ast).run()
if args.pure is not None:
    pures = args.pure.split(',')
else:
    pures = []
#code_transformers.ExpressionSimplifier(ast,pures).run()
#code_transformers.ConstantMemberSimplifier(ast).run()

print("Producing JSON output file:", args.output)
def myserializer(obj):
    if isinstance(obj, re.Pattern):
        return None
    return {k: v for k, v in obj.__dict__.items() if not (k.startswith('noout_') or k.startswith('notrans_'))}

json_data = json.dumps(ast, default=myserializer)
f = open(args.output, "w")
f.write(json_data)
f.close()

