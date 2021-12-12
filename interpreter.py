from abstract import State, JSClosure, JSObject, JSUndefNaN, JSTop, JSRef, JSSimFct, JSPrimitive, JSValue

from debug import debug

import plugin_manager
import output
import config
import sys

to_inspect = []

class Interpreter(object):
    def __init__(self, ast):
        self.ast = ast
        self.funcs = []

    @staticmethod
    def truth_value(v):
        return plugin_manager.to_bool(v)
        
    def scope_lookup(self, state, name):
        trace = False #(name == '_0x2abc3f')
        if name in state.objs[state.lref].properties:
            if trace:
                print("local scope")
            return state.objs[state.lref].properties

        current_scope = state.objs[state.lref].properties
        found = False
        while '__closure' in current_scope and not found:
            current_scope = state.objs[current_scope['__closure'].ref_id].properties
            found = name in current_scope
        if found:
            if trace:
                print("closure scope")
            return current_scope
        if trace:
            print("not found")
        return state.objs[state.gref].properties

    def evaluate_function(self, state, callee, arguments):
        #callee can be either JSTop, JSClosure or JSSimFct
           
        if isinstance(callee, JSSimFct):
            args = []
            for argument in arguments:
                arg_val = self.calc_expr_and_store(state, argument)
                args.append(arg_val)
            return callee.fct(*args)


        if isinstance(callee, JSClosure):
            callee.body.used = True
        
        saved_return = self.return_value
        saved_rstate = self.return_state
        saved_lref = state.lref

        self.return_value = None
        self.return_state = State.bottom()
        new_loc_obj = JSObject({})
        new_loc = new_loc_obj.properties
        
        i = 0
        for argument in arguments:
            arg = self.calc_expr_and_store(state, argument)
            if isinstance(callee, JSClosure):
                new_loc[callee.params[i].name] = arg 
                if isinstance(arg, JSClosure) and arg.env is not None:
                    state.objs[arg.env].inc()
                if isinstance(arg, JSRef):
                    state.objs[arg.ref_id].inc()
            else:
                if isinstance(arg, JSClosure):
                    self.evaluate_function(state, arg, [])
            i = i + 1

        lref = State.new_id()
        state.objs[lref] = new_loc_obj
        state.objs[lref].inc()
        state.lref = lref
        if isinstance(callee, JSClosure):
            if callee.env is not None:
                state.objs[state.lref].properties["__closure"] = JSRef(callee.env)
                state.objs[callee.env].inc()
            self.do_statement(state, callee.body)
            state.join(self.return_state)
            if state.is_bottom:
                raise ValueError

            my_return = self.return_value
        else:
            my_return = JSTop
        self.return_value = saved_return
        self.return_state = saved_rstate
        state.objs[lref].dec(state.objs, lref)
        state.lref = saved_lref
        if my_return is None:
            return JSUndefNaN
        return my_return


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
                old = scope.pop(expr.left.name, None)
                if isinstance(old, JSRef):
                    state.objs[old.ref_id].dec(state.objs, old.ref_id)
                if isinstance(old, JSClosure) and old.env is not None:
                    if old.env in state.objs:
                        state.objs[old.env].dec(state.objs, old.env)
                if abs_rvalue is not JSTop:
                    scope[expr.left.name] = abs_rvalue
                    if expr.left.name in to_inspect:
                        print(expr.left.name, ":", abs_rvalue)
                        if isinstance(abs_rvalue, JSRef):
                            print("pointed object:", state.objs[abs_rvalue.ref_id])
                    if isinstance(abs_rvalue, JSRef):
                        state.objs[abs_rvalue.ref_id].inc()
                    if isinstance(abs_rvalue, JSClosure) and abs_rvalue.env is not None:
                        state.objs[abs_rvalue.env].inc()

            elif expr.left.type == "MemberExpression":
                abs_object = self.calc_expr_and_store(state, expr.left.object)
                if expr.left.computed is False:
                    if abs_object is JSTop:
                        return JSTop
                    ref_id = abs_object.ref_id
                    if ref_id in state.objs:
                        old = state.objs[ref_id].properties.pop(expr.left.property.name, None)
                        if isinstance(old, JSRef):
                            state.objs[old.ref_id].dec(state.objs, old.ref_id)
                        if isinstance(old, JSClosure) and old.env is not None:
                            state.objs[old.env].dec(state.objs, old.env)
                        if abs_rvalue is not JSTop:
                            state.objs[ref_id].properties[expr.left.property.name] = abs_rvalue
                            if isinstance(abs_rvalue, JSRef):
                                state.objs[abs_rvalue.ref_id].inc()
                            if isinstance(abs_rvalue, JSClosure) and abs_rvalue.env is not None:
                                state.objs[abs_rvalue.env].inc()
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
                        raise ValueError("Invalid property type:" + str(type(abs_property)), + ", " + str(abs_property))
            else:
                raise ValueError("Invalid assignment left type")
            return abs_rvalue
        
        elif expr.type == "ObjectExpression":
            properties = {}
            for prop in expr.properties:
                if prop.type != "Property":
                    continue
                prop_val = self.calc_expr_and_store(state, prop.value)
                if prop_val is JSTop:
                    continue
                if not prop.computed:
                    properties[prop.key.value] = prop_val
                    if isinstance(prop_val, JSRef):
                        state.objs[prop_val.ref_id].inc()
                    if isinstance(prop_val, JSClosure) and prop_val.env is not None:
                        state.objs[prop_val.env].inc()

                else:
                    prop_key = self.calc_expr_and_store(state, prop.key)
                    if isinstance(prop_key, JSPrimitive):
                        properties[prop_key.val] = prop_val
                        if isinstance(prop_val, JSRef):
                            state.objs[prop_val.ref_id].inc()
                        if isinstance(prop_val, JSClosure) and prop_val.env is not None:
                            state.objs[prop_val.env].inc()
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(properties)
            return JSRef(obj_id)

        elif expr.type == "ArrayExpression":
            elements = {}
            i = 0
            for elem in expr.elements:
                elements[i] = self.calc_expr_and_store(state, elem)
                if isinstance(elements[i], JSRef):
                    state.objs[elements[i].ref_id].inc()
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
                elif abs_property is JSUndefNaN:
                    return JSUndefNaN
                else:
                    raise ValueError("Invalid property type: " + str(type(abs_property)) + "," + str(abs_property))

        elif expr.type == "UnaryExpression":
            argument = self.calc_expr_and_store(state, expr.argument)
            return plugin_manager.handle_unary_operation(expr.operator, argument)

        elif expr.type == "BinaryExpression" or expr.type == "LogicalExpression":
            left = self.calc_expr_and_store(state, expr.left)
            right = self.calc_expr_and_store(state, expr.right)
            return plugin_manager.handle_binary_operation(expr.operator, left, right)

        elif expr.type == "FunctionExpression" or expr.type == "ArrowFunctionExpression":
            if state.lref == state.gref:
                f = JSClosure(expr.params, expr.body, None)
            else:
                f = JSClosure(expr.params, expr.body, state.lref)
            
            if f.body.seen is not True:
                if False and state.lref != state.gref:
                    state.objs[state.lref].inc()
                f.body.seen = True
                f.body.name = "<anonymous>"
                self.funcs.append(f)
            return f

        elif expr.type == "CallExpression":
            callee = self.calc_expr_and_store(state, expr.callee)
            ret =  self.evaluate_function(state, callee, expr.arguments)
            return ret

        else:
            raise ValueError("Expr type not handled:" + expr.type)
        return

    def do_vardecl(self, state, decl, hoisting=False):
        if decl.type == "VariableDeclarator":
            if hoisting or decl.init is None:
                scope = state.objs[state.lref].properties
                scope[decl.id.name] = JSUndefNaN
            else:
                val = self.calc_expr_and_store(state, decl.init)
                if decl.id.name in to_inspect:
                    print(decl.id.name, ":", val)
                    if isinstance(val, JSRef):
                        print("pointed object:", state.objs[val.ref_id])

                if isinstance(val, JSRef):
                    state.objs[val.ref_id].inc()
                scope = state.objs[state.lref].properties
                if val is not JSTop:
                    scope[decl.id.name] = val
                else:
                    if decl.id.name in scope:
                        del scope[decl.id.name]
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
            #print("loop", i)
            saved_loopcont = self.loopcont_state
            self.loopcont_state = State.bottom()
            i = i + 1
            abs_test_result = self.calc_expr_and_store(state, test)
            self.bring_out_your_dead(state)
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
                    exit = True 
                else:
                    if config.max_iter is not None and i > config.max_iter + 10:
                        print(i)
                        print("BUG: loop state failed to stabilize")
                        print("state:", state)
                        print("prev_state:", prev_state)
                        raise ValueError
            
            elif Interpreter.truth_value(abs_test_result):
                prev_state = state.clone()
                self.do_sequence(state, body)
                state.join(self.loopcont_state)
                self.loopcont_state = saved_loopcont
                if state == prev_state:
                    state.set_to_bottom()
                    exit = True
            else:
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
            a = self.return_state
            b = self.return_value
            c = self.loopexit_state
            d = self.loopcont_state
            self.return_state = State.bottom()
            self.return_value = None
            self.loopexit_state = State.bottom()
            self.loopcont_state = State.bottom()
            cl = state.clone()
            self.do_statement(cl, consequent)
            self.return_state = a
            self.return_value = b
            self.loopexit_state = c
            self.loopcont_state = d
            if alternate is not None:
                self.do_statement(state, alternate)

    def do_fundecl(self, state, name, params, body):
        scope = state.objs[state.lref].properties
        if state.lref == state.gref:
            scope[name] = JSClosure(params, body, None)
        else:
            if name in scope:
                if isinstance(scope[name], JSRef):
                    state.objs[scope[name].ref_id].dec()
                if isinstance(scope[name], JSClosure) and scope[name].env is not None:
                    state.objs[scope[name].env].dec()
            scope[name] = JSClosure(params, body, state.lref)
            state.objs[state.lref].inc()

        if scope[name].body.seen is not True:
            if False and state.lref != state.gref:
                state.objs[state.lref].inc()
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
        if argument is None:
            arg_val = JSUndefNaN
        else:
            arg_val = self.calc_expr_and_store(state, argument)
        if self.return_value is None:
            self.return_value = arg_val.clone()
        elif not (type(self.return_value) == type(arg_val) and self.return_value == arg_val):
            self.return_value = JSTop
        
        self.return_state.join(state)
        
        state.set_to_bottom()

    def bring_out_your_dead(self, state):
        #print("cleanup", state)
        if config.delete_unused:
            bye = []
            for o in state.objs:
                if o != state.gref:
                    nclosures = 0
                    for c in state.objs[o].properties:
                        c_obj = state.objs[o].properties[c]
                        if isinstance(c_obj, JSClosure) and c_obj.env == o:
                            nclosures += 1
                    if state.objs[o].refcount == nclosures:
                        bye.append(o)
            for b in bye:
                del state.objs[b]

    def do_statement(self, state, statement, hoisting=False):
        if state.is_bottom:
            debug("Ignoring dead code: ", statement.type)
            return

        debug("Current state: ", state)
        debug("Interpreting statement:", statement.type)

        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.do_vardecl(state, decl, hoisting)

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

        self.bring_out_your_dead(state)

    def do_sequence(self, state, sequence):
        for statement in sequence:
            self.do_statement(state, statement)
    
    def do_sequence_with_hoisting(self, state, sequence):
        #half-assed hoisting
        for statement in sequence:
            if statement.type == "FunctionDeclaration" or statement.type == "VariableDeclaration":
                self.do_statement(state, statement, True)
        
        for statement in sequence:
            if not statement.type == "FunctionDeclaration":
                self.do_statement(state, statement)


    def run(self):
        state = State(glob=True, bottom=False)
        self.return_value = None
        self.closure = {}
        self.return_state = State.bottom()
        self.loopexit_state = State.bottom()
        self.loopcont_state = State.bottom()


        for (ref_id, obj) in plugin_manager.preexisting_objects:
            state.objs[ref_id] = obj
        
        for (name, value) in plugin_manager.global_symbols:
            state.objs[state.gref].properties[name] = value
            if isinstance(value, JSRef):
                state.objs[value.ref_id].inc()
        
        State.set_next_id(plugin_manager.ref_id)

        debug("Dumping Abstract Syntax Tree:")
        debug(self.ast.body)
        debug("Init state: ", str(state))
        print("Starting abstract interpretation...")
        self.do_sequence_with_hoisting(state, self.ast.body)
        print("\nAnalysis finished")
        for f in self.funcs:
            if not f.body.used:
                f.body.dead_code = True



