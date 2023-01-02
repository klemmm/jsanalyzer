import random
import esprima
import re
from abstract import JSPrimitive, JSRef
from tools import call
from config import regexp_rename, rename_length, simplify_expressions, simplify_function_calls, simplify_control_flow, max_unroll_ratio, remove_dead_code
from functools import reduce
from collections import namedtuple
from node_tools import get_ann, set_ann, del_ann, node_from_id, id_from_node, clear_ann
from typing import Set, List

gg = []

class LexicalScopedAbsInt(object):
    def __init__(self, ast, domain, name):
        self.ast = ast
        self.name = name
        self.domain = domain

    def on_statement(self, state, statement):
        pass

    def on_expression(self, state, statement, test=False):
        pass

    def do_declaration(self, state, decl):
        if decl is None or decl.type != "VariableDeclaration":
            return
        yield [self.do_statement, state, decl]
    
    def do_expression(self, state, expression, test=False):
        if expression.type == "CallExpression":
            if type(expression.arguments) is list and len(expression.arguments) == 1 and expression.arguments[0].type == "BlockStatement":
                for st in expression.arguments[0].body:
                    yield [self.do_statement, state, st]
            return (yield [self.on_expression,state, expression, test])
        elif expression.type == "FunctionExpression" or expression.type == "ArrowFunctionExpression":
            return (yield [self.on_expression, state, expression, test])
        else:
            return (yield [self.on_expression, state, expression, test])

    def do_statement(self, state, statement):
        if statement.type == "VariableDeclaration":
            yield [self.on_statement, state, statement]

        elif statement.type == "ExpressionStatement":
            yield [self.on_statement, state, statement]

        elif statement.type == "IfStatement":
            yield [self.on_statement, state, statement]
            yield [self.on_expression, state, statement.test, True]
            state_else = self.domain.clone_state(state)
            yield [self.do_statement, state, statement.consequent]
            if statement.alternate is not None:
                yield [self.do_statement, state_else, statement.alternate]
            self.domain.join_state(state, state_else)

        elif statement.type == "FunctionDeclaration":
            yield [self.on_statement, state, statement]
       
        elif statement.type == "ReturnStatement":
            yield [self.on_statement, state, statement]

        elif statement.type == "WhileStatement":
            yield [self.on_statement, state, statement]
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
            yield [self.on_statement, state, statement]

            if statement.init is not None:
                yield [self.do_expression, state, statement.init]
            
            header_state = self.domain.bottom_state()
            while True:
                prev_header_state = self.domain.clone_state(header_state)
                self.domain.join_state(header_state, state)
                self.domain.assign_state(state, header_state)

                if header_state == prev_header_state:
                    break

                if statement.test is not None:
                    yield [self.do_expression, state, statement.test, True]

                if statement.body is not None:
                    yield [self.do_statement, state, statement.body]

                if statement.update is not None:
                    yield [self.do_expression, state, statement.update]
        
        elif statement.type == "ThrowStatement":
            yield [self.on_statement, state, statement]

        elif statement.type == "SwitchStatement":
            yield [self.on_statement, state, statement]
            yield [self.on_expression, state, statement.discriminant]

            case_states = []
            for case in statement.cases:
                current_case = self.domain.clone_state(state)
                case_states.append(current_case)
                for statement in case.consequent:
                    yield [self.do_statement, current_case, statement]

            for s in case_states:
                self.domain.join_state(state, s)

        elif statement.type == "ClassDeclaration":
            yield [self.on_statement, state, statement]

        elif statement.type == "ClassBody":
            yield [self.on_statement, state, statement]

        elif statement.type == "MethodDefinition":
            yield [self.on_statement, state, statement]

        elif statement.type == "ForInStatement":

            yield [self.on_expression, state, statement.left]
            yield [self.on_expression, state, statement.right]
            
            header_state = self.domain.bottom_state()
            while True:
                prev_header_state = self.domain.clone_state(header_state)
                self.domain.join_state(header_state, state)
                self.domain.assign_state(state, header_state)

                if header_state == prev_header_state:
                    break

                yield [self.do_statement, state, statement.body]
        
    def do_prog(self, prog):
        state = self.domain.init_state()
        for statement in prog:
            yield [self.do_statement, state, statement]
        self.on_end(state)

    def run(self):
        call(self.do_prog, self.ast.body)

