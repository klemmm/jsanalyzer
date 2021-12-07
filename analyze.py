#!/usr/bin/env pypy3
import esprima
import sys
import config
from interpreter import Interpreter
from output import Output
from debug import set_debug

set_debug(config.debug)
if (len(sys.argv) < 3):
    print("Usage: " + str(sys.argv[0]) + " <input JS file> <output JS file>")
    sys.exit(1)

print("Opening input file:", sys.argv[1])
f = open(sys.argv[1], "r")
data = f.read()
f.close()

print("Parsing file into abstract syntax tree...")
ast = esprima.parse(data)

i = Interpreter(ast)
i.run()

print("Producing output file:", sys.argv[2])
f = open(sys.argv[2], "w")
o = Output(ast, f)
o.dump()
f.close()

