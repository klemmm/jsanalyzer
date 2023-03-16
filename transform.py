#!/usr/bin/env pypy3
import esprima
import sys
import re
import config
import pickle
import json
import code_transformers
import argparse
import resource
from node_tools import mark_node_recursive, load_annotations

resource.setrlimit(resource.RLIMIT_STACK, (2**29,-1))
sys.setrecursionlimit(1000000)

parser = argparse.ArgumentParser()
parser.add_argument("--no-simplify-expr", help="Disable simplify expressions", action='store_true')
parser.add_argument("--no-simplify-calls", help="Disable simplify function calls", action='store_true')
parser.add_argument("--no-simplify-flow", help="Disable simplify control flow", action='store_true')
parser.add_argument("--no-remove-dead-code", help="Disable remove dead code", action='store_true')
parser.add_argument("--no-eval-handling", help="Disable eval() and Function.constructor() handling", action='store_true')
parser.add_argument("--no-rename-variable", help="Disable variable renaming", action='store_true')
parser.add_argument("--no-constant-member-rewrite", help="Do not rewrite constant member access", action='store_true')
parser.add_argument("--no-remove-dead-variables", help="Disable remove dead variable", action='store_true')
parser.add_argument("--no-remove-useless-statements", help="Disable removing no-effects statements", action='store_true')
parser.add_argument("--debug-dead-variables", help="Turn on dead-variable remover debugging", action='store_true')
parser.add_argument("--pure", help="comma-separated list of pure functions")
parser.add_argument("--simplify-undef", help="Simplify possibly-undef expressions (UNSOUND)", action='store_true')
parser.add_argument("--always-unroll", help="Always unroll loops when possible", action='store_true')

parser.add_argument("input", help="input file")
parser.add_argument("output", help="output file")
args = parser.parse_args()

print("\n======== Transform Settings: ========")
print("Simplify expressions:\t\t", not args.no_simplify_expr)
print("Simplify function calls:\t", not args.no_simplify_calls)
print("Simplify control flow:\t\t", not args.no_simplify_flow)
print("Remove dead code:\t\t", not args.no_remove_dead_code)
print("Remove dead variables:\t\t", not args.no_remove_dead_variables)
print("Remove useless statements:\t", not args.no_remove_useless_statements)
print("Rename variables:\t\t", not args.no_rename_variable)
print("Handle eval() / fn cons: \t", not args.no_eval_handling)
print("Rewrite constant member access:\t", not args.no_constant_member_rewrite)
print("Simplify undef expressions:\t", args.simplify_undef)
print("=====================================\n")

if args.pure is not None:
    print("Additional pure functions:", args.pure)
    print("")



print("Opening input file:", args.input)
f = open(args.input, "rb")
(ast, annotation_state) = pickle.load(f)
f.close()

load_annotations(*annotation_state)

if args.pure is not None:
    pures = args.pure.split(',')
else:
    pures = []

print("Pre-processing...")
mark_node_recursive(ast)

#Order matters, because some transformers will introduce some code that will be processed by other transformers
if not args.no_eval_handling:
    code_transformers.EvalReplacer(ast).run()

if not args.no_remove_dead_code:
    code_transformers.DeadCodeRemover(ast).run()

if not args.no_simplify_expr:
    code_transformers.ExpressionSimplifier(ast, pures, args.simplify_undef).run()

if not args.no_remove_dead_variables:
    code_transformers.UselessVarRemover(ast, args.debug_dead_variables).run()
    code_transformers.SideEffectMarker(ast, pures).run()

if not args.no_remove_useless_statements:
    code_transformers.SideEffectMarker(ast, pures).run()
    code_transformers.UselessStatementRemover(ast).run()

if not args.no_constant_member_rewrite:
    code_transformers.ConstantMemberSimplifier(ast).run()


if not args.no_simplify_flow: #Breaks call target annotations (FIXME TODO)
    code_transformers.LoopUnroller(ast, args.always_unroll).run()

if not args.no_simplify_calls: #May break contextual static values loop id
    inliner = code_transformers.FunctionInliner(ast)
    while True:
        inliner.set_count(0)
        inliner.run()
        if inliner.get_count() == 0:
            break  
      
if not args.no_simplify_expr:
    code_transformers.ExpressionSimplifier(ast, pures, args.simplify_undef).run()

if not args.no_remove_dead_variables:
    code_transformers.UselessVarRemover(ast, args.debug_dead_variables).run()
    code_transformers.SideEffectMarker(ast, pures).run()

if not args.no_remove_useless_statements:
    code_transformers.SideEffectMarker(ast, pures).run()
    code_transformers.UselessStatementRemover(ast).run()

if not args.no_rename_variable: #After inliner, because variable renaming breaks call target formal args name (FIXME TODO)
    code_transformers.VariableRenamer(ast).run()

print("Producing JSON output file:", args.output)
def myserializer(obj):
    if isinstance(obj, re.Pattern):
        return None
    return {k: v for k, v in obj.__dict__.items() if not (k.startswith('noout_') or k.startswith('notrans_'))}

json_data = json.dumps(ast, default=myserializer)
f = open(args.output, "w")
f.write(json_data)
f.close()