class CodeTransform(object):
    def __init__(self, ast, name):
        self.ast = ast
        self.name = name
        self.pass_num = 1

    def before_expression(self, expr):
        return True

    def before_statement(self, expr):
        return True
    
    def after_expression(self, expr, results):
        return None

    def after_statement(self, expr, results):
        return None

    def after_program(self, results):
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
            for st in statement.body:
                results.append((yield [self.do_statement, st]))
        
        elif statement.type == "ForStatement":
            if statement.init is not None:
                results.append((yield [self.do_expr_or_declaration,statement.init]))
            if statement.test is not None:
                results.append((yield [self.do_expr,statement.test]))
            if statement.update is not None:
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
        results = []
        for statement in prog:
            results.append((yield [self.do_statement, statement]))
        self.after_program(results)

    def run(self):
        if self.name is not None:
            print("Applying code transform: " + str(self.name), end="")
            if self.pass_num > 1:
                print(" (pass " + str(self.pass_num) + ")")
            else:
                print("")
        call(self.do_prog, self.ast.body)
        self.pass_num += 1

class ExpressionSimplifier(CodeTransform):
    def __init__(self, ast, pures):
        super().__init__(ast, "Expression Simplifier")
        self.pures = pures
        self.id_pures = set()

    def after_statement(self, st, results):
        if st.type == "ExpressionStatement":
            st.expression.notrans_static_value = None


    def before_expression(self, o):
        if o.type == "UpdateExpression":
            set_ann(o.argument, "is_updated", True)
            return True
        return True

    def after_expression(self, o, side_effects): #TODO nettoyer
        """
        Process expression.
        
        :param o esprima.nodes.Node: An expression node
        :param List[Union[bool, esprima.nodes.Node]] side_effects: For all subexpressions: True if has side effects not related to functions. False if has no side effects. List of function calls if only side-effects related to functions.
        """


        calls = []
        #Collect side-effects call for any sub-expression. If we encounter side effects not releted to function call, return True
        for s in side_effects:
            if s is True:
                return True
            elif s is False:
                continue
            elif type(s) is list:
                for c in s:
                    calls.append(c)        
        #If we reach here, sub-expressions have either no side effects, or side effects related to function calls


        if o.type == "AssignmentExpression" or o.type == "ConditionalExpression" or o.type == "LogicalExpression":
            return True #Report side effects not related to function call

        if o.type == "UpdateExpression" and isinstance(o.notrans_static_value, JSPrimitive):
            if (type(o.notrans_static_value.val) is int or type(o.notrans_static_value.val) is float) and o.notrans_static_value.val < 0:
                return True
                
            n = esprima.nodes.AssignmentExpression("=", o.argument, esprima.nodes.Literal(o.notrans_static_value.val, None))
            o.__dict__ = n.__dict__
            return True

        #If we reach here, this expression either have either no side effects, or side effects related to function calls

        #Find out if this expression references a function that has been declared as pure on the command line arguments
        if o.type == "CallExpression" and o.callee.name in self.pures:
            if isinstance(o.callee.notrans_static_value, JSRef):
                self.id_pures.add(o.callee.notrans_static_value.target())

        #Find out if this is a call with side effects
        if o.type == "CallExpression" and not o.callee_is_pure and o.callee.name not in self.pures and (not isinstance(o.callee.notrans_static_value, JSRef) or o.callee.notrans_static_value.target() not in self.id_pures):
            c = esprima.nodes.CallExpression(o.callee, o.arguments)
            calls.append(c)

        #Find out if expression has a statically-known value
        if isinstance(o.notrans_static_value, JSPrimitive) and not get_ann(o, "is_updated"):
            #TODO should put an UnaryExpression here in case of negative value
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
        if o.type == "Identifier" and o.name != "uncreate_defd":
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
            statement.body.leadingComments = [{"type":"Block", "value":" Pure: " + str(statement.body.pure) + " Closure: " + str(statement.body.closure) + " "}]
        return True

    def before_expression(self, o):
        if o.type == "CallExpression" and o.noout_reduced is not None:
            o.__dict__ = o.noout_reduced.__dict__
            o.noout_reduced = None
        elif o.type == "FunctionExpression" or o.type == "ArrowFunctionExpression":
            o.body.leadingComments = [{"type":"Block", "value":" Pure: " + str(o.body.pure) + " Closure: " + str(o.body.closure) + " "}]
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


