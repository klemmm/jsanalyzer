from abstract import State, JSObject, JSUndefNaN, JSTop, JSBot, JSRef, JSPrimitive, JSValue

from debug import debug

SITE = 0

import esprima
import plugin_manager
import output
import config
import sys
import bisect

class StackUnwind(Exception):
    def __init__(self, site):
        self.site = site

class Stats:
    computed_values = 0
    beta_reductions = 0
    steps = 0

class Interpreter(object):
    def __init__(self, ast, data):
        self.ast = ast
        self.funcs = []
        self.data = data
        plugin_manager.set_source(data)
        self.lines  = []
        self.stack_trace = []
        self.last = None
        self.memo = {}
        i = 0
        while i < len(self.data):
            if self.data[i] == '\n':
                self.lines.append(i)
            i += 1

    def offset2line(self, offset):
        return bisect.bisect_left(self.lines, offset) + 1
       
    @staticmethod
    def beta_reduction(expression, formal_args, effective_args):
        if expression.type == "BinaryExpression":
            l = Interpreter.beta_reduction(expression.left, formal_args, effective_args)
            r = Interpreter.beta_reduction(expression.right, formal_args, effective_args)
            return esprima.nodes.BinaryExpression(expression.operator, l, r)
        elif expression.type == "Identifier":
            i = 0
            found = False
            for a in formal_args:
                if a.name ==  expression.name:
                    found = True
                    break
                i += 1
            if found:
                return effective_args[i]
            else:
                return expression

        elif expression.type == "CallExpression":
            args = []
            for a in expression.arguments:

                reduced_arg = Interpreter.beta_reduction(a, formal_args, effective_args)
                if reduced_arg is None:
                    raise ValueeError
                args.append(reduced_arg)

            return esprima.nodes.CallExpression(Interpreter.beta_reduction(expression.callee, formal_args, effective_args), args)
        elif expression.type == "Literal":
            return expression
        else:
            print("beta_reduction: unhandled expression type " + str(expression.type))
            return expression

    #Evaluate a function call
    #state (mutable): takes abstract state used to perform the evaluation
    #callee (callable JSObject, or JSTop): represent callee object
    #expr (AST node, or None): represent arguments, if any
    def eval_func_call(self, state, callee, expr, this=None, consumed_refs=None):
        if expr is None:
            arguments = []
        else:
            arguments = expr.arguments
        
        #Argument evaluation is the same in each case.
        #Evaluate argument, then handle the actual function call.
        args_val = []
        for argument in arguments:
            #We evaluate arguments even if callee is not callable, to handle argument-evaluation side effects
            v = self.eval_expr(state, argument)
            state.consume_expr(v, consumed_refs)
            if callee.is_callable():
                args_val.append(v)
            elif isinstance(v, JSRef) and state.objs[v.target()].is_function():
                #If the function is unknown, and closures are passed as arguments, we assume these closures will be called by the unknown function.
                self.eval_func_call(state, state.objs[v.target()], None)

        #Handle the case where callee is a simfct
        if callee.is_simfct(): 
            self.pure = False #TODO implement a way for plugins to tell the interpreter that a python function is pure.

            #TODO for now, only simfct can be bound
            if this:
                if type(this) is int: #bound to object
                    return callee.simfct(state, state.objs[this], *args_val) #call bound simfct
                else: #bound to primitive type (int or string)
                    assert isinstance(this, JSPrimitive)
                    return callee.simfct(state, this, *args_val) #call bound simfct
            else:
                return callee.simfct(state, *args_val) #call unbound simfct

        #Handle the case where callee is a non-simfct function
        if callee.is_function():
            callee.body.used = True
           
            #enable inlining if the function consists of only one return statement
            if callee.body.type is "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body

            #same, for a block statement containing a single return statement
            if callee.body.type is "BlockStatement" and len(callee.body.body) > 0 and callee.body.body[0].type is "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body.body[0]

            #Attempt to compute an inlined version of the expression
            if config.inlining and callee.body.redex and expr is not None:
                Stats.beta_reductions += 1
                expr.reduced = Interpreter.beta_reduction(return_statement.argument, callee.params, arguments)
        
            #Enter callee context 
            saved_return = self.return_value
            saved_rstate = self.return_state
            saved_pure = self.pure

            self.return_value = None
            self.return_state = State.bottom()
            state.stack_frames.append(state.lref)
            self.stack_trace.append(self.last)
            state.lref = State.new_id()
            state.objs[state.lref] = JSObject({})
            self.pure = True

            #Store the argument values in callee local scope
            i = 0
            for v in args_val:
                state.objs[state.lref].properties[callee.params[i].name] = v
                i = i + 1
       
            #bind closure environment, if any
            if callee.is_closure():
                #TODO store this in state.closure_ref or something like this, instead
                state.objs[state.lref].properties["__closure"] = JSRef(callee.closure_env())
           
            #evaluate function, join any return states
            self.do_statement(state, callee.body)
            callee.body.pure = self.pure
            state.join(self.return_state)
           
            #Save function return value
            return_value = self.return_value #TODO reflechir au pending
       
            #Leave callee context
            self.return_value = saved_return
            self.return_state = saved_rstate
            if not state.is_bottom:
                state.lref = state.stack_frames.pop()
            self.last = self.stack_trace.pop()
            self.pure = saved_pure and self.pure

            if return_value is None:
                return JSUndefNaN

            return return_value
        self.pure = False
        return JSTop
       
    #Evaluate expression and annotate AST in case of statically known value. Return abstract value.
    def eval_expr(self, state, expr):
        if state.is_bottom:
            return JSBot
        result = self.eval_expr_aux(state, expr)
        if result is not JSTop:
            Stats.computed_values += 1
            expr.static_value = State.value_join(expr.static_value, result)
        if isinstance(result, JSRef):
            state.pending.add(result.target())
            #print("PEND: (target) add: ", result.target())
            if result.is_bound() and type(result.this()) is int:
                state.pending.add(result.this())
                #print("PEND: (this) add: ", result.this())
        return result
            
    def do_assignment(self, state, lvalue_expr, abs_rvalue, consumed_refs=None):
        #try to find the dict holding the identifier or property that is being written to, and the property/identifier name
        if lvalue_expr.type == "Identifier":
            #Identifier type: the simple case.
            target = state.scope_lookup(lvalue_expr.name)
            prop = lvalue_expr.name
            if target is not state.objs[state.lref].properties:
                self.pure = False

        elif lvalue_expr.type == "MemberExpression": #member as lvalue
            self.pure = False
            #Member expression: identify target object (dict), and property name (string)
            r = self.use_member(state, lvalue_expr, consumed_refs)
            if r is None:
                return
            target = r[0].properties
            prop = r[1]
        else:
            raise ValueError("Invalid assignment left type")

        #Delete old value (if any)
        old = target.pop(prop, None)

        if abs_rvalue is not JSTop:
            target[prop] = abs_rvalue

    #Helper function to decompose member expression into object (dict) and property (string). Returns None if not found.
    def use_member(self, state, expr, consumed_refs=None):
        #Member expression type: first, try to find referenced object
        abs_target = self.eval_expr(state, expr.object)
        state.consume_expr(abs_target, consumed_refs)

        #If we cannot locate the referenced object, we will return JSTop later (but still evaluate computed property, if needed)
        if isinstance(abs_target, JSRef):
            target = state.objs[abs_target.target()]
        elif isinstance(abs_target, JSPrimitive):
            target = abs_target

        #Now, try to find the property name, it can be directly given, or computed.
        if expr.computed:
            #Property name is computed (i.e. tab[x + 1])
            abs_property = self.eval_expr(state, expr.property)
            state.consume_expr(abs_property, consumed_refs)
            if abs_property is JSTop:
                return None
            if abs_property is JSUndefNaN:
                return None
            elif isinstance(abs_property, JSPrimitive):
                prop = abs_property.val
            else:
                raise ValueError("Invalid property type: " + str(type(abs_property)))
        else:
            #Property name is directly given (i.e. foo.bar)
            prop = expr.property.name
        if isinstance(abs_target, JSRef):
            return target, prop, abs_target.target()
        elif isinstance(abs_target, JSPrimitive):
            return target, prop, None
        else:
            return None

    #Takes state, expression, and returns a JSValue
    def eval_expr_aux(self, state, expr):
        if expr.type == "Literal":
            if expr.value is None:
                return JSUndefNaN
            return JSPrimitive(expr.value)

        elif expr.type == "Identifier":
            if expr.name == "undefined":
                return JSUndefNaN
            scope = state.scope_lookup(expr.name)
            if expr.name in scope:
                return scope[expr.name]
            else:
                return JSTop #untracked identifier

        elif expr.type == "UpdateExpression":
            consumed_refs = set()
            argument = self.eval_expr(state, expr.argument)
            state.consume_expr(argument, consumed_refs)
            result = plugin_manager.handle_update_operation(expr.operator, state, argument)
            state.consume_expr(result, consumed_refs)

            self.do_assignment(state, expr.argument, result, consumed_refs)
            state.pending.difference_update(consumed_refs)
            
            if expr.prefix:
                return result
            else:
                if result is JSTop:
                    return JSTop
                else:
                    return argument

        elif expr.type == "NewExpression":
            consumed_refs = set()
            for argument in expr.arguments:
                arg_val = self.eval_expr(state, argument)
                state.consume_expr(arg_val, consumed_refs)
            state.pending.difference_update(consumed_refs)
            print("NewExpression return JSTop")
            return JSTop
      
        elif expr.type == "ConditionalExpression":
            consumed_refs = set()
            abs_test_result = self.eval_expr(state, expr.test)
            state.consume_expr(abs_test_result, consumed_refs)

            state_then = state
            state_else = state.clone()
            expr_then = self.eval_expr(state_then, expr.consequent)
            state.consume_expr(expr_then, consumed_refs)
            expr_else = self.eval_expr(state_else, expr.alternate)
            state.consume_expr(expr_else, consumed_refs)

            if abs_test_result is JSTop:
                state_then.join(state_else)
                if State.value_equal(expr_then, expr_else):
                    result = expr_then
                else:
                    result = JSTop
            elif plugin_manager.to_bool(abs_test_result):
                result = expr_then
            else:
                result = expr_else

            state.pending.difference_update(consumed_refs)
            return result

        elif expr.type == "SequenceExpression":
            consumed_refs = set()
            for e in expr.expressions:
                r = self.eval_expr(state, e)
                state.consume_expr(r, consumed_refs)
            state.pending.difference_update(consumed_refs)
            return r

        elif expr.type == "ThisExpression":
            print("ThisExpression")
            return JSTop

        elif expr.type == "AssignmentExpression":
            consumed_refs = set()
            if expr.operator[0] == "=":
                abs_rvalue = self.eval_expr(state, expr.right)
                if state.is_bottom:
                    return JSBot
                state.consume_expr(abs_rvalue, consumed_refs)
                self.do_assignment(state, expr.left, abs_rvalue, consumed_refs)
                state.pending.difference_update(consumed_refs)
                return abs_rvalue
            else:
                left = self.eval_expr(state, expr.left)
                state.consume_expr(left, consumed_refs)
                right = self.eval_expr(state, expr.right)
                state.consume_expr(right, consumed_refs)
                result = plugin_manager.handle_binary_operation(expr.operator[0], state, left, right)
                self.do_assignment(state, expr.left, result, consumed_refs)
                state.pending.difference_update(consumed_refs)
                return result

        elif expr.type == "ObjectExpression":
            properties = {}
            consumed_refs = set()
            for prop in expr.properties:
                if prop.type != "Property":
                    continue
                prop_val = self.eval_expr(state, prop.value)
                state.consume_expr(prop_val, consumed_refs)
                if prop_val is JSTop:
                    continue
                if not prop.computed:
                    properties[prop.key.value] = prop_val

                else:
                    prop_key = self.eval_expr(state, prop.key)
                    state.consume_expr(prop_key, consumed_refs)
                    if isinstance(prop_key, JSPrimitive):
                        properties[prop_key.val] = prop_val
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(properties)
            state.pending.difference_update(consumed_refs)
            return JSRef(obj_id)

        elif expr.type == "ArrayExpression":
            elements = {}
            consumed_refs = set()
            i = 0
            for elem in expr.elements:
                elements[i] = self.eval_expr(state, elem)
                state.consume_expr(elements[i], consumed_refs)
                i = i + 1
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(elements)
            state.pending.difference_update(consumed_refs)
            return JSRef(obj_id)

        elif expr.type == "MemberExpression":
            consumed_refs = set()
            r = self.use_member(state, expr, consumed_refs)
            if r is None:
                state.pending.difference_update(consumed_refs)
                return JSTop
            target, prop, target_id = r
            if isinstance(target, JSObject):
                if prop == "length":
                    state.pending.difference_update(consumed_refs)
                    return JSPrimitive(len(target.properties))
                member = target.member(prop)
                if isinstance(member, JSRef) and not member.is_bound():
                    bound_member = member.clone()
                    bound_member.bind(target_id)
                    state.pending.difference_update(consumed_refs)
                    return bound_member
                else:
                    state.pending.difference_update(consumed_refs)
                    return member
            elif isinstance(target, JSPrimitive) and type(target.val) is str:
                if type(prop) is int:
                    if prop >= 0 and prop < len(target.val):
                        ret = JSPrimitive(target.val[prop])
                    else:
                        ret = JSUndefNaN
                    state.pending.difference_update(consumed_refs)
                    return ret
                if prop == "length":
                    state.pending.difference_update(consumed_refs)
                    return JSPrimitive(len(target.val))
                fct = JSTop
                for h in JSObject.hooks:
                    fct = h(prop)
                    if fct is not JSTop:
                        fct = fct.clone()
                        fct.bind(target)
                        break
                if fct is JSTop:
                    print("Unknown string member: ", prop, type(prop))
                    state.pending.difference_update(consumed_refs)
                    return JSTop
                state.pending.difference_update(consumed_refs)
                return fct
            elif isinstance(target, JSPrimitive) and type(target.val) is int:
                fct = JSTop
                for h in JSObject.hooks:
                    fct = h(prop)
                    if fct is not JSTop:
                        fct = fct.clone()
                        fct.bind(target)
                        break
                if fct is JSTop:
                    print("Unknown int member: ", prop)
                    state.pending.difference_update(consumed_refs)
                    return JSTop
                state.pending.difference_update(consumed_refs)
                return fct

            else:
                state.pending.difference_update(consumed_refs)
                return JSTop

        elif expr.type == "UnaryExpression": #Unary expression computation delegated to plugins
            consumed_refs = set()
            argument = self.eval_expr(state, expr.argument)
            state.consume_expr(argument, consumed_refs)
            result = plugin_manager.handle_unary_operation(expr.operator, state, argument)
            state.consume_expr(result, consumed_refs)
            state.pending.difference_update(consumed_refs)
            return result
            

        elif expr.type == "BinaryExpression" or expr.type == "LogicalExpression": #Also delegated to plugins
            consumed_refs = set()
            left = self.eval_expr(state, expr.left)
            state.consume_expr(left, consumed_refs)
            right = self.eval_expr(state, expr.right)
            state.consume_expr(right, consumed_refs)
            result = plugin_manager.handle_binary_operation(expr.operator, state, left, right)
            state.pending.difference_update(consumed_refs)
            return result

        elif expr.type == "FunctionExpression" or expr.type == "ArrowFunctionExpression":
            if state.lref == state.gref: #if global scope, no closure
                f = JSObject.function(expr.body, expr.params)
                f.range = expr.range
            else: #otherwise, closure referencing local scope
                f = JSObject.closure(expr.body, expr.params, state.lref)
                f.range = expr.range

            if f.body.seen is not True:
                f.body.seen = True
                f.body.name = "<anonymous>"
                self.funcs.append(f)
            obj_id = State.new_id()
            state.objs[obj_id] = f
            return JSRef(obj_id)

        elif expr.type == "CallExpression":
            if expr.skip:
                print("skipped for site=", expr.site)
                return JSBot
            consumed_refs = set()
            callee_ref = self.eval_expr(state, expr.callee)
            state.consume_expr(callee_ref, consumed_refs)

            this = None
            if callee_ref.is_bound():
                this = callee_ref.this()

            callee = JSTop
            if isinstance(callee_ref, JSRef):
                callee = state.objs[callee_ref.target()]

            if expr.active is None:
                expr.active = 0
                #print("\nHandling function: ", callee.body.name, "site=", expr.site)
                #print("active count: ", expr.active)

            if expr.site is None:
                expr.site = State.new_id()
            site = expr.site

            if expr.active == config.max_recursion:
                assert expr.recursion_state is None
                if callee is not JSTop:
                    print("[warning] Recursion inlining stopped at depth=", expr.active, "function=", callee.body.name, site)
                expr.recursion_state = state.clone()

            if expr.active == config.max_recursion + 1:
                if callee is not JSTop:
                    print("current state stack frames: ",  state.stack_frames, state.lref, "function=", callee.body.name, site)

                if expr.recursion_state.is_bottom:
                    if callee is not JSTop:
                        print("recursion state stack frames: BOT",  "function=", callee.body.name, site)
                else:
                    if callee is not JSTop:
                        print("recursion state stack frames: ",  expr.recursion_state.stack_frames, expr.recursion_state.lref, "function=", callee.body.name, site)
                expr.recursion_state.join(state)
                if callee is not JSTop:
                    print("   joined state stack frames: ",  expr.recursion_state.stack_frames, expr.recursion_state.lref, "function=", callee.body.name, site)
                raise StackUnwind(site)

            key = None
            try:
                if callee.body.name in config.memoize:
                    key = ""
                    for a in expr.arguments:
                        key = key + a.value + "\x00"
            except:
                pass
            if key in self.memo:
                state.pending.difference_update(consumed_refs)
                return JSPrimitive(self.memo[key])

            #if callee.is_function() and callee.body.name in config.memoize:
            #    raise ValueError
            expr.active += 1
            stable = False
            while not stable:
                try:
                    #print("start eval, site", expr.site, "skip=", expr.skip)
                    if expr.recursion_state is not None:
                        old_recursion_state = expr.recursion_state.clone()
                    if self.return_state is not None:
                        saved_return_state = self.return_state.clone()
                    else:
                        saved_return_state = None
                    if self.return_value is not None:
                        saved_return_value = self.return_value.clone()
                    else:
                        saved_return_value = None
                    ret =  self.eval_func_call(state, callee, expr, this, consumed_refs)
                    #print("stop eval, site", expr.site, "skip=", expr.skip)
                    stable = True
                except StackUnwind as e:
                    #print("at site: ", expr.site)
                    if e.site != expr.site:
                        #print("not my function")
                        expr.active -= 1
                        expr.recursion_state = None
                        raise e
                    #print("Unwinded: ", e.site)
                    state.assign(old_recursion_state)
                    self.return_state = saved_return_state
                    self.return_value = saved_return_value
                    if state == expr.recursion_state:
                        expr.skip = True
                        #print("Recursion state stabilized, function=", callee.body.name, site)
