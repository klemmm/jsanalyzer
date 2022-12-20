import random
import esprima
import re
from abstract import JSPrimitive, JSRef
from tools import call
from config import regexp_rename, rename_length, simplify_expressions, simplify_function_calls, simplify_control_flow, max_unroll_ratio, remove_dead_code
from functools import reduce
from collections import namedtuple
from node_tools import get_ann, set_ann, del_ann, node_from_id, id_from_node
from typing import Set

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
            yield [self.on_statement, state, statement]

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
            yield [self.on_statement, state, statement]
       
        elif statement.type == "ReturnStatement":
            yield [self.on_statement, state, statement]

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
            yield [self.on_statement, state, statement]

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
            yield [self.on_statement, state, statement]

        elif statement.type == "ClassBody":
            yield [self.on_statement, state, statement]

        elif statement.type == "MethodDefinition":
            yield [self.on_statement, state, statement]

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
        self.id_pures = set()

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
        if o.type == "CallExpression" and o.callee.name in self.pures:
            if isinstance(o.callee.notrans_static_value, JSRef):
                self.id_pures.add(o.callee.notrans_static_value.target())
        if o.type == "CallExpression" and not o.callee_is_pure and o.callee.name not in self.pures and (not isinstance(o.callee.notrans_static_value, JSRef) or o.callee.notrans_static_value.target() not in self.id_pures):
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

    ExprDesc = namedtuple("ExprDesc", "def_set has_side_effects")
    Def = namedtuple("Def", "name def_id")

    class Domain(object):
        class State(set):
            pass

        """
        Creates a new initial state

        :return: new initial state
        """
        def init_state(self) -> State:
            return self.State({None})

        """
        Creates a new bottom state

        :return: new bottom state
        """
        def bottom_state(self) -> State:
            return self.State({None})

        """
        Tells the state is bottom
        
        :param State state: the state to check
        :rtype: bool
        :return: True if the passed state is bottom
        """
        def is_bottom(self, state : State) -> bool:
            return state == self.State({None})

        """
        Copy a state, returning the copy
        
        :param State state: the source state
        :rtype: State
        :return: the copied state
        """
        def clone_state(self, state : State) -> State:
            return state.copy()

        """
        Join two states, store result in state_dest
        
        :param State state_dest: the dest state
        :param State state_source: the source state
        """
        def join_state(self, state_dest : State, state_source : State) -> None:
            if self.is_bottom(state_source):
                return
            elif self.is_bottom(state_dest):
                self.assign_state(state_dest, state_source)
            else:
                state_dest.update(state_source)

        """
        Assign source state to destination state
        
        :param State state_dest: the dest state
        :param State state_source: the source state
        """
        def assign_state(self, state_dest : State, state_source : State) -> None:
            state_dest.clear()
            state_dest.update(state_source)

    def __init__(self, ast : esprima.nodes.Node) -> None:
        self.defs = set()
        self.stack = []
        self.node_stack = []
        self.current_func = None
        super().__init__(ast, self.Domain(), "Variable Definition")
   
    """
    Called when the analysis enters a function

    :param Domain.State state: the current state
    :param esprima.nodes.Node statement: the function body 
    """
    def on_enter_function(self, state : Domain.State, statement : esprima.nodes.Node) -> None:
        self.stack.append(self.domain.clone_state(state))
        self.node_stack.append(self.current_func)
        self.current_func = statement
        state.clear()

    """
    Called when the analysis leaves a function

    :param Domain.State state: the current state
    :param esprima.nodes.Node statement: the function body 
    """
    def on_leave_function(self, state : Domain.State, statement : esprima.nodes.Node) -> None:
        p = self.stack.pop()
        self.node_stack.pop()
        self.domain.assign_state(state, p)

    """
    Create a link from a set of definitions to an use
    
    :param Set[int] def_set: the set of definitions (set of ids)
    :param int use: the use (by id)
    """
    def link_def_set_to_use(self, def_set : Set[int], use : int) -> None:
        for used_assignment_id in def_set:
            used_assignment = node_from_id(used_assignment_id)
            get_ann(used_assignment, "used_by").add(use)

    """
    Get a set of definitions matching a variable name
    
    :param Domain.State state: the current state
    :param str name: the variable name
    :rtype: Set[int]
    :return: the set of definitions (set of ids)
    """
    def get_def_set_by_name(self, state : Domain.State, name : str) -> Set[int]:
        return set([x.def_id for x in state if x.name == name])

    """
    Removes definitions from state matching some variable name
    
    :param Domain.State state: the current state
    :param str name: the variable name
    """
    def kill_def_set_by_name(self, state : Domain.State, name : str) -> None:
        state.difference_update([x for x in state if x.name == name])

    """
    Create a definition based on the variable name and expression
    
    :param Domain.State state: the current state
    :param esprima.nodes.Node expression: the expression that will be stored in the variable
    :param str name: the variable name
    """
    def create_def(self, state : Domain.State, expression : esprima.nodes.Node, name : str) -> None:
        self.defs.add(id_from_node(expression))
        set_ann(expression, "used_by", set())
        self.kill_def_set_by_name(state, name)
        state.add(self.Def(name, id_from_node(expression)))

    """
    Returns a new Expression Descriptor. The Expression Descriptor contains a set of definitions used
    by an expression, and also whether the expression has any side-effects.

    :param Set[int] def_set: The set of definitions used by the expression (default: empty set)
    :param bool has_side_effects: True if the expression has side effects (default: False)
    :rtype: ExprDesc
    :return: The new expression descriptor
    """
    def new_expr_desc(self, def_set : Set[int] = set(), has_side_effects : bool = False) -> ExprDesc:
        return self.ExprDesc(def_set, has_side_effects)

    """
    Updates an Expression Descriptor to take into account a new expression.

    :param Domain.State state: the current state
    :param ExprDesc expr_desc: the current expression descriptor
    :param: esprima.nodes.Node expr: the expression used to update the descriptor
    :rtype: ExprDesc
    :return: The updated expression descriptor
    """
    def updated_expr_desc(self, state : Domain.State, expr_desc : ExprDesc, expr : esprima.nodes.Node) -> ExprDesc:
        if expr.type == "BlockStatement":
            return self.new_expr_desc() #TODO
        sub_expr_desc = yield [self.do_expression, state, expr]
        r = self.new_expr_desc(sub_expr_desc.def_set.union(expr_desc.def_set), sub_expr_desc.has_side_effects or expr_desc.has_side_effects)
        return r

    """
    Called when the analysis encounters a statement

    :param Domain.State state: the current state
    :param esprima.nodes.Node: the current statement
    """
    def on_statement(self, state : Domain.State, statement : esprima.nodes.Node) -> None:
        if self.domain.is_bottom(state):
            return

        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                expr_desc = self.new_expr_desc()
                if decl.id.type == "ObjectPattern":
                    print(decl.id)
                else:
                    self.create_def(state, decl, decl.id.name)
                if decl.init is not None:
                    expr_desc = yield [self.updated_expr_desc, state, expr_desc, decl.init]
                    self.link_def_set_to_use(expr_desc.def_set, id_from_node(decl))
                    set_ann(decl, "side_effects", expr_desc.has_side_effects)
        elif statement.type == "FunctionDeclaration":
            if self.current_func is not None:
                set_ann(self.current_func, "has_inner_func", True)


    """
    Called when the analysis encounters an expression

    :param Domain.State state state: the current state
    :param esprima.nodes.Node expression: the current expression
    :param bool test: True if the expression is used as a condition (in while/for/if)
    :rtype: ExprDesc
    :return: the expression descriptor corresponding to the expression
    """
    def on_expression(self, state : Domain.State, expression : esprima.nodes.Node, test : bool = False) -> ExprDesc:
        if self.domain.is_bottom(state):
            return self.new_expr_desc()

        if expression.type == "AssignmentExpression":
            expr_desc = self.new_expr_desc()
            if expression.left.type == "MemberExpression" or expression.operator != "=":
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.left]
            if bool(self.get_def_set_by_name(state, expression.left.name)):
                self.create_def(state, expression, expression.left.name)
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.right]
            self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
            set_ann(expression, "side_effects", expr_desc.has_side_effects)
            return self.new_expr_desc(expr_desc.def_set, True)

        elif expression.type == "BinaryExpression" or expression.type == "LogicalExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.left]
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.right]
            if test:
                set_ann(expression, "test", True)
                self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
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
            return self.new_expr_desc(expr_desc.def_set, True)

        elif expression.type == "Identifier":
            return self.new_expr_desc(self.get_def_set_by_name(state, expression.name), False)

        elif expression.type == "CallExpression":
            expr_desc = self.new_expr_desc()
            for a in expression.arguments:
                expr_desc = yield [self.updated_expr_desc, state, expr_desc, a]
            if not expression.callee_is_pure:
                self.link_def_set_to_use(expr_desc.def_set, id_from_node(expression))
            return self.new_expr_desc(expr_desc.def_set, expr_desc.has_side_effects or not expression.callee_is_pure)

        elif expression.type == "AwaitExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.argument]
            return expr_desc

        elif expression.type == "UnaryExpression":
            expr_desc = self.new_expr_desc()
            expr_desc = yield [self.updated_expr_desc, state, expr_desc, expression.argument]
            return expr_desc

        elif expression.type == "FunctionExpression" or expression.type == "ArrowFunctionExpression":
            if self.current_func is not None:
                set_ann(self.current_func, "has_inner_func", True)
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

    """
    Called when the analysis ends.

    :param Domain.State state: the current (final) state
    """
    def on_end(self, state : Domain.State) -> None:
        useless = set()
        change = True
        while change:
            previous_useless = useless.copy()
            for d in self.defs:
                useful_count = len([u for u in get_ann(node_from_id(d), "used_by") if u not in useless and u != d])
                if useful_count == 0:
                    useless.add(d)
            change = (useless != previous_useless)
        for d in self.defs:
            assign_expr = node_from_id(d)
            set_ann(assign_expr, "useless", d in useless)

