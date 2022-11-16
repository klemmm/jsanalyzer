from abstract import JSPrimitive, JSRef
from config import regexp_rename, rename_length
import re
EXPRESSIONS = ["BinaryExpression", "UnaryExpression", "Identifier", "CallExpression", "Literal", "NewExpression", "UpdateExpression", "ConditionalExpression", "NewExpression", "ThisExpression", "AssignmentExpression", "MemberExpression", "ObjectExpression", "ArrayExpression", "LogicalExpression", "FunctionExpression", "ArrowFunctionExpression"]

import random
random.seed(42)
first=['b','ch','d','f','g','l','k', 'm','n','p','r','t','v','x','z']
second=['a','e','o','u','i','au','ou']

def generate(n):
    name = ""
    for i in range(n):
        name += random.choice(first)
        name += random.choice(second)
    return name

class Output(object):
    def __init__(self, ast, f):
        self.INDENT = 2
        self.indent = 0
        self.ast = ast
        self.f = f
        self.renamed = {}

    def rename(self, name):
        if name is None:
            return "NONE"
        for r in regexp_rename:
            if re.match(r, name) is not None:
                if name in self.renamed.keys():
                    return self.renamed[name]
                newname = generate(rename_length)
                self.renamed[name] = newname
                return newname
        return name
    
    def out(self, *args, **kwargs):
        kwargs['file'] = self.f
        print(*args, **kwargs)

    def dump(self):
        self.do_prog(self.ast.body)

    def print_literal(self, literal):
        if type(literal) == str:
            self.out('"' + literal + '"', end="")
        elif type(literal) == bool:
            if literal:
                self.out("true", end="")
            else:
                self.out("false", end="")
        elif type(literal) == int:
            self.out(str(literal), end="")
        else:
            self.out("undefined", end="")
        return

    def do_expr_or_statement(self, exprstat, simplify=True, end="\n"):
        if exprstat.type in EXPRESSIONS:
            self.do_expr(exprstat, simplify)
        else:
            self.do_statement(exprstat, end)

    def do_expr(self, expr, simplify=True):
        if simplify and (expr.static_value is not None and isinstance(expr.static_value, JSPrimitive)):
            self.print_literal(expr.static_value.val)
        
        elif expr.type == "Literal":
            self.print_literal(expr.value)

        elif expr.type == "Identifier":
            self.out(self.rename(expr.name), end="")
            pass

        elif expr.type == "NewExpression":
            self.out("new ", end="")
            self.do_expr(expr.callee)
            self.out("(", end="")
            first = True
            for argument in expr.arguments:
                if not first:
                    self.out(", ", end="")
                first = False
                self.do_expr(argument)
            self.out(")", end="")

        elif expr.type == "ConditionalExpression":
            self.out(" ( ", end="")
            self.do_expr(expr.test)
            self.out(" ? ", end="")
            self.do_expr(expr.consequent)
            self.out(" : ", end="")
            self.do_expr(expr.alternate)
            self.out(" ) ", end="")

        elif expr.type == "ThisExpression":
            self.out("this", end="")

        elif expr.type == "SequenceExpression":
            first = True
            for e in expr.expressions:
                if not first:
                    self.out(", ", end="")
                first = False
                self.do_expr(e)

        elif expr.type == "AssignmentExpression":
            if expr.left.type == "Identifier":
                self.out(self.rename(expr.left.name) + " " + expr.operator + " ", end="")
            else: #MemberExpression
                glob = isinstance(expr.left.object.static_value, JSRef) and expr.left.object.static_value.target() == 0
                prefix = ""
                if not glob:
                    self.do_expr(expr.left.object)
                    prefix = "."
                if expr.left.computed:
                    if isinstance(expr.left.property.static_value, JSPrimitive) and type(expr.left.property.static_value.val) is str:
                        self.out(prefix + expr.left.property.static_value.val, end="")
                    else:
                        self.out("[", end="")
                        self.do_expr(expr.left.property)
                        self.out("]", end="")
                else:
                    self.out(prefix + expr.left.property.name, end="")
                self.out(" " + expr.operator + " ", end="")

            self.do_expr(expr.right)

        elif expr.type == "ObjectExpression":
            self.out("{")
            self.indent += self.INDENT
            first = True
            for prop in expr.properties:
                if not first:
                    self.out(", ")
                first = False
                self.out(" "*self.indent, end="")
                if prop.computed:
                    self.do_expr(prop.key)
                else:
                    if prop.type == "Property":
                        self.out(prop.key.value, end="")
                        self.out(": ", end="")
                        self.do_expr(prop.value)
                    else:
                        self.out("<???>") #TODO

            self.indent -= self.INDENT
            self.out("\n}")

        elif expr.type == "ArrayExpression":
            self.out("[", end="")
            first = True
            for elem in expr.elements:
                if not first:
                    self.out(", ", end="")
                first = False
                self.do_expr(elem)
            self.out("]", end="")

        elif expr.type == "MemberExpression":
            glob = isinstance(expr.object.static_value, JSRef) and expr.object.static_value.target() == 0
            prefix = ""
            if not glob:
                self.do_expr(expr.object)
                prefix = "."
            if expr.computed:
                if isinstance(expr.property.static_value, JSPrimitive) and type(expr.property.static_value.val) is str:
                    self.out(prefix + expr.property.static_value.val, end="")
                else:
                    self.out("[", end="")
                    self.do_expr(expr.property)
                    self.out("]", end="")
            else:
                self.out(prefix + expr.property.name, end="")

        elif expr.type == "UnaryExpression":
            self.out(expr.operator, end="")
            if expr.operator.isalpha():
                self.out(" ", end="")
            self.do_expr(expr.argument)

        elif expr.type == "BinaryExpression":
            self.do_expr(expr.left)
            self.out(" ", end="")
            self.out(expr.operator, end="")
            self.out(" ", end="")
            self.do_expr(expr.right)

        elif expr.type == "LogicalExpression":
            self.do_expr(expr.left)
            self.out(" ", end="")
            self.out(expr.operator, end="")
            self.out(" ", end="")
            self.do_expr(expr.right)

        elif expr.type == "FunctionExpression":
            first = True
            params = ""
            for a in expr.params:
                if first:
                    first = False
                else:
                    params += ", "
                params += self.rename(a.name)
            self.out(self.indent*" " + "function(" + params + ")")
            #self.out("/* PURE: " + str(expr.body.pure) + " REDEX: " + str(expr.body.redex) + " */")
            self.do_statement(expr.body)

        elif expr.type == "ArrowFunctionExpression":
            first = True
            params = ""
            for a in expr.params:
                if first:
                    first = False
                else:
                    params += ", "
                params += self.rename(a.name)
            self.out(self.indent*" " + "function(" + params + ")")
            self.do_statement(expr.body)

        elif expr.type == "CallExpression":
            if expr.reduced is not None:
                #print("reduced2:")
                #print(expr.reduced)
                self.do_expr(expr.reduced)
                return
            self.do_expr(expr.callee)
            self.out("(", end="")
            first = True
            for argument in expr.arguments:
                if not first:
                    self.out(", ", end="")
                first = False
                self.do_expr(argument)
            self.out(")", end="")

        elif expr.type == "UpdateExpression":
            self.out("(", end="")
            self.do_expr(expr.argument, simplify=False)
            self.out(")" + expr.operator, end="")

        else:
            self.out(expr)
            raise ValueError("Expr type not handled: " + expr.type)

    def do_statement(self, statement, end="\n"):
        if statement.dead_code is True:
            self.out((self.indent)*" " + "{");
            self.out((self.indent+self.INDENT)*" " + "/* Dead Code */")
            self.out((self.indent)*" " + "}");
        elif statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.out(self.indent*" " + "var " + self.rename(decl.id.name), end="")
                if decl.init is not None:
                    self.out(" = ", end="")
                    self.do_expr(decl.init)
                self.out("", end=end)

        elif statement.type == "ExpressionStatement":
            self.out(" "*self.indent, end="")
            self.do_expr(statement.expression, simplify=False)
            self.out("", end=end)

        elif statement.type == "IfStatement":
            self.out(self.indent*" " + "if (", end="")
            self.do_expr(statement.test)
            self.out(")", end="")
            self.do_statement(statement.consequent)
            if statement.alternate is not None:
                self.out(self.indent*" " + "else")
                self.do_statement(statement.alternate)

        elif statement.type == "FunctionDeclaration":
            first = True
            params = ""
            for a in statement.params:
                if first:
                    first = False
                else:
                    params += ", "
                params += self.rename(a.name)
            self.out(self.indent*" " + "function " + self.rename(statement.id.name) + "(" + params + ")")
            #self.out("/* PURE: " + str(statement.body.pure) + " REDEX: " + str(statement.body.redex) + " */")
            self.do_statement(statement.body)
       
        elif statement.type == "ReturnStatement":
            self.out(self.indent*" " + "return ", end="")
            if statement.argument is not None:
                self.do_expr(statement.argument)

        elif statement.type == "WhileStatement":
            self.out(self.indent*" " + "while (", end="")
            self.do_expr(statement.test)
            self.out(")")
            self.do_statement(statement.body)
        
        elif statement.type == "BreakStatement":
            self.out(self.indent*" " + "break")

        elif statement.type == "ContinueStatement":
            self.out(self.indent*" " + "continue")

        elif statement.type == "TryStatement":
            self.out(self.indent*" " + "try ")
            self.do_statement(statement.block)
            self.out(self.indent*" " + "catch { /* NOT SUPPORTED */}")
        
        elif statement.type == "BlockStatement":
            self.out(self.indent*" " + "{")
            self.indent += self.INDENT
            for statement in statement.body:
                self.do_statement(statement)
            self.indent -= self.INDENT
            self.out(self.indent*" " + "}")
        
        elif statement.type == "EmptyStatement":
            pass
        
        elif statement.type == "ForStatement":
            self.out(self.indent*" " + "for(", end="")
            self.do_expr_or_statement(statement.init, simplify=False, end="")
            self.out("; ", end="")
            self.do_expr(statement.test)
            self.out("; ", end="")
            self.do_expr_or_statement(statement.update, simplify=False, end="")
            self.out("; ", end="")
            self.out(")")
            self.do_statement(statement.body)
        
        elif statement.type == "ForOfStatement":
            self.out(self.indent*" " + "ForOfStatement;")

        elif statement.type == "SwitchStatement":
            self.out(self.indent*" " + "switch (", end="")
            self.do_expr(statement.discriminant)
            self.out(") {")
            self.indent += self.INDENT
            for case in statement.cases:
                self.out(self.indent*" ", end="")
                self.do_expr(case.test)
                self.out(": ", end="")
                self.indent += self.INDENT
                for statement in case.consequent:
                    self.do_statement(statement)
                self.indent -= self.INDENT
            self.indent -= self.INDENT
            self.out(self.indent*" " + "}")

        else:
            raise ValueError("Statement type not handled: " + statement.type)
    def do_prog(self, prog):
        for statement in prog:
            self.do_statement(statement)
