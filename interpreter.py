from abstract import State, JSClosure, JSObject, JSUndefNaN, JSTop, JSRef, JSSimFct, JSPrimitive, JSValue

from debug import debug

import plugin_manager
import config


class Interpreter(object):
    def __init__(self, ast):
        self.ast = ast

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

    #Takes state, expression, and returns a JSValue
    def calc_expr(self, state, expr):
        if expr.type == "Literal":
            return JSPrimitive(expr.value)

        elif expr.type == "Identifier":
            scope = self.scope_lookup(state, expr.name)
            if expr.name in scope:
                return scope[expr.name]
            else:
                return JSTop #untracked identifier

        elif expr.type == "ArrayExpression":
            elements = {}
            i = 0
            for elem in expr.elements:
                elements[i] = self.calc_expr(state, elem)
                i = i + 1
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(elements)
            return JSRef(obj_id)

        elif expr.type == "MemberExpression":
            abs_object = self.calc_expr(state, expr.object)
            if abs_object is JSTop:
                return JSTop #cannot determine concrete object
            ref_id = abs_object.ref_id

            if expr.computed is False:
                return state.objs[ref_id].member(expr.property.name)
            else: #expression
                abs_property = self.calc_expr(state, expr.property)
                if isinstance(abs_property, JSPrimitive):
                    return state.objs[ref_id].member(abs_property.val)
                elif abs_property is JSTop:
                    return JSTop
                else:
                    raise ValueError("Invalid property type: " + str(type(abs_property)))

        elif expr.type == "UnaryExpression":
            argument = self.calc_expr(state, expr.argument)
            return plugin_manager.handle_unary_operation(expr.operator, argument)

        elif expr.type == "BinaryExpression":
            left = self.calc_expr(state, expr.left)
            right = self.calc_expr(state, expr.right)
            return plugin_manager.handle_binary_operation(expr.operator, left, right)

        elif expr.type == "FunctionExpression":
            if state.loc is state.glob:
                return JSClosure(expr.params, expr.body.body, {})
            else:
                closure_env = {}
                State.dict_assign(closure_env, state.loc)
                return JSClosure(expr.params, expr.body.body, closure_env)

        elif expr.type == "CallExpression":
            callee = self.calc_expr(state, expr.callee)
            #callee can be either JSTop, JSClosure or JSSimFct

            if callee is JSTop:
                return JSTop # Unsound, since it does not account for side-effects

            elif isinstance(callee, JSSimFct):
                args = []
                for argument in expr.arguments:
                    arg_val = self.calc_expr(state, argument)
                    args.append(arg_val)
                return callee.fct(*args)

            elif isinstance(callee, JSClosure):
                saved_return = self.return_value
                saved_rstate = self.return_state
                saved_closure = self.closure
                self.return_value = None
                self.return_state = State.bottom()
                saved_loc = state.loc
                new_loc = {}
                
                i = 0
                for argument in expr.arguments:
                    new_loc[callee.params[i].name] = self.calc_expr(state, argument)
                    i = i + 1
                state.loc = new_loc
                self.closure = callee.env
                debug("Evaluating function", expr.callee.name,"with closure",callee.env, "and locs", state.loc)
                self.do_sequence(state, callee.body)
                debug("return value for", expr.callee.name, "is", self.return_value)
                debug("return state:", self.return_state)
                state.join(self.return_state)
                my_return = self.return_value
                self.return_value = saved_return
                self.return_state = saved_rstate
                self.closure = saved_closure
                state.loc = saved_loc
                if my_return is None:
                    return JSUndefNaN
                return my_return
            else:
                raise ValueError("Attempted to call a non-callable value: " + str(callee))

        else:
            raise ValueError("Expr type not handled:" + expr.type)
        return

    def do_vardecl(self, state, decl):
        if decl.type == "VariableDeclarator":
            scope = state.loc
            if decl.init is not None:
                val = self.calc_expr(state, decl.init)
                if val is not JSTop:
                    scope[decl.id.name] = val
            else:
                scope[decl.id.name] = JSUndefNaN
        else:
            raise ValueError("Vardecl type not handled:" + decl.type)


    def do_exprstat(self, state, expr):
        if expr.type == "AssignmentExpression":
            abs_rvalue = self.calc_expr(state, expr.right)

            if expr.left.type == "Identifier":
                scope = self.scope_lookup(state, expr.left.name)
                if abs_rvalue is JSTop:
                    scope.pop(expr.left.name, None)
                else:
                    scope[expr.left.name] = abs_rvalue

            elif expr.left.type == "MemberExpression":
                abs_object = self.calc_expr(state, expr.left.object)
                ref_id = abs_object.ref_id
                if ref_id in state.objs:
                    if expr.left.computed is False:
                        if abs_rvalue is JSTop:
                            state.objs[ref_id].properties.pop(expr.left.property.name, None)
                        else:
                            state.objs[ref_id].properties[expr.left.property.name] = abs_rvalue
                    else: #expression
                        abs_property = self.calc_expr(state, expr.left.property)
                        if isinstance(abs_property, JSPrimitive):
                            if abs_rvalue is JSTop:
                                state.objs[ref_id].properties.pop(abs_property.val, None)
                            else:
                                state.objs[ref_id].properties[abs_property.val] = abs_rvalue
                        elif abs_property is not JSTop:
                            raise ValueError("Invalid property type:" + str(type(abs_property)))
                            
            else:
                raise ValueError("Invalid assignment left type")
        elif expr.type == "CallExpression":
            self.calc_expr(state, expr)
        else:
            raise ValueError("ExprStatement type not handled:" + expr.type)

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
            abs_test_result = self.calc_expr(state, test)
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
                if state == prev_state:
                    debug("Exiting loop after " + str(i) + " iterations because abstract state is stable (condition is unknown)")
                    exit = True 
            
            elif Interpreter.truth_value(abs_test_result):
                prev_state = state.clone()
                self.do_sequence(state, body)
                if state == prev_state:
                    debug("Exiting loop after " + str(i) + " iterations because abstract state is stable (condition is true)")
                    state.set_to_bottom()
                    exit = True
            else:
                debug("Exiting loop after " + str(i) + " iterations because condition is false")
                exit = True

            state.join(self.loopcont_state)
            self.loopcont_state = saved_loopcont

        state.join(self.loopexit_state)
        self.loopexit_state = saved_loopexit

    def do_if(self, state, test, consequent, alternate):
        abs_test_result = self.calc_expr(state, test)

        if abs_test_result is JSTop:
            state_then = state
            state_else = state.clone()
            self.do_sequence(state_then, consequent.body)
            if alternate is not None:
                self.do_sequence(state_else, alternate.body)
            state_then.join(state_else)
            return

        if Interpreter.truth_value(abs_test_result):
            self.do_sequence(state, consequent.body)
        else:
            if alternate is not None:
                self.do_sequence(state, alternate.body)

    def do_fundecl(self, state, name, params, body):
        scope = state.loc
        if state.glob is state.loc:
            scope[name] = JSClosure(params, body.body, {})
        else:
            closure_env = {}
            State.dict_assign(closure_env, state.loc)
            scope[name] = JSClosure(params, body.body, closure_env)


    def do_break(self, state):
        self.loopexit_state.join(state)
        state.set_to_bottom()
    
    def do_continue(self, state):
        self.loopcont_state.join(state)
        state.set_to_bottom()

    def do_return(self, state, argument):
        self.return_state.join(state)
        arg_val = self.calc_expr(state, argument)
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

        else:
            raise ValueError("Statement type not handled: " + statement.type)

    def do_sequence(self, state, sequence):
        for statement in sequence:
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
        self.do_sequence(state, self.ast.body)
        print("Done. Final state: ", str(state))