class UselessVarRemover(CodeTransform):
    def __init__(self, ast, only_comment = False):
        self.only_comment = only_comment
        super().__init__(ast, "Useless Variable Remover")

    """
    Comment the assignment

    :param esprima.nodes.Node assign: The assignment
    :param str _type: The assignment type (can be "Assign" or "Declare")
    """
    def process_assignment(self, assign : esprima.nodes.Node, _type : str) -> None:
        if self.only_comment:
            if get_ann(assign, "useless") == True:
                u = "Useless, "
            elif get_ann(assign, "useless") == False:
                u = "Useful, "
            else:
                u = "Always-Keep, "
            comm = " Type: " + _type + ", ID: " + str(id_from_node(assign)) + ", " + u + "Used-By: " + str(get_ann(assign, "used_by") or "{}") + " "
            if get_ann(assign, "side_effects"):
                comm += "RValue-Has-Side-Effects "
            else:
                comm += "RValue-Has-No-Side-Effects "
            assign.trailingComments = [{"type":"Block", "value": comm}]

    def process_block(self, body: [esprima.nodes.Node]) -> None:
        bye = []
        for b in body:
            if b.type == "ExpressionStatement":
                if b.expression.type == "AssignmentExpression":
                    if get_ann(b.expression, "useless"):
                        if get_ann(b.expression, "side_effects"):
                            b.expression.__dict__ = b.expression.right.__dict__
                        else:
                            bye.append(b)
            if b.type == "VariableDeclaration":
                for decl in b.declarations:
                    if get_ann(decl, "useless") and not get_ann(decl, "side_effects"):
                        decl.init = None
        for b in bye:
            body.remove(b)

    """
    Called before we encounter a statement

    :param esprima.nodes.Node o: The statement
    :rtype bool:
    :return: True if we continue to process the statement, False otherwise
    """
    def before_statement(self, o : esprima.nodes.Node) -> bool:
        if o.type == "VariableDeclaration":
            for decl in o.declarations:
                self.process_assignment(decl, "Declare")
        if o.type == "FunctionDeclaration":
            if get_ann(o.body, "has_inner_func"):
                return False
        if o.type == "BlockStatement":
            self.process_block(o.body)
        return True

    """
    Called before we encounter an expression

    :param esprima.nodes.Node o: The expression
    :rtype bool:
    :return: True if we continue to process the expression, False otherwise
    """
    def before_expression(self, o : esprima.nodes.Node) -> bool:
        if id_from_node(o) is None:
            return True

        if o.type == "AssignmentExpression":
            self.process_assignment(o, "Assign")

        if self.only_comment:
            if o.type == "CallExpression" and id_from_node(o) is not None:
                o.trailingComments = [{"type":"Block", "value":" Type: Call, ID: " + str(id_from_node(o)) + " "}]
            elif get_ann(o, "test"):
                o.trailingComments = [{"type":"Block", "value":" Type: Test, ID: " + str(id_from_node(o)) + " "}]

        if o.type == "FunctionExpression" or o.type == "ArrowFunctionExpression":
            if get_ann(o.body, "has_inner_func"):
                return False
        return True

    def run(self):
        VarDefInterpreter(self.ast).run()
        super().run()
