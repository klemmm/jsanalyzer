import random
import esprima
import re
from abstract import JSPrimitive
from tools import call
from config import regexp_rename, rename_length, simplify_expressions, simplify_function_calls, simplify_control_flow, max_unroll_ratio, remove_dead_code
from functools import reduce

class AbstractInterpreter(object):
    def __init__(self, ast, domain, name):
        self.ast = ast
        self.name = name
        self.domain = domain

    def on_statement(self, state, statement):
        pass

    def on_expression(self, state, statement, test=False):
        pass

    def on_enter_function(self, state, statement):
        pass

    def on_leave_function(self, state, statement):
        pass
    
    def do_declaration(self, state, decl):
        if decl is None or decl.type != "VariableDeclaration":
            return
        yield [self.do_statement, state, decl]
    
    def do_expression(self, state, expression, test=False):
        if expression.type == "CallExpression":
            if expression.notrans_resolved_call is not None:
                self.on_enter_function(state, expression.notrans_resolved_call)
                if expression.notrans_resolved_call.notrans_function_entry_state != state:
                    expression.notrans_resolved_call.notrans_function_entry_state = self.domain.clone_state(state)
                    for st in expression.notrans_resolved_call.body:
                        yield [self.do_statement, state, st]
                self.on_leave_function(state, expression.notrans_resolved_call)
            return (yield [self.on_expression,state, expression, test])
        else:
            return (yield [self.on_expression, state, expression, test])

    def do_statement(self, state, statement):
        if statement.type == "VariableDeclaration":
            self.on_statement(state, statement)

        elif statement.type == "ExpressionStatement":
            yield [self.do_expression, state, statement.expression]

        elif statement.type == "IfStatement":
            yield [self.on_expression, state, statement.test, True]
            state_else = self.domain.clone_state(state)
            yield [self.do_statement, state, statement.consequent]
            if statement.alternate is not None:
                yield [self.do_statement, state_else, statement.alternate]
            self.domain.join_state(state, state_else)

        elif statement.type == "FunctionDeclaration":
            self.on_statement(state, statement)
       
        elif statement.type == "ReturnStatement":
            self.on_statement(state, statement)

        elif statement.type == "WhileStatement":
            header_state = self.domain.bottom_state()
            while True:
                prev_header_state = self.domain.clone_state(header_state)
                self.domain.join_state(header_state, state)
                self.domain.assign_state(state, header_state)

                if header_state == prev_header_state:
                    break

                yield [self.do_expression, state, statement.test, True]
                yield [self.do_statement, state, statement.body]

        
        elif statement.type == "TryStatement":
            yield [self.do_statement, state, statement.block]
        
        elif statement.type == "BlockStatement":
            for st in statement.body:
                yield [self.do_statement, state, st]
        
        elif statement.type == "ForStatement":

            yield [self.do_expression, state, statement.init]
            
            header_state = self.domain.bottom_state()
            while True:
                prev_header_state = self.domain.clone_state(header_state)
                self.domain.join_state(header_state, state)
                self.domain.assign_state(state, header_state)

                if header_state == prev_header_state:
                    break

                yield [self.do_expression, state, statement.test, True]
                yield [self.do_statement, state, statement.body]
                yield [self.do_expression, state, statement.test]
        
        elif statement.type == "ThrowStatement":
            self.on_statement(state, statement)

        elif statement.type == "SwitchStatement":
            yield [self.on_expression, state, statement.discriminant]

            case_states = []
            for case in statement.cases:
                current_case = state.clone()
                case_states.append(current_case)
                for statement in case.consequent:
                    yield [self.do_statement, current_state, statement]

            for s in case_states:
                state.join(s)

        elif statement.type == "ClassDeclaration":
            self.on_statement(state, statement)

        elif statement.type == "ClassBody":
            self.on_statement(state, statement)

        elif statement.type == "MethodDefinition":
            self.on_statement(state, statement)

        elif statement.type == "ForInStatement":

            yield [self.on_expression, state, statement.left]
            yield [self.on_expression, state, statement.right]
            
            header_state = self.state.bottom_state()
            while True:
                prev_header_state = header_state.clone()
                header_state.join(state)
                state.assign(header_state)

                if header_state == prev_header_state:
                    break

                yield [self.do_statement, state, statement.body]
        
    def do_prog(self, prog):
        state = self.domain.init_state()
        for statement in prog:
            yield [self.do_statement, state, statement]

        self.on_end(state)

    def run(self):
        print("Performing abstract interpretation on the '" + str(self.name) + "' domain.")
        call(self.do_prog, self.ast.body)

