from abstract import JSPrimitive, JSRef, JSUndefNaN
from config import regexp_rename, rename_length, simplify_expressions, simplify_function_calls, simplify_control_flow, max_unroll_ratio, remove_dead_code
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
        self.count_rename = 0
        self.count_reduce = 0
        self.count_unroll = 0
        self.count_evaluate = 0
        self.count_dead = 0

    def rename(self, name):
        if name is None:
            return "NONE"
        for r in regexp_rename:
            if re.match(r, name) is not None:
                if name in self.renamed.keys():
                    return self.renamed[name]
                newname = generate(rename_length)
                self.count_rename += 1
                self.renamed[name] = newname
                return newname
        return name
    
    def out(self, *args, **kwargs):
        kwargs['file'] = self.f
        print(*args, **kwargs)

    def dump(self):
        self.do_prog(self.ast.body)
        print("")
        print("======== Processing finished ========")
        print("Expressions simplified:\t\t", self.count_evaluate)
        print("Function calls inlined:\t\t", self.count_reduce)
        print("Loops unrolled:\t\t\t", self.count_unroll)
        print("Dead statements removed:\t", self.count_dead)
        print("Variables renamed:\t\t", self.count_rename)
        print("=====================================")

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
            self.out("[[TODO: litteral type not handled, type="+str(type(literal)) + ", val=" +str(literal) + "]]", end="")
        return

    def try_unroll(self, statement):
        if type(statement.unrolled) is list:
            unrolled_size = 0
            for st in statement.unrolled:
                unrolled_size += st.range[1] - st.range[0]
            if unrolled_size / (statement.range[1] - statement.range[0]) < max_unroll_ratio:
                self.out(self.indent*" " + " /* Start of unrolled loop */ ")
                for st in statement.unrolled:
                    self.do_statement(st)
                self.out(self.indent*" " + " /* End of unrolled loop */ ")
                self.count_unroll += 1
                return True
            else:
                self.out(self.indent*" " + " /* Could unroll, but decided not to */ ")
                return False
        else:
                self.out(self.indent*" " + " /* not unrollable: " + str(statement.reason) + " */ ")


    def do_expr_or_statement(self, exprstat, simplify=simplify_expressions, end="\n"):
        if exprstat.type in EXPRESSIONS:
            self.do_expr(exprstat, simplify)
        else:
            self.do_statement(exprstat, end)

    def do_expr(self, expr, simplify=True):
        if expr.eval is not None:
            self.out("eval('\n", end="")
            self.indent += self.INDENT
            for statement in expr.eval:
                self.do_statement(statement)
            self.indent -= self.INDENT
            self.out("')", end="")

        elif simplify and (expr.static_value is not None and ((isinstance(expr.static_value, JSPrimitive) and expr.static_value.val is not None) and not (expr.type == "CallExpression" and expr.callee.name == "eval")) or expr.static_value is JSUndefNaN):
            if expr.static_value is JSUndefNaN:
                self.out("undefined", end="")
            else:
                self.print_literal(expr.static_value.val)
            self.count_evaluate += 1
        
        elif expr.type == "Literal":
            if expr.raw == "null":
                self.out("null", end="")
            else:
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
                        if prop.key.name is not None:
                            self.out(prop.key.name, end="")
                        else:
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
            if expr.reduced is not None and simplify_function_calls:
                self.do_expr(expr.reduced)
                self.count_reduce += 1
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
        if remove_dead_code and (statement.dead_code or not statement.live) and not statement.type in EXPRESSIONS:
            self.out((self.indent)*" " + "{");
            self.out((self.indent+self.INDENT)*" " + "/* Dead Code: " + statement.type + " */")
            self.out((self.indent)*" " + "}");
            self.count_dead += 1
        elif statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.out(self.indent*" " + "var " + self.rename(decl.id.name), end="")
                if decl.init is not None:
                    self.out(" = ", end="")
                    self.do_expr(decl.init)
                self.out(";", end=end)

        elif statement.type == "ExpressionStatement":
            self.out(" "*self.indent, end="")
            self.do_expr(statement.expression, simplify=False)
            self.out(";", end=end)

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
            if not self.try_unroll(statement):
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
            if not self.try_unroll(statement):
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
            pass
            #raise ValueError("Statement type not handled: " + statement.type)
    def do_prog(self, prog):
        for statement in prog:
            self.do_statement(statement)
