#!/usr/bin/env pypy3
import esprima
import sys
import config
import pickle
from interpreter import Interpreter
from debug import set_debug
import cProfile
import resource
from node_tools import mark_node_recursive, save_annotations
sys.setrecursionlimit(1000000)
resource.setrlimit(resource.RLIMIT_STACK, (2**29,-1))


set_debug(config.debug)
if (len(sys.argv) < 3):
    print("Usage: " + str(sys.argv[0]) + " <input JS file> <output Pickle file>")
    sys.exit(1)

print("\n======== Analysis Settings: =========")
print("Preserve possibly-undef:\t", config.use_or != [])
print("Unify before merge:\t\t", config.use_unify != [])
print("Use condition guards:\t\t", config.use_filtering_if != [])
print("Use exception guards:\t\t", config.use_filtering_err != [])
print("=====================================\n")

print("Opening input file:", sys.argv[1])
f = open(sys.argv[1], "r")
data = f.read()
f.close()

print("Parsing file into abstract syntax tree...")
ast = esprima.parse(data, options={ 'range': True})

print("Pre-processing...")
mark_node_recursive(ast)

i = Interpreter(ast, data)
cProfile.run("i.run()")
#i.run()

print("Producing out file...")
delattr(esprima.nodes.Object, "__getattr__") # To allow pickling
f = open(sys.argv[2], "wb")
pickle.dump((ast, save_annotations()), f)
f.close()
print("All done.")