class VarDefInterpreter(LexicalScopedAbsInt):

    ExprDesc = namedtuple("ExprDesc", "def_set has_side_effects")
    Def = namedtuple("Def", "name def_id")

    class Domain(object):
        class State(set):
            pass

        
        def init_state(self) -> State:
            """
            Creates a new initial state

            :return: new initial state
            """
            return self.State({})


        def bottom_state(self) -> State:
            """
            Creates a new bottom state

            :return: new bottom state
            """
            return self.State({None})


        def is_bottom(self, state : State) -> bool:
            """
            Tells the state is bottom
            
            :param State state: the state to check
            :rtype: bool
            :return: True if the passed state is bottom
            """
            return state == self.State({None})


        def clone_state(self, state : State) -> State:
            """
            Copy a state, returning the copy
            
            :param State state: the source state
            :rtype: State
            :return: the copied state
            """            
            return state.copy()


        def join_state(self, state_dest : State, state_source : State) -> None:
            """
            Join two states, store result in state_dest
            
            :param State state_dest: the dest state
            :param State state_source: the source state
            """
            if self.is_bottom(state_source):
                return
            elif self.is_bottom(state_dest):
                self.assign_state(state_dest, state_source)
            else:
                state_dest.update(state_source)


        def assign_state(self, state_dest : State, state_source : State) -> None:
            """
            Assign source state to destination state
            
            :param State state_dest: the dest state
            :param State state_source: the source state
            """            
            state_dest.clear()
            state_dest.update(state_source)

    def __init__(self, ast : esprima.nodes.Node) -> None:
        """
        Class constructor

        :param esprima.nodes.Node ast: The AST to process.
        """
        self.defs = set()
        self.free_vars = set()
        self.inner_free_vars = set()
        self.state_stack = []
        self.func_stack = []
        self.current_func = None
        super().__init__(ast, self.Domain(), "Variable Definition")

    def handle_function_body(self, state: Domain.State, body: esprima.nodes.Node) -> None:
        """
        Called whenever we enter a function

        :param State state: The current state
        :param esprima.nodes.Node body: The function body
        """
        self.free_vars = set()
        self.func_stack.append(self.current_func)
        self.current_func = body
        self.state_stack.append(self.domain.clone_state(state))
        self.domain.assign_state(state, self.domain.init_state())
        yield [self.do_statement, state, body]
        set_ann(body, "inner_free_vars", self.inner_free_vars.copy())
        self.current_func = self.func_stack.pop()
        self.inner_free_vars.difference_update(set([x.name for x in state]))
        self.domain.assign_state(state, self.state_stack.pop())
        self.free_vars.update(self.inner_free_vars)
        self.inner_free_vars = self.free_vars
        self.free_vars = set()



    def link_def_set_to_use(self, def_set : Set[int], use : int) -> None:
        """
        Create a link from a set of definitions to an use
        
        :param Set[int] def_set: the set of definitions (set of ids)
        :param int use: the use (by id)
        """        
        for used_assignment_id in def_set:
            used_assignment = node_from_id(used_assignment_id)
            get_ann(used_assignment, "used_by").add(use)


    def get_def_set_by_name(self, state : Domain.State, name : str) -> Set[int]:
        """
        Get a set of definitions matching a variable name
        
        :param Domain.State state: the current state
        :param str name: the variable name
        :rtype: Set[int]
        :return: the set of definitions (set of ids)
        """        
        return set([x.def_id for x in state if x.name == name])


    def kill_def_set_by_name(self, state : Domain.State, name : str) -> None:
        """
        Removes definitions from state matching some variable name
        
        :param Domain.State state: the current state
        :param str name: the variable name
        """        
        state.difference_update([x for x in state if x.name == name])


    def create_def(self, state : Domain.State, expression : esprima.nodes.Node, name : str) -> None:
        """
        Create a definition based on the variable name and expression
        
        :param Domain.State state: the current state
        :param esprima.nodes.Node expression: the expression that will be stored in the variable
        :param str name: the variable name
        """        
        self.defs.add(id_from_node(expression))
        set_ann(expression, "used_by", set())
        set_ann(expression, "decl_used_by", set())
        self.kill_def_set_by_name(state, name)
        state.add(self.Def(name, id_from_node(expression)))


    def new_expr_desc(self, def_set : Set[int] = set(), has_side_effects : bool = False) -> ExprDesc:
        """
        Returns a new Expression Descriptor. The Expression Descriptor contains a set of definitions used
        by an expression, and also whether the expression has any side-effects.

        :param Set[int] def_set: The set of definitions used by the expression (default: empty set)
        :param bool has_side_effects: True if the expression has side effects (default: False)
        :rtype: ExprDesc
        :return: The new expression descriptor
        """        
        return self.ExprDesc(def_set, has_side_effects)

 
    def updated_expr_desc(self, state : Domain.State, expr_desc : ExprDesc, expr : esprima.nodes.Node) -> ExprDesc:
        """
            Updates an Expression Descriptor to take into account a new expression.

            :param Domain.State state: the current state
            :param ExprDesc expr_desc: the current expression descriptor
            :param: esprima.nodes.Node expr: the expression used to update the descriptor
            :rtype: ExprDesc
            :return: The updated expression descriptor
            """        
        if expr.type == "BlockStatement":
            return self.new_expr_desc() #TODO
        sub_expr_desc = yield [self.do_expression, state, expr]
        r = self.new_expr_desc(sub_expr_desc.def_set.union(expr_desc.def_set), sub_expr_desc.has_side_effects or expr_desc.has_side_effects)
        return r


    def on_statement(self, state : Domain.State, statement : esprima.nodes.Node) -> None:
        """
        Called when the analysis encounters a statement

        :param Domain.State state: the current state
        :param esprima.nodes.Node: the current statement
        """

        if self.domain.is_bottom(state):
            return

        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                expr_desc = self.new_expr_desc()
                if decl.id.type == "ObjectPattern":
                    #TODO, todoo, todoooo🎵 🎵dooo dooo🎵 dooo🎵 🎵
                    pass        
                else:
                    self.create_def(state, decl, decl.id.name)
                if decl.init is not None:
                    expr_desc = yield [self.updated_expr_desc, state, expr_desc, decl.init]
                    self.link_def_set_to_use(expr_desc.def_set, id_from_node(decl))
                    set_ann(decl, "rhs_side_effects", expr_desc.has_side_effects)
                set_ann(decl, "in_func", self.current_func)

        elif statement.type == "ExpressionStatement":
            expr_desc = yield [self.updated_expr_desc, state, self.new_expr_desc(), statement.expression]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(statement.expression)) 

        elif statement.type == "ReturnStatement":
            expr_desc = yield [self.updated_expr_desc, state, self.new_expr_desc(), statement.argument]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(statement.argument))

        elif statement.type in ["ForStatement", "WhileStatement", "IfStatement"]:
            expr_desc = yield [self.updated_expr_desc, state, self.new_expr_desc(), statement.test]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(statement.test))

        elif statement.type in ["SwitchStatement"]:
            expr_desc = yield [self.updated_expr_desc, state, self.new_expr_desc(), statement.discriminant]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(statement.discriminant))

        elif statement.type == "FunctionDeclaration":
            yield [self.handle_function_body, state, statement.body]


    def on_expression(self, state : Domain.State, expression : esprima.nodes.Node, test : bool = False) -> ExprDesc:
        """
        Called when the analysis encounters an expression

        :param Domain.State state state: the current state
        :param esprima.nodes.Node expression: the current expression
        :param bool test: True if the expression is used as a condition (in while/for/if)
        :rtype: ExprDesc
        :return: the expression descriptor corresponding to the expression
        """        
        if self.domain.is_bottom(state):
            return self.new_expr_desc()

        if expression.type == "AssignmentExpression":
            global gg
            expr_desc = self.new_expr_desc()

            #In these cases, LHS is read, so we need to register the uses for LHS in the expr desc
            if expression.left.type == "MemberExpression" or expression.operator != "=":
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.left]
            
            #Register the declaration associated to the LHS as useful: we track declarations and values separately because it's possible that a variable declaration is useful even if the initialization isn't
            existing_defs = self.get_def_set_by_name(state, expression.left.name)
            for d in existing_defs:
                if node_from_id(d).type == "VariableDeclarator":
                    get_ann(node_from_id(d), "decl_used_by").add(id_from_node(expression))               
            
            #register the uses for RHS in expr desc
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.right]

            #We only handle local variables for now, so we create a DEF only if this variable was locally declared
            if bool(existing_defs):
                self.create_def(state, expression, expression.left.name)            
            
            #Store results in annotations
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
            set_ann(expression, "rhs_side_effects", expr_desc.has_side_effects)
            set_ann(expression, "in_func", self.current_func)
          
            return self.new_expr_desc(expr_desc.def_set, True)

        elif expression.type == "BinaryExpression" or expression.type == "LogicalExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.left]
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.right]
            return expr_desc

        elif expression.type == "ConditionalExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.test]
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.consequent]
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.alternate]
            return expr_desc

        elif expression.type == "ArrayExpression":
            expr_desc = self.new_expr_desc()
            for elem in expression.elements:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, elem]
            return expr_desc
        
        elif expression.type == "ObjectExpression":
            expr_desc = self.new_expr_desc()
            for prop in expression.properties:
                if prop.computed:
                    expr_desc = yield [self.updated_expr_desc, state, expr_desc, prop.key]
                if prop.type == "Property":
                    expr_desc = yield [self.updated_expr_desc, state, expr_desc, prop.value]
            return expr_desc
        
        elif expression.type == "MemberExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.object]
            if expression.computed:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.property]
            return expr_desc

        elif expression.type == "Literal":
            return self.new_expr_desc()

        elif expression.type == "UpdateExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.argument]

            if expression.argument.type == "Identifier": #For now, only handle updates to identifiers
                existing_defs = self.get_def_set_by_name(state, expression.argument.name)
                if bool(existing_defs):
                    self.create_def(state, expression, expression.argument.name)

                self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
                set_ann(expression, "in_func", self.current_func)


            return self.new_expr_desc(expr_desc.def_set, True)

        elif expression.type == "Identifier":
            def_set = self.get_def_set_by_name(state, expression.name)
            if len(def_set) == 0:
                self.free_vars.add(expression.name)
            return self.new_expr_desc(def_set, False)

        elif expression.type == "CallExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.callee]
            for a in expression.arguments:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, a]
            if not expression.callee_is_pure:
                self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
            return self.new_expr_desc(expr_desc.def_set, expr_desc.has_side_effects or not expression.callee_is_pure)
        
        elif expression.type == "ThisExpression":
            return self.new_expr_desc()

        elif expression.type == "AwaitExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.argument]
            return expr_desc

        elif expression.type == "UnaryExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.argument]
            return expr_desc

        elif expression.type == "FunctionExpression" or expression.type == "ArrowFunctionExpression":
            yield [self.handle_function_body, state, expression.body]
            expr_desc = self.new_expr_desc()
            return expr_desc

        elif expression.type == "NewExpression":
            expr_desc = self.new_expr_desc()
            for a in expression.arguments:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, a]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
            return self.new_expr_desc(expr_desc.def_set, True)

        elif expression.type == "SequenceExpression":
            expr_desc = self.new_expr_desc()
            for elem in expression.expressions:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, elem]
            return expr_desc


    def on_end(self, state : Domain.State) -> None:
        """
        Called when the analysis ends.

        :param Domain.State state: the current (final) state
        """        
        useless = set()
        change = True
        while change:
            previous_useless = useless.copy()
            for d in self.defs:
                useful_count = len([u for u in get_ann(node_from_id(d), "used_by") if u not in useless and u != d])
                if useful_count == 0:
                    useless.add(d)
            change = (useless != previous_useless)
        decl_useless = set()
        for d in self.defs:
            useful_count = len([u for u in get_ann(node_from_id(d), "decl_used_by") if u not in useless and u != d])
            if useful_count == 0:
                decl_useless.add(d)
        for d in self.defs:
            assign_expr = node_from_id(d)
            set_ann(assign_expr, "useless", d in useless)
            set_ann(assign_expr, "decl_useless", d in decl_useless)