class CodeTransform(object):
    def __init__(self, ast, name):
        self.ast = ast
        self.name = name

    def before_expression(self, expr):
        return True

    def before_statement(self, expr):
        return True
    
    def after_expression(self, expr, results):
        return None

    def after_statement(self, expr, results):
        return None

    def do_expr_or_declaration(self, exprdecl):
        if exprdecl is None:
            return
        if exprdecl.type == "VariableDeclaration":
            yield [self.do_statement, exprdecl]
        else:
            yield [self.do_expr, exprdecl]

    def do_expr(self, expr):
        if expr is None:
            return
        if not self.before_expression(expr):
            return
        results = []
        if expr.type == "NewExpression":
            yield [self.do_expr, expr.callee]
            for argument in expr.arguments:
                results.append((yield [self.do_expr, argument]))

        elif expr.type == "ConditionalExpression":
            results.append((yield [self.do_expr,expr.test]))
            results.append((yield [self.do_expr,  expr.consequent]))
            results.append((yield [self.do_expr, expr.alternate]))

        elif expr.type == "SequenceExpression":
            for e in expr.expressions:
                results.append((yield [self.do_expr, e]))

        elif expr.type == "AssignmentExpression":
            if expr.left.type == "MemberExpression":
                results.append((yield [self.do_expr, expr.left.object]))
                if expr.left.computed:
                        results.append((yield [self.do_expr,expr.left.property]))
            results.append((yield [self.do_expr,expr.right]))

        elif expr.type == "ObjectExpression":
            for prop in expr.properties:
                if prop.computed:
                    results.append((yield [self.do_expr,prop.key]))
                else:
                    if prop.type == "Property":
                        results.append((yield [self.do_expr, prop.value]))

        elif expr.type == "ArrayExpression":
            for elem in expr.elements:
                results.append((yield [self.do_expr,elem]))

        elif expr.type == "MemberExpression":
            results.append((yield [self.do_expr,expr.object]))
            if expr.computed:
                results.append((yield [self.do_expr,expr.property]))

        elif expr.type == "UnaryExpression":
            results.append((yield [self.do_expr,expr.argument]))

        elif expr.type == "BinaryExpression":
            results.append((yield [self.do_expr,expr.left]))
            results.append((yield [self.do_expr,expr.right]))

        elif expr.type == "LogicalExpression":
            results.append((yield [self.do_expr,expr.left]))
            results.append((yield [self.do_expr,expr.right]))

        elif expr.type == "FunctionExpression":
            results.append((yield [self.do_statement,expr.body]))

        elif expr.type == "ArrowFunctionExpression":
            if expr.expression:
                results.append((yield [self.do_expr,expr.body]))
            else:
                results.append((yield [self.do_statement,expr.body]))

        elif expr.type == "CallExpression": #todo reduced
            results.append((yield [self.do_expr,expr.callee]))
            for argument in expr.arguments:
                if argument.type == "BlockStatement":
                    results.append((yield [self.do_statement, argument])) #TODO hack
                results.append((yield [self.do_expr,argument]))

        elif expr.type == "UpdateExpression":
            results.append((yield [self.do_expr,expr.argument]))

        elif expr.type == "AwaitExpression":
            results.append((yield [self.do_expr, expr.argument]))

        return self.after_expression(expr, results)

    def do_statement(self, statement, end="\n"):
        if not self.before_statement(statement):
            return
        results = []
        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                if decl.id.type == "ObjectPattern":
                    for prop in decl.id.properties:
                        if prop.computed:
                            results.append((yield [self.do_expr,prop.key]))
                        else:
                            if prop.type == "Property":
                                results.append((yield [self.do_expr,prop.value]))
                if decl.init is not None:
                    results.append((yield [self.do_expr, decl.init]))

        elif statement.type == "ExpressionStatement":
            results.append((yield [self.do_expr, statement.expression]))

        elif statement.type == "IfStatement":
            results.append((yield [self.do_expr,statement.test]))
            results.append((yield [self.do_statement, statement.consequent]))
            if statement.alternate is not None:
                results.append((yield [self.do_statement, statement.alternate]))

        elif statement.type == "FunctionDeclaration":
            results.append((yield [self.do_statement, statement.body]))
       
        elif statement.type == "ReturnStatement":
            if statement.argument is not None:
                results.append((yield [self.do_expr, statement.argument]))

        elif statement.type == "WhileStatement":
            results.append((yield [self.do_expr,statement.test]))
            results.append((yield [self.do_statement,statement.body]))
        
        elif statement.type == "TryStatement":
            results.append((yield [self.do_statement,statement.block]))
        
        elif statement.type == "BlockStatement":
            for statement in statement.body:
                results.append((yield [self.do_statement,statement]))
        
        elif statement.type == "ForStatement":
            results.append((yield [self.do_expr_or_declaration,statement.init]))
            results.append((yield [self.do_expr,statement.test]))
            results.append((yield [self.do_expr_or_declaration,statement.update]))
            results.append((yield [self.do_statement,statement.body]))
        
        elif statement.type == "ThrowStatement":
            results.append((yield [self.do_expr,statement.argument]))

        elif statement.type == "SwitchStatement":
            results.append((yield [self.do_expr,statement.discriminant]))
            for case in statement.cases:
                results.append((yield [self.do_expr,case.test]))
                for statement in case.consequent:
                    results.append((yield [self.do_statement,statement]))

        elif statement.type == "ClassDeclaration":
            results.append((yield [self.do_statement,statement.body]))

        elif statement.type == "ClassBody":
            for item in statement.body:
                results.append((yield [self.do_statement,item]))

        elif statement.type == "MethodDefinition":
            if statement.key.type != "Identifier":
                results.append((yield [self.do_expr,statement.key]))
            results.append((yield [self.do_statement,statement.value.body]))

        elif statement.type == "ForInStatement":
            results.append((yield [self.do_expr_or_declaration,statement.left]))
            results.append((yield [self.do_expr_or_declaration,  statement.right]))
            results.append((yield [self.do_statement,statement.body]))
        
        return self.after_statement(statement, results)

    def do_prog(self, prog):
        for statement in prog:
            yield [self.do_statement, statement]

    def run(self):
        print("Applying code transform: " + str(self.name))
        call(self.do_prog, self.ast.body)

