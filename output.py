from abstract import JSPrimitive

class Output(object):
    def __init__(self, ast, f):
        self.INDENT = 2
        self.indent = 0
        self.ast = ast
        self.f = f
    
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

    def do_expr(self, expr, simplify=True):
        if simplify and (expr.static_value is not None and isinstance(expr.static_value, JSPrimitive)):
            self.print_literal(expr.static_value.val)

        elif expr.type == "Literal":
            self.print_literal(expr.value)

        elif expr.type == "Identifier":
            self.out(expr.name, end="")
            pass

        elif expr.type == "NewExpression":
            self.out("new XXX(", end="")
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
            self.out("ThisExpression")

        elif expr.type == "SequenceExpression":
            first = True
            for e in expr.expressions:
                if not first:
                    self.out(", ", end="")
                first = False
                self.do_expr(e)

        elif expr.type == "AssignmentExpression":
            if expr.left.type == "Identifier":
                self.out(expr.left.name + " = ", end="")
            else: #MemberExpression
                self.do_expr(expr.left.object)
                if expr.left.computed:
                    self.out("[", end="")
                    self.do_expr(expr.left.property)
                    self.out("]", end="")
                else:
                    self.out("." + expr.left.property.name, end="")
                self.out(" = ", end="")

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
            self.do_expr(expr.object)
            if expr.computed:
                self.out("[", end="")
                self.do_expr(expr.property)
                self.out("]", end="")
            else:
                self.out("." + expr.property.name, end="")

        elif expr.type == "UnaryExpression":
            self.out(expr.operator, end="")
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
            self.out(self.indent*" " + "function()")
            self.do_statement(expr.body)

        elif expr.type == "ArrowFunctionExpression":
            self.out(self.indent*" " + "function()")
            self.do_statement(expr.body)

        elif expr.type == "CallExpression":
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
            self.do_expr(expr.argument)
            self.out(")" + expr.operator, end="")

        else:
            self.out(expr)
            raise ValueError("Expr type not handled: " + expr.type)




    def do_statement(self, statement):
        if statement.dead_code is True:
            self.out((self.indent)*" " + "{");
            self.out((self.indent+self.INDENT)*" " + "/* Dead Code */")
            self.out((self.indent)*" " + "}");
        elif statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.out(self.indent*" " + "var " + str(decl.id.name), end="")
                if decl.init is not None:
                    self.out(" = ", end="")
                    self.do_expr(decl.init)
                self.out("")

        elif statement.type == "ExpressionStatement":
            self.out(" "*self.indent, end="")
            self.do_expr(statement.expression, simplify=False)
            self.out("")

        elif statement.type == "IfStatement":
            self.out(self.indent*" " + "if (", end="")
            self.do_expr(statement.test)
            self.out(")", end="")
            self.do_statement(statement.consequent)
            if statement.alternate is not None:
                self.do_statement(statement.alternate)

        elif statement.type == "FunctionDeclaration":
            self.out(self.indent*" " + "function " + statement.id.name + "()")
            self.do_statement(statement.body)
       
        elif statement.type == "ReturnStatement":
            self.out(self.indent*" " + "return")
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
            self.out(self.indent*" " + "ForStatement;")
        
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
