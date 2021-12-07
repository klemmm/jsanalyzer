from abstract import State, JSClosure, JSObject, JSUndefNaN, JSTop, JSRef, JSSimFct, JSPrimitive, JSValue

from debug import debug

import plugin_manager
import output
import config
import sys

to_inspect = [ "toto" ]

class Interpreter(object):
    def __init__(self, ast):
        self.ast = ast
        self.funcs = []

    @staticmethod
    def truth_value(v):
        return plugin_manager.to_bool(v)
        
    def scope_lookup(self, state, name):
        debug("looking up:", name, "...", end="")
        if name in state.loc:
            debug("found in local scope")
            return state.loc
        if name in self.closure:
            debug("found in closure scope")
            return self.closure
        if name in state.glob:
            debug("found in global scope")
        else:
            debug("not found")
        return state.glob

    def calc_expr_and_store(self, state, expr):
        result = self.calc_expr(state, expr)
        if result is not JSTop and result is not None:
            if expr.static_value is None:
                expr.static_value = result.clone()
            else:
                if type(expr.static_value) != type(result) or expr.static_value != result:
                    expr.static_value = JSTop
        return result

    #Takes state, expression, and returns a JSValue
    def calc_expr(self, state, expr):
        if expr.type == "Literal":
            if expr.value is None:
                return JSUndefNaN
            return JSPrimitive(expr.value)

        elif expr.type == "Identifier":
            scope = self.scope_lookup(state, expr.name)
            if expr.name in scope:
                return scope[expr.name]
            else:
                return JSTop #untracked identifier

        elif expr.type == "UpdateExpression":
            return JSTop #TODO

        elif expr.type == "NewExpression":
            for argument in expr.arguments:
                arg_val = self.calc_expr_and_store(state, argument)

            return JSTop
      
        elif expr.type == "ConditionalExpression":
            abs_test_result = self.calc_expr_and_store(state, expr.test)

            if abs_test_result is JSTop:
                state_then = state
                state_else = state.clone()
                expr_then = self.calc_expr_and_store(state_then, expr.consequent)
                expr_else = self.calc_expr_and_store(state_else, expr.alternate)
                state_then.join(state_else)
                if type(expr_then) == type(expr_else) and expr_then == expr_else:
                    return expr_then
                else:
                    return JSTop

            if Interpreter.truth_value(abs_test_result):
                return self.calc_expr_and_store(state, expr.consequent)
            else:
                return self.calc_expr_and_store(state, expr.alternate)

        elif expr.type == "SequenceExpression":
            for e in expr.expressions:
                r = self.calc_expr_and_store(state, e)
            return r

        elif expr.type == "AssignmentExpression":
            abs_rvalue = self.calc_expr_and_store(state, expr.right)

            if expr.left.type == "Identifier":
                scope = self.scope_lookup(state, expr.left.name)
                if abs_rvalue is JSTop:
                    scope.pop(expr.left.name, None)
                else:
                    scope[expr.left.name] = abs_rvalue
                    if expr.left.name in to_inspect:
                        print(expr.left.name, ":", abs_rvalue)
                        if isinstance(abs_rvalue, JSRef):
                            print("pointed object:", state.objs[abs_rvalue.ref_id])

            elif expr.left.type == "MemberExpression":
                abs_object = self.calc_expr_and_store(state, expr.left.object)
                if expr.left.computed is False:
                    if abs_object is JSTop:
                        return JSTop
                    ref_id = abs_object.ref_id
                    if ref_id in state.objs:
                        if abs_rvalue is JSTop:
                            state.objs[ref_id].properties.pop(expr.left.property.name, None)
                        else:
                            state.objs[ref_id].properties[expr.left.property.name] = abs_rvalue
                    else:
                        raise ValueError("Referenced object not found, id=" + str(ref_id))
                else: #expression
                    abs_property = self.calc_expr_and_store(state, expr.left.property)
                    if abs_object is JSTop:
                        return JSTop
                    ref_id = abs_object.ref_id
                    if isinstance(abs_property, JSPrimitive):
                        if ref_id in state.objs:
                            if abs_rvalue is JSTop:
                                state.objs[ref_id].properties.pop(abs_property.val, None)
                            else:
                                state.objs[ref_id].properties[abs_property.val] = abs_rvalue
                        else:
                            raise ValueError("Referenced object not found, id=" + str(ref_id))

                    elif abs_property is not JSTop:
                        raise ValueError("Invalid property type:" + str(type(abs_property)))
            else:
                raise ValueError("Invalid assignment left type")
            return abs_rvalue
        
        elif expr.type == "ObjectExpression":
            properties = {}
            for prop in expr.properties:
                prop_val = self.calc_expr_and_store(state, prop.value)
                if prop_val is JSTop:
                    continue
                if not prop.computed:
                    properties[prop.key.value] = prop_val
                else:
                    prop_key = self.calc_expr_and_store(state, prop.key)
                    if isinstance(prop_key, JSPrimitive):
                        properties[prop_key.val] = prop_val
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(properties)
            return JSRef(obj_id)

        elif expr.type == "ArrayExpression":
            elements = {}
            i = 0
            for elem in expr.elements:
                elements[i] = self.calc_expr_and_store(state, elem)
                i = i + 1
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(elements)
            return JSRef(obj_id)

        elif expr.type == "MemberExpression":
            abs_object = self.calc_expr_and_store(state, expr.object)
            ret_top = False
            if abs_object is JSTop or abs_object is JSUndefNaN:
                ret_top = True

            if isinstance(abs_object, JSPrimitive) and type(abs_object.val) is str:
                ret_top = True


            if expr.computed is False:
                if ret_top:
                    return JSTop
                ref_id = abs_object.ref_id
                return state.objs[ref_id].member(expr.property.name)
            else: #expression
                abs_property = self.calc_expr_and_store(state, expr.property)
                if ret_top:
                    return JSTop
                ref_id = abs_object.ref_id
                if ref_id not in state.objs:
                    raise ValueError("Referenced object not found, id=", str(ref_id))
                if isinstance(abs_property, JSPrimitive):
                    return state.objs[ref_id].member(abs_property.val)
                elif abs_property is JSTop:
                    return JSTop
                else:
                    raise ValueError("Invalid property type: " + str(type(abs_property)))

        elif expr.type == "UnaryExpression":
            argument = self.calc_expr_and_store(state, expr.argument)
            return plugin_manager.handle_unary_operation(expr.operator, argument)

        elif expr.type == "BinaryExpression" or expr.type == "LogicalExpression":
            left = self.calc_expr_and_store(state, expr.left)
            right = self.calc_expr_and_store(state, expr.right)
            return plugin_manager.handle_binary_operation(expr.operator, left, right)

        elif expr.type == "FunctionExpression" or expr.type == "ArrowFunctionExpression":
            if state.loc is state.glob:
                f = JSClosure(expr.params, expr.body, {}, {})
            else:
                closure_env = {}
                State.dict_assign(closure_env, state.loc)
                for k in self.closure:
                    if k not in closure_env:
                        closure_env[k] = self.closure[k].clone()
                closure_objs = {}
                State.dict_assign(closure_objs, state.objs)
                f = JSClosure(expr.params, expr.body, closure_env, closure_objs)
            
            if f.body.seen is not True:
                f.body.seen = True
                f.body.name = "<anonymous>"
                self.funcs.append(f)
            return f

        elif expr.type == "CallExpression":
            callee = self.calc_expr_and_store(state, expr.callee)
            #callee can be either JSTop, JSClosure or JSSimFct
               
            if isinstance(callee, JSSimFct):
                args = []
                for argument in expr.arguments:
                    arg_val = self.calc_expr_and_store(state, argument)
                    args.append(arg_val)
                return callee.fct(*args)




            if isinstance(callee, JSClosure):
                callee.body.used = True
            saved_return = self.return_value
            saved_rstate = self.return_state
            saved_closure = self.closure
            self.return_value = None
            self.return_state = State.bottom()
            saved_loc = state.loc
            new_loc = {}
            
            i = 0
            for argument in expr.arguments:
                if isinstance(callee, JSClosure):
                    new_loc[callee.params[i].name] = self.calc_expr_and_store(state, argument)
                else:
                    self.calc_expr_and_store(state, argument)
                i = i + 1

            state.loc = new_loc
            if isinstance(callee, JSClosure):
                self.closure = callee.env
                if expr.callee.name == "ToCache":
                    print("ToCache")
                debug("Evaluating function", expr.callee.name,"with closure",callee.env, "and locs", state.loc)
                self.do_statement(state, callee.body)
                debug("return value for", expr.callee.name, "is", self.return_value)
                debug("return state:", self.return_state)
                state.join(self.return_state)

                my_return = self.return_value
            else:
                my_return = JSTop
            self.return_value = saved_return
            self.return_state = saved_rstate
            self.closure = saved_closure
            state.loc = saved_loc
            if my_return is None:
                return JSUndefNaN
            return my_return

        else:
            raise ValueError("Expr type not handled:" + expr.type)
        return

    def do_vardecl(self, state, decl):
        if decl.type == "VariableDeclarator":
            scope = state.loc
            if decl.init is not None:
                val = self.calc_expr_and_store(state, decl.init)
                if decl.id.name in to_inspect:
                    print(decl.id.name, ":", val)
                    if isinstance(val, JSRef):
                        print("pointed object:", state.objs[val.ref_id])
                if val is not JSTop:
                    scope[decl.id.name] = val
            else:
                scope[decl.id.name] = JSUndefNaN
        else:
            raise ValueError("Vardecl type not handled:" + decl.type)


    def do_exprstat(self, state, expr):
        self.calc_expr_and_store(state, expr)

    def do_while(self, state, test, body):
        prev_state = None
        i = 0
        warned = False
        saved_loopexit = self.loopexit_state
        self.loopexit_state = State.bottom()
        exit = False
        while not exit:
            saved_loopcont = self.loopcont_state
            self.loopcont_state = State.bottom()
            i = i + 1
            abs_test_result = self.calc_expr_and_store(state, test)
            if config.max_iter is not None and i > config.max_iter:
                if not warned:
                    print("[warning] Loop unrolling stopped after " + str(config.max_iter) + " iterations")
                    warned = True
                abs_test_result = JSTop
            if abs_test_result is JSTop:
                prev_state = state.clone()
                header_state = state.clone()
                self.do_sequence(state, body)
                state.join(header_state)
                state.join(self.loopcont_state)
                self.loopcont_state = saved_loopcont
                if state == prev_state:
                    debug("Exiting loop after " + str(i) + " iterations because abstract state is stable (condition is unknown)")
                    exit = True 
            
            elif Interpreter.truth_value(abs_test_result):
                prev_state = state.clone()
                self.do_sequence(state, body)
                state.join(self.loopcont_state)
                self.loopcont_state = saved_loopcont
                if state == prev_state:
                    debug("Exiting loop after " + str(i) + " iterations because abstract state is stable (condition is true)")
                    state.set_to_bottom()
                    exit = True
            else:
                debug("Exiting loop after " + str(i) + " iterations because condition is false")
                exit = True


        state.join(self.loopexit_state)
        self.loopexit_state = saved_loopexit

    def do_switch(self, state, discriminant, cases):
        abs_discr = self.calc_expr_and_store(state, discriminant)
        has_true = False
        states_after = []
        for case in cases:
            abs_test = self.calc_expr_and_store(state, case.test)
            if isinstance(abs_test, JSPrimitive) and isinstance(abs_discr, JSPrimitive) and abs_test.val != abs_discr.val:
                continue #No
            elif isinstance(abs_test, JSPrimitive) and isinstance(abs_discr, JSPrimitive) and abs_test.val == abs_discr.val:
                has_true = True
                state_clone = state.clone()
                self.do_sequence(state_clone, case.consequent) #Yes
                states_after.append(state_clone)
                break
            else:
                state_clone = state.clone()
                self.do_sequence(state_clone, case.consequent) #Maybe
                states_after.append(state_clone)
        if has_true:
            state.set_to_bottom()
        for s in states_after:
            state.join(s)

    def do_if(self, state, test, consequent, alternate):
        abs_test_result = self.calc_expr_and_store(state, test)

        if abs_test_result is JSTop:
            state_then = state
            state_else = state.clone()
            self.do_statement(state_then, consequent)
            if alternate is not None:
                self.do_statement(state_else, alternate)
            state_then.join(state_else)
            return

        if Interpreter.truth_value(abs_test_result):
            self.do_statement(state, consequent)
        else:
            if alternate is not None:
                self.do_statement(state, alternate)

    def do_fundecl(self, state, name, params, body):
        scope = state.loc
        if state.glob is state.loc:
            scope[name] = JSClosure(params, body, {}, {})
        else:
            closure_env = {}
            State.dict_assign(closure_env, state.loc)
            for k in self.closure:
                if k not in closure_env:
                    closure_env[k] = self.closure[k].clone()
            closure_objs = {}
            State.dict_assign(closure_objs, state.objs)

            scope[name] = JSClosure(params, body, closure_env, closure_objs)

        if scope[name].body.seen is not True:
            scope[name].body.seen = True
            scope[name].body.name = name
            self.funcs.append(scope[name])

    def do_break(self, state):
        self.loopexit_state.join(state)
        state.set_to_bottom()
    
    def do_continue(self, state):
        self.loopcont_state.join(state)
        state.set_to_bottom()

    def do_return(self, state, argument):
        self.return_state.join(state)
        if argument is None:
            arg_val = JSUndefNaN
        else:
            arg_val = self.calc_expr_and_store(state, argument)
        if self.return_value is None:
            self.return_value = arg_val.clone()
        elif not (type(self.return_value) == type(arg_val) and self.return_value == arg_val):
            self.return_value = JSTop
        state.set_to_bottom()

    def do_statement(self, state, statement):
        if state.is_bottom:
            debug("Ignoring dead code: ", statement.type)
            return

        debug("Current state: ", state)
        debug("Interpreting statement:", statement.type)

        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.do_vardecl(state, decl)

        elif statement.type == "ExpressionStatement":
            self.do_exprstat(state, statement.expression)

        elif statement.type == "IfStatement":
            self.do_if(state, statement.test, statement.consequent, statement.alternate)

        elif statement.type == "FunctionDeclaration":
            self.do_fundecl(state, statement.id.name, statement.params, statement.body)
       
        elif statement.type == "ReturnStatement":
            self.do_return(state, statement.argument)

        elif statement.type == "WhileStatement":
            self.do_while(state, statement.test, statement.body.body)
        
        elif statement.type == "BreakStatement":
            self.do_break(state)
        
        elif statement.type == "ContinueStatement":
            self.do_continue(state)

        elif statement.type == "TryStatement":
            self.do_statement(state, statement.block) #TODO we assume that exceptions never happen  ¯\_(ツ)_/¯
        
        elif statement.type == "BlockStatement":
            self.do_sequence_with_hoisting(state, statement.body)
        
        elif statement.type == "EmptyStatement":
            pass

        elif statement.type == "SwitchStatement":
            self.do_switch(state, statement.discriminant, statement.cases)

        else:
            raise ValueError("Statement type not handled: " + statement.type)

    def do_sequence(self, state, sequence):
        for statement in sequence:
            self.do_statement(state, statement)
    
    def do_sequence_with_hoisting(self, state, sequence):
        #half-assed hoisting
        for statement in sequence:
            if statement.type == "FunctionDeclaration" or statement.type == "AVariableDeclaration":
                self.do_statement(state, statement)
        
        for statement in sequence:
            if not (statement.type == "FunctionDeclaration" or statement.type == "AVariableDeclaration"):
                self.do_statement(state, statement)


    def run(self):
        state = State.top()
        self.return_value = None
        self.closure = {}
        self.return_state = State.bottom()
        self.loopexit_state = State.bottom()
        self.loopcont_state = State.bottom()
        state.loc = state.glob

        for (name, value) in plugin_manager.global_symbols:
            state.glob[name] = value

        for (ref_id, obj) in plugin_manager.preexisting_objects:
            state.objs[ref_id] = obj

        State.set_next_id(plugin_manager.ref_id)

        debug("Dumping Abstract Syntax Tree:")
        debug(self.ast.body)
        debug("Init state: ", str(state))
        print("Starting abstract interpretation...")
        self.do_sequence_with_hoisting(state, self.ast.body)
        print("\nAnalysis finished")