class ExpressionSimplifier(CodeTransform):
    def __init__(self, ast, pures):
        super().__init__(ast, "Expression Simplifier")
        self.pures = pures

    def after_statement(self, st, results):
        if st.type == "ExpressionStatement":
            st.expression.notrans_static_value = None

    def after_expression(self, o, side_effects):
        calls = []
        for s in side_effects:
            if s is True:
                return True
            elif s is False:
                continue
            elif type(s) is list:
                for c in s:
                    calls.append(c)
        if o.type == "AssignmentExpression" or o.type == "UpdateExpression" or o.type == "ConditionalExpression" or o.type == "LogicalExpression":
            return True
        #Test if expression has side effects
        if o.type == "CallExpression" and not o.callee_is_pure and o.callee.name not in self.pures:
            c = esprima.nodes.CallExpression(o.callee, o.arguments)
            calls.append(c)
        if isinstance(o.notrans_static_value, JSPrimitive):
            if (type(o.notrans_static_value.val) is int or type(o.notrans_static_value.val) is float) and o.notrans_static_value.val < 0:
                return calls
            else:
                o.type = "Literal"
                o.value = o.notrans_static_value.val
                if o.value == "<<NULL>>":
                    o.value = None
                if len(calls) > 0:
                    o_copy = esprima.nodes.Literal(o.value, o.raw)
                    sequence = calls.copy()
                    sequence.append(o_copy)
                    seq_node = esprima.nodes.SequenceExpression(sequence)
                    static_value = o.notrans_static_value
                    o.__dict__ = seq_node.__dict__
                    o.notrans_static_value = static_value
                    o.notrans_impure = True

        return calls