class UselessVarRemover(CodeTransform):
    def __init__(self, ast, only_comment = False):
        self.only_comment = only_comment
        super().__init__(ast, "Useless Variable Remover")


    def process_assignment(self, assign : esprima.nodes.Node, _type : str) -> None:
        """
        Comment the assignment

        :param esprima.nodes.Node assign: The assignment
        :param str _type: The assignment type (can be "Assign" or "Declare")
        """        
        if self.only_comment:
            if get_ann(assign, "useless") == True:
                u = "Val-Unused-locally, "
            elif get_ann(assign, "useless") == False:
                u = "Val-Used-locally, "
            else:
                u = "Always-Keep, "
            comm = " Type: " + _type + ", ID: " + str(id_from_node(assign)) + ", " + u + "Locally-Used-By: " + str(get_ann(assign, "used_by") or "{}") + ", "
            if _type == "Declare":
                if get_ann(assign, "decl_useless"):
                    comm += "Decl-Unused, "
                else:
                    comm += "Decl-Used, "
                comm += "Decl-Used-By: " + str(get_ann(assign, "decl_used_by") or "{}") + ", "
            if get_ann(assign, "rhs_side_effects"):
                comm += "RValue-Has-Side-Effects, "
            else:
                comm += "RValue-Has-No-Side-Effects, "
            func = get_ann(assign, "in_func")
            if func is None:
                comm += "Not-In-Function "
            else:
                comm += "In-Function, "
                if _type == "Declare":
                    name = assign.id.name
                elif _type == "Update":
                    name = assign.argument.name
                else:
                    name = assign.left.name
                if name in get_ann(func, "inner_free_vars"):
                    comm += "Used-By-Closures"
                else:
                    comm += "Unused-By-Closures"

            assign.trailingComments = [{"type":"Block", "value": comm}]
        elif assign.type == "AssignmentExpression":
            func = get_ann(assign, "in_func")
            if get_ann(assign, "useless") and func and assign.left.name not in get_ann(func, "inner_free_vars") and not get_ann(assign, "rhs_side_effects"):
                assign.__dict__ = assign.right.__dict__

    def process_block(self, body: List[esprima.nodes.Node]) -> None:
        bye = []
        if self.only_comment:
            return
        for b in body:
            if b.type == "ExpressionStatement":
                func = get_ann(b.expression, "in_func")
                if b.expression.type == "AssignmentExpression":
                    if get_ann(b.expression, "useless") and func and b.expression.left.name not in get_ann(func, "inner_free_vars"):
                        if get_ann(b.expression, "rhs_side_effects"):
                            b.expression.__dict__ = b.expression.right.__dict__
                        else:
                            bye.append(b)
                if b.expression.type == "UpdateExpression":
                    if get_ann(b.expression, "useless") and func and b.expression.argument.name not in get_ann(func, "inner_free_vars"):
                        bye.append(b)


            if b.type == "VariableDeclaration":
                decl_bye = []
                for decl in b.declarations:
                    if decl.id.type == "ObjectPattern":
                        pass #TODO
                    else:
                        func = get_ann(decl, "in_func")
                        if get_ann(decl, "useless") and func and decl.id.name not in get_ann(func, "inner_free_vars"):
                            if get_ann(decl, "decl_useless") and not get_ann(decl, "rhs_side_effects"):
                                decl_bye.append(decl)
                            elif not get_ann(decl, "decl_useless") and not get_ann(decl, "rhs_side_effects"):
                                decl.init = None
                for db in decl_bye:
                    b.declarations.remove(db)
                if len(b.declarations) == 0:
                    bye.append(b)

        for b in bye:
            body.remove(b)


    def before_statement(self, o : esprima.nodes.Node) -> bool:
        """
        Called before we encounter a statement

        :param esprima.nodes.Node o: The statement
        :rtype bool:
        :return: True if we continue to process the statement, False otherwise
        """        
        if o.type == "VariableDeclaration":
            for decl in o.declarations:
                self.process_assignment(decl, "Declare")
        if o.type == "BlockStatement":
            self.process_block(o.body)
        return True


    def before_expression(self, o : esprima.nodes.Node) -> bool:
        """
        Called before we encounter an expression

        :param esprima.nodes.Node o: The expression
        :rtype bool:
        :return: True if we continue to process the expression, False otherwise
        """        
        if id_from_node(o) is None:
            return True

        if o.type == "AssignmentExpression":
            self.process_assignment(o, "Assign")
        elif o.type == "UpdateExpression":
            self.process_assignment(o, "Update")

        if self.only_comment:
            if o.type == "CallExpression" and id_from_node(o) is not None:
                o.trailingComments = [{"type":"Block", "value":" Type: Call, ID: " + str(id_from_node(o)) + " "}]
            elif get_ann(o, "test"):
                o.trailingComments = [{"type":"Block", "value":" Type: Test, ID: " + str(id_from_node(o)) + " "}]
        return True

    def run(self):
        VarDefInterpreter(self.ast).run()
        super().run()