#                    else:
#                       print("not stable yet")
                        state.assign(expr.recursion_state)
            #if expr.recursion_state is not None:
            #    print("Finished site=", expr.site, expr.range)
            expr.skip = None
            expr.active -= 1
            expr.recursion_state = None
            if key is not None and isinstance(ret, JSPrimitive):
                self.memo[key] = ret.val
            state.consume_expr(ret, consumed_refs)
            state.pending.difference_update(consumed_refs)
            return ret

        else:
            raise ValueError("Expr type not handled:" + expr.type)
        return

    def do_vardecl(self, state, decl, hoisting=False):
        #This is called twice.
        #One time during hoisting (to declare variables)
        #And one time to do variable initialization
        consumed_refs = set()
        if decl.type == "VariableDeclarator":
            if hoisting or decl.init is None: #Only declaration (set value to undefined)
                scope = state.objs[state.lref].properties
                scope[decl.id.name] = JSUndefNaN
            else:
                val = self.eval_expr(state, decl.init)
                state.consume_expr(val, consumed_refs)
                scope = state.objs[state.lref].properties
                #remove old variable
                old = scope.pop(decl.id.name, None)

                #compute new value
                if val is not JSTop:
                    scope[decl.id.name] = val
        else:
            raise ValueError("Vardecl type not handled:" + decl.type)
        state.pending.difference_update(consumed_refs)

    def do_expr_or_statement(self, state, exprstat):
        if exprstat.type in output.EXPRESSIONS:
            discarded = self.eval_expr(state, exprstat)
            state.consume_expr(discarded)
        else:
            self.do_statement(state, exprstat)

    def do_exprstat(self, state, expr):
        discarded = self.eval_expr(state, expr)
        state.consume_expr(discarded)
    
    def do_while(self, state, test, body):
        self.do_for(state, None, test, None, body)

    def do_for(self, state, init, test, update, body):
        state_is_bottom = False
        consumed_refs = set()
        prev_state = None
        i = 0
        warned = False
        saved_loopexit = self.loopexit_state
        self.loopexit_state = State.bottom()
        exit = False
        if init is not None:
            self.do_expr_or_statement(state, init)
        while not exit:
            #print("loop", i)
            saved_loopcont = self.loopcont_state
            self.loopcont_state = State.bottom()
            i = i + 1
            abs_test_result = self.eval_expr(state, test)
            if state.is_bottom:
                break
            state.consume_expr(abs_test_result, consumed_refs)
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
                if update:
                    self.do_expr_or_statement(state, update)
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
            
            elif plugin_manager.to_bool(abs_test_result):
                prev_state = state.clone()
                self.do_sequence(state, body)
                if update:
                    self.do_exprstat(state, update)
                state.join(self.loopcont_state)
                self.loopcont_state = saved_loopcont
                if state == prev_state:
                    state.set_to_bottom()
                    exit = True
            else:
                exit = True


        state.join(self.loopexit_state)
        self.loopexit_state = saved_loopexit
        state.pending.difference_update(consumed_refs)

    def do_switch(self, state, discriminant, cases):
        consumed_refs = set()
        abs_discr = self.eval_expr(state, discriminant)
        state.consume_expr(abs_discr, consumed_refs)
        has_true = False
        states_after = []
        for case in cases:
            abs_test = self.eval_expr(state, case.test)
            state.consume_expr(abs_test, consumed_refs)
            if (abs_test is not JSTop) and (abs_discr is not JSTop) and ((type(abs_test) != type(abs_discr)) or (abs_test != abs_discr)):
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
        state.pending.difference_update(consumed_refs)

    def do_if(self, state, test, consequent, alternate):
        consumed_refs = set()
        abs_test_result = self.eval_expr(state, test)
        state.consume_expr(abs_test_result, consumed_refs)

        if abs_test_result is JSTop:
            state_then = state
            state_else = state.clone()
            self.do_statement(state_then, consequent)
            if alternate is not None:
                self.do_statement(state_else, alternate)
            state_then.join(state_else)
            state.pending.difference_update(consumed_refs)
            return

        if plugin_manager.to_bool(abs_test_result):
            self.do_statement(state, consequent)
        else:
            #TODO temporary workaround for probably incorrect boolean value evaluation
            if config.process_not_taken:
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
            #TODO end of temporary workaround
            if alternate is not None:
                self.do_statement(state, alternate)
        state.pending.difference_update(consumed_refs)

    def do_fundecl(self, state, statement):
        name = statement.id.name
        params = statement.params
        body = statement.body
        scope = state.objs[state.lref].properties
        if state.lref == state.gref:
            f = JSObject.function(body, params)
            f.range = statement.range
        else:
            f = JSObject.closure(body, params, state.lref)
            f.range = statement.range

        if f.body.seen is not True:
            f.body.seen = True
            f.body.name = name
            self.funcs.append(f)
        obj_id = State.new_id()
        state.objs[obj_id] = f
        scope[name] = JSRef(obj_id)

    def do_break(self, state):
        #do_break works by merging loopexit_state with current state
        #loopexit_state will be merged with the state after the loop
        self.loopexit_state.join(state)
        state.set_to_bottom()
    
    def do_continue(self, state):
        #do_continue works by merging loopcont_state with current state
        #loopexit_state will be merged with the state after the current iteration
        self.loopcont_state.join(state)
        state.set_to_bottom()

    def do_return(self, state, argument):
        #do_return works by merging return_state with current state
        #return_state will be used as the state after the function call
        #also we merge return_value as the upper bound of all possible return values
        if argument is None:
            arg_val = JSUndefNaN
        else:
            arg_val = self.eval_expr(state, argument) 
            if state.is_bottom:
                return
        if self.return_value is None or self.return_value is JSBot:
            self.return_value = arg_val.clone()
        elif not ((type(self.return_value) == type(arg_val) and self.return_value == arg_val) or arg_val is JSBot):
            self.return_value = JSTop
        
        self.return_state.join(state)
        
        state.set_to_bottom()

    def bring_out_your_dead(self, state):

        #Delete unreachable objects that are in cycles
        if not config.delete_unused:
            return

        debug("State before GC: ", state)

        if state.is_bottom:
            debug("GC: Not doing anything\n")
            return

        reachable = set()
        def visit(ref_id):
            if ref_id in reachable:
                return
            reachable.add(ref_id)
            for k,v in state.objs[ref_id].properties.items():
                if isinstance(v, JSRef):
                    visit(v.target())
                    if v.is_bound():
                        visit(v.this())
            if state.objs[ref_id].is_closure():
                visit(state.objs[ref_id].closure_env())

        visit(state.lref) #local context gc root
        visit(state.gref) #global context gc root

        #callstack local contexts gc root
        for ref in state.stack_frames:
            if ref is None:
                raise ValueError
            visit(ref)

        #pending expressions gc root
        for ref in state.pending:
            visit(ref)

        #preexisting objects gc root
        for ref, obj in plugin_manager.preexisting_objects:
            visit(ref)


        debug("GC: Reachable nodes: ", reachable)
        bye = set()
        for o,v in state.objs.items():
            if o not in reachable:
                bye.add(o)

        for b in bye:
            del state.objs[b]

    def do_statement(self, state, statement, hoisting=False):
        if state.is_bottom:
            debug("Ignoring dead code: ", statement.type)
            return

        Stats.steps += 1

        debug("Current state: ", state)

        line1 = self.offset2line(statement.range[0])
        line2 = self.offset2line(statement.range[1])

        self.last = statement.type + ", range: " + str(statement.range) + ", lines: "+ str(line1) + "-" + str(line2) + "\nsource: " + self.data[statement.range[0]:statement.range[1]]

        debug("interpreting: ", self.last)


        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.do_vardecl(state, decl, hoisting)

        elif statement.type == "ExpressionStatement":
            self.do_exprstat(state, statement.expression)

        elif statement.type == "ForOfStatement":
            print("ForOfStatement")
            pass #TODO
        
        elif statement.type == "ForStatement":
            self.do_for(state, statement.init, statement.test, statement.update, statement.body.body)

        elif statement.type == "IfStatement":
            self.do_if(state, statement.test, statement.consequent, statement.alternate)

        elif statement.type == "FunctionDeclaration":
            self.do_fundecl(state, statement)
       
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
        self.pure = True

        for (ref_id, obj) in plugin_manager.preexisting_objects:
            state.objs[ref_id] = obj
        
        for (name, value) in plugin_manager.global_symbols:
            state.objs[state.gref].properties[name] = value
        
        State.set_next_id(plugin_manager.ref_id)

        debug("Dumping Abstract Syntax Tree:")
        debug(self.ast.body)
        debug("Init state: ", str(state))
        print("Starting abstract interpretation...")
        try:
            self.do_sequence_with_hoisting(state, self.ast.body)
        except:
            if self.last is not None:
                print("\n=== ERROR DURING ABSTRACT INTERPRETATION ===")
                print("\nWith abstract state: ")
                print(state)
                print("\nAt analyzed program statement: ")
                print(self.last + "\n")
                for t in reversed(self.stack_trace):
                    print("Called from: \n" + t + "\n")
                print("\nException: ")
            raise
        print("\nAbstract state stabilized after", Stats.steps, "steps")
        debug("Abstract state at end: ", state)
        dead_funcs = 0
        funcs = 0
        for f in self.funcs:
            funcs += 1
            if not f.body.used:
                f.body.dead_code = True
                dead_funcs += 1
        print("Functions analyzed: ", funcs)
        print("Dead-code functions: ", dead_funcs)
        print("Static values computed: ", Stats.computed_values)
        print("Beta-reductions: ", Stats.beta_reductions)