class VariableRenamer(CodeTransform):
    def __init__(self, ast):
        random.seed(42)
        self.first=['b','ch','d','f','g','l','k', 'm','n','p','r','t','v','x','z']
        self.second=['a','e','o','u','i','au','ou']
        self.renamed = {}
        self.used_names = set()
        super().__init__(ast, "Variable Renamer")

    def generate(self, n):
        name = ""
        for i in range(n):
            name += random.choice(self.first)
            name += random.choice(self.second)
        return name

    def rename(self, name):
        global rename_length
        if name is None:
            return name
        for r in regexp_rename:
            if re.match(r, name) is not None:
                if name in self.renamed.keys():
                    return self.renamed[name]

                newname = self.generate(rename_length)
                t = 0
                while newname in self.used_names:
                    if t > 10:
                        rename_length += 1
                        print("WARNING: increased variable rename length to:", rename_length)
                    newname = generate(rename_length)
                    t = t + 1
                self.used_names.add(newname)
                self.renamed[name] = newname
                return newname
        return name
    
    def before_expression(self, o):
        if o.type == "Identifier" and o.name != "undefined":
            o.name = self.rename(o.name)
        elif o.type == "AssignmentExpression":
            o.left.name = self.rename(o.left.name)
        elif o.type == "FunctionExpression" or o.type == "ArrowFunctionExpression":
            for a in o.params:
                a.name = self.rename(a.name)
        return True

    def before_statement(self, st):
        if st.type == "VariableDeclaration":
            for decl in st.declarations:
                if decl.id.type == "Identifier":
                    decl.id.name = self.rename(decl.id.name)
        elif st.type == "FunctionDeclaration":
            for a in st.params:
                a.name = self.rename(a.name)
            st.id.name = self.rename(st.id.name)
        elif st.type == "ClassDeclaration":
            st.id.name = self.rename(st.id.name)
        elif st.type == "MethodDefinition":
            for a in st.value.params:
                a.name = self.rename(a.name)
        return True