class SideEffectMarker(CodeTransform):
    def run(self) -> None:
        clear_ann("side_effects")
        super().run()
        
    def __init__(self, ast : esprima.nodes.Node, pures : List[str]= []) -> None:
        self.pures = pures
        self.id_pures = set()        
        super().__init__(ast, None)

    def after_expression(self, expr, side_effects : List[bool]) -> bool:
        if expr.type == "AssignmentExpression" or expr.type == "UpdateExpression":
            r = True
        elif expr.type == "CallExpression":
            if expr.callee.name in self.pures:
                r = False
                if expr.callee.notrans_static_value.target():
                    self.id_pures.add(expr.callee.notrans_static_value.target())
            elif expr.callee.notrans_static_value.target() in self.id_pures:
                r = False
            elif expr.callee_is_pure:
                r = False
            else:
                r = True
        else:
            r = reduce(lambda x,y : x or y, side_effects, False)
        set_ann(expr, "side_effects", r)
        return r
            
class UselessStatementRemover(CodeTransform):
    def run(self) -> None:
        super().run()
        
    def __init__(self, ast : esprima.nodes.Node, pures : List[str]= []) -> None:
        self.pures = pures
        self.id_pures = set()        
        super().__init__(ast, "Useless Statement Remover")

    def process_statement_list(self, statement_list):
            bye = []
            for st in statement_list:
                if st.type == "ExpressionStatement" and not get_ann(st.expression, "side_effects"):
                    bye.append(st)
            for b in bye:
                statement_list.remove(b)

    def after_statement(self, statement, unused):
        if statement.type == "BlockStatement":
            self.process_statement_list(statement.body)

    def after_program(self, unused):
        self.process_statement_list(self.ast.body)