class FunctionInliner(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Function Inliner")

    def before_statement(self, statement):
        if statement.type == "FunctionDeclaration":
            statement.body.leadingComments = [{"type":"Block", "value":" Pure: " + str(statement.body.pure) + " " }]
        return True

    def before_expression(self, o):
        if o.type == "CallExpression" and o.noout_reduced is not None:
            o.__dict__ = o.noout_reduced.__dict__
            o.noout_reduced = None
        elif o.type == "FunctionExpression" or o.type == "ArrowFunctionExpression":
            o.body.leadingComments = [{"type":"Block", "value":" Pure: " + str(o.body.pure) + " " }]
        return True

class DeadCodeRemover(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Dead Code Remover")

    def before_statement(self, o):
        if not o.live and o.type == "BlockStatement":
            o.body = [esprima.nodes.EmptyStatement()]
            o.body[0].leadingComments = [{"type":"Block", "value":" Dead Code "}]
            return False
        return True

class LoopUnroller(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Loop Unroller")

    def before_statement(self, o):
        if (o.type == "WhileStatement" or o.type == "ForStatement") and type(o.noout_unrolled) is list:
            unrolled_size = 0
            for st in o.noout_unrolled:
                unrolled_size += st.range[1] - st.range[0]

            if unrolled_size / (o.range[1] - o.range[0]) < max_unroll_ratio:
                o.type = "BlockStatement"
                o.body = []
                for st in o.noout_unrolled:
                    if st.type != "Literal" and st.type != "Identifier":
                        o.body.append(st)
                o.leadingComments = [{"type":"Block", "value":" Begin unrolled loop "}]
                o.trailingComments = [{"type":"Block", "value":" End unrolled loop "}]
            o.noout_unrolled = None
        return True

class EvalReplacer(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Eval Handler")

    def before_expression(self, o):
        if o is None:
            return False
        if o.noout_eval is not None:
            block = esprima.nodes.BlockStatement(o.noout_eval)
            block.live = True
            o.arguments = [block] #TODO not valid JS 
            o.noout_eval = None
        if o.noout_fn_cons is not None:
            o.__dict__ = o.noout_fn_cons[0].expression.__dict__
        return True

class ConstantMemberSimplifier(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Constant Member Simplifier")

    def before_expression(self, expr):
        if expr.type == "AssignmentExpression":
            if expr.left.type == "MemberExpression":
                if expr.left.computed and isinstance(expr.left.property.notrans_static_value, JSPrimitive) and type(expr.left.property.notrans_static_value.val) is str:
                    expr.left.computed = False
                    expr.left.property.name = expr.left.property.notrans_static_value.val
                    if expr.left.property.notrans_impure:
                        expr_copy = esprima.nodes.AssignmentExpression(expr.operator, expr.left, expr.right)
                        sequence = expr.left.property.expressions[:-1]
                        sequence.append(expr_copy)
                        result = esprima.nodes.SequenceExpression(sequence)
                        expr.__dict__ = result.__dict__
        elif expr.type == "MemberExpression":
            if expr.computed and isinstance(expr.property.notrans_static_value, JSPrimitive) and type(expr.property.notrans_static_value.val) is str:
                expr.computed = False
                expr.property.name = expr.property.notrans_static_value.val
                if expr.property.notrans_impure:
                    expr_copy = esprima.nodes.StaticMemberExpression(expr.object, expr.property)
                    sequence = expr.property.expressions[:-1]
                    sequence.append(expr_copy)
                    result = esprima.nodes.SequenceExpression(sequence)
                    expr.__dict__ = result.__dict__
        return True


class VarDefInterpreter(AbstractInterpreter):

    class Domain(object):

        def init_state(self):
            return set({None})

        def bottom_state(self):
            return set({None})

        def is_bottom(self, state):
            return state == set({None})

        def clone_state(self, state):
            return state.copy()

        def join_state(self, state_dest, state_source):
            if self.is_bottom(state_source):
                return
            elif self.is_bottom(state_dest):
                self.assign_state(state_dest, state_source)
            else:
                state_dest.update(state_source)

        def assign_state(self, state_dest, state_source):
            state_dest.clear()
            state_dest.update(state_source)

    def __init__(self, ast):
        self.id_to_expr = {}
        self.defs = set()
        self.expr_id = 0
        self.stack = []
        super().__init__(ast, self.Domain(), "Variable Definition")
    
    def on_enter_function(self, state, statement):
        self.stack.append(self.domain.clone_state(state))
        state.clear()

    def on_leave_function(self, state, statement):
        p = self.stack.pop()
        self.domain.assign_state(state, p)

    def mark_expression(self, expression, is_def=False):
        if expression.expr_id is None:
            expression.expr_id = self.expr_id
            self.id_to_expr[self.expr_id] = expression
            if is_def:
                self.defs.add(self.expr_id)
                expression.notrans_used_by = set()
            expression.notrans_uses = set()
            self.expr_id += 1
        
    def def_use_link(self, _def, _use):
        for used_expr_id in _def:
            used_expr = self.id_to_expr[used_expr_id]
            for used_assignment_id in used_expr.notrans_uses:
                used_assignment = self.id_to_expr[used_assignment_id]
                used_assignment.notrans_used_by.add(_use.expr_id)

    def define(self, state, expression, name):
        self.mark_expression(expression, True)
        state.difference_update([x for x in state if x[0] == name])
        state.add((name, expression.expr_id))

    def on_statement(self, state, statement):
        if self.domain.is_bottom(state):
            return
        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.define(state, decl, decl.id.name)

    def on_expression(self, state, expression, test=False):
        if self.domain.is_bottom(state):
            return set()
        r = set()
        expression.notrans_state = state.copy()
        if expression.type == "AssignmentExpression":
            killed = [x for x in state if x[0] == expression.left.name]
            self.mark_expression(expression, len(killed) > 0)
            if len(killed) > 0:
                state.add((expression.left.name, expression.expr_id))
            
            expr_result = yield [self.do_expression, state, expression.right]
            r.update(expr_result[0])
            expression.notrans_uses = r.copy()
            self.def_use_link(r, expression)
            state.difference_update(killed)
            r.add(expression.expr_id)
            expression.notrans_side_effects = expr_result[1]
            return (r, True)

        elif expression.type == "BinaryExpression" or expression.type == "LogicalExpression":
            r = set()
            left = yield [self.do_expression, state, expression.left]
            right = yield [self.do_expression, state, expression.right]
            r.update(left[0])
            r.update(right[0])
            self.mark_expression(expression)
            if test:
                expression.notrans_test = True
                self.def_use_link(r, expression)
            return (r, left[1] or right[1])

        elif expression.type == "Literal":
            return ({}, False)

        elif expression.type == "Identifier":
            self.mark_expression(expression)
            used = [x for x in state if x[0] == expression.name]
            for u in used:
                expression.notrans_uses.add(u[1])
            return ({expression.expr_id}, False)

        elif expression.type == "CallExpression":
            r = set()
            side_effects = not expression.callee_is_pure
            for a in expression.arguments:
                arg_result = yield [self.do_expression, state, a]
                r.update(arg_result[0])
            self.mark_expression(expression)
            if side_effects:
                self.def_use_link(r, expression)
            return (r, side_effects)

    def on_end(self, state):
        useless = set()
        change = True
        while change:
            previous_useless = useless.copy()
            for d in self.defs:
                useful_count = len([u for u in self.id_to_expr[d].notrans_used_by if u not in useless and u != d])
                if useful_count == 0:
                    useless.add(d)
            change = (useless != previous_useless)
        for d in self.defs:
            assign_expr = self.id_to_expr[d]
            assign_expr.notrans_useless = d in useless

class UselessVarRemover(CodeTransform):
    def __init__(self, ast):
        super().__init__(ast, "Useless Variable Remover")

    def before_expression(self, o):
        if o.type == "CallExpression" and o.expr_id is not None:
            o.trailingComments = [{"type":"Block", "value":" Type: Call, ID: " + str(o.expr_id) + " "}]
        elif o.notrans_test:
            o.trailingComments = [{"type":"Block", "value":" Type: Test, ID: " + str(o.expr_id) + " "}]
        return True

    def before_statement(self, o):
        if not o.live:
            return
        if o.type == "ExpressionStatement" and (o.expression.type == "AssignmentExpression"):
            if o.expression.notrans_useless == True:
                u = "Useless, "
            elif o.expression.notrans_useless == False:
                u = "Useful, "
            else:
                u = "Is-Not-Local, "
            comm = " Type: Assign, ID: " + str(o.expression.expr_id) + ", " + u + "Used-By: " + str(o.expression.notrans_used_by or "{}") + " "
            if o.expression.notrans_side_effects:
                comm += "Has-Side-Effects "
            o.trailingComments = [{"type":"Block", "value": comm}]
            
            return True
        return True
