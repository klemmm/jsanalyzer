import esprima
from abstract import State, JSObject, JSUndefNaN, JSTop, JSBot, JSRef, JSPrimitive, JSValue, MissingMode, JSOr, GCConfig
from debug import debug
import re
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

def eval_fct(state, expr, target):
    if target is JSTop:
        return JSTop #TODO should clear entire state here
    if isinstance(target, JSPrimitive) and type(target.val) is str:
        print("Launch sub-interpreter to manage eval()")
        ast = esprima.parse(target.val, options={ 'range': True})
        i = Interpreter(ast, target.val)
        i.run(state)
        expr.eval = ast.body
        print("Sub-interpreter finished")
        return state.value
    else:
        return target

class Interpreter(object):
    def __init__(self, ast, data):
        self.ast = ast
        self.funcs = []
        self.data = data
        plugin_manager.set_source(data)
        self.lines  = []
        self.stack_trace = []
        self.last = None
        self.deferred = []
        self.need_clean = False
        self.unroll_trace = None
        i = 0
        while i < len(self.data):
            if self.data[i] == '\n':
                self.lines.append(i)
            i += 1

    def offset2line(self, offset):
        return bisect.bisect_left(self.lines, offset) + 1
       
    @staticmethod
    def beta_reduction(expression, formal_args, effective_args):
        if expression.reduced is not None:
            return Interpreter.beta_reduction(expression.reduced, formal_args, effective_args)

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

            ret = esprima.nodes.CallExpression(Interpreter.beta_reduction(expression.callee, formal_args, effective_args), args)
            ret.created_by_beta_reduction = True
            return ret
        elif expression.type == "Literal":
            return expression
        else:
            #print("beta_reduction: unhandled expression type " + str(expression.type))
            return expression

    def eval_func_helper(self, state, expr, consumed_refs, this=None):
        if expr.skip:
            #print("skipped for site=", expr.site)
            return JSBot
        callee_ref = self.eval_expr(state, expr.callee)
        state.consume_expr(callee_ref, consumed_refs)

        if isinstance(callee_ref, JSOr) and config.use_filtering_err:
            #print("Or in call:", callee_ref)
            c = callee_ref.choices.difference({JSUndefNaN})
            if len(c) == 1:
                target, prop, target_id = self.use_lvalue(state, expr.callee, consumed_refs)
                target.properties[prop] = list(c)[0]
                callee_ref = list(c)[0]


        if callee_ref.is_bound() and this is None:
            #print("callee ref is bound:", callee_ref, state.objs[callee_ref.this()], expr)
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
#            if callee is not JSTop:
#                print("[warning] Recursion inlining stopped at depth=", expr.active, "function=", callee.body.name, site)
            expr.recursion_state = state.clone()

        if expr.active == config.max_recursion + 1:
#            if callee is not JSTop:
#                print("current state stack frames: ",  state.stack_frames, state.lref, "function=", callee.body.name, site)
#
#            if expr.recursion_state.is_bottom:
#                if callee is not JSTop:
#                    print("recursion state stack frames: BOT",  "function=", callee.body.name, site)
#            else:
#                if callee is not JSTop:
#                    print("recursion state stack frames: ",  expr.recursion_state.stack_frames, expr.recursion_state.lref, "function=", callee.body.name, site)
            expr.recursion_state.join(state)
#            if callee is not JSTop:
#                print("   joined state stack frames: ",  expr.recursion_state.stack_frames, expr.recursion_state.lref, "function=", callee.body.name, site)
            raise StackUnwind(site)

        expr.active += 1
        stable = False
        while not stable:
            try:
                #print("start eval, site", expr.site, "skip=", expr.skip)
                if expr.recursion_state is not None:
                    old_recursion_state = expr.recursion_state.clone()
                if self.return_state is not None:
                    saved_return_state = self.return_state
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
                state.unify(expr.recursion_state)
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
        state.consume_expr(ret, consumed_refs)
        return ret


    #Evaluate a function call
    #state (mutable): takes abstract state used to perform the evaluation
    #callee (callable JSObject, or JSTop): represent callee object
    #expr (AST node, or None): represent call expression, if any
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
                #self.eval_func_call(state, state.objs[v.target()], None)
                if not argument.processed:
                    argument.processed = True
                    deferred_id = state.objs[state.gref].properties["___deferred"].target()
                    fn_id = State.new_id()
                    state.objs[deferred_id].properties[fn_id] = v

        #Handle the case where callee is a simfct
        if callee.is_simfct(): 
            self.pure = False #TODO implement a way for plugins to tell the interpreter that a python function is pure.

            #TODO for now, only simfct can be bound
            if this:
                if type(this) is int: #bound to object
                    return callee.simfct(state, expr, state.objs[this], *args_val) #call bound simfct
                else: #bound to primitive type (int or string)
                    assert isinstance(this, JSPrimitive)
                    return callee.simfct(state, expr, this, *args_val) #call bound simfct
            else:
                return callee.simfct(state, expr, *args_val) #call unbound simfct

        #Handle the case where callee is a non-simfct function
        elif callee.is_function():
            callee.body.used = True

            #enable inlining if the function consists of only one return statement
            if callee.body.type == "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body

            #same, for a block statement containing a single return statement
            if callee.body.type == "BlockStatement" and len(callee.body.body) > 0 and callee.body.body[0].type == "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body.body[0]

        
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
            if this and type(this) is int:
                state.objs[state.lref].properties["__this"] = JSRef(this)
            self.pure = True

            #Store the argument values in callee local scope
            i = 0
            arguments_id = State.new_id()
            state.objs[state.lref].properties["arguments"] = JSRef(arguments_id)
            state.objs[arguments_id] = JSObject({})
            for v in args_val:
                state.objs[state.lref].properties[callee.params[i].name] = v
                state.objs[arguments_id].properties[i] = v
                i = i + 1
       
            #bind closure environment, if any
            if callee.is_closure():
                #TODO store this in state.closure_ref or something like this, instead
                state.objs[state.lref].properties["__closure"] = JSRef(callee.closure_env())
           
            #evaluate function, join any return states
            self.do_statement(state, callee.body)
            self.need_clean = True
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
            
            #Attempt to compute an inlined version of the expression
            if config.simplify_function_calls and callee.body.redex and expr is not None:
                expr.reduced = Interpreter.beta_reduction(return_statement.argument, callee.params, arguments)

            if return_value is None:
                return JSUndefNaN

            return return_value
        else:
            #function is unknown, if it is a bound method, set this to top
            if this is not None:
                state.objs[this].properties.clear()
                state.objs[this].set_missing_mode(MissingMode.MISSING_IS_TOP)
                state.objs[this].properties["__probable_api"] = JSPrimitive(True)
        self.pure = False
        return JSTop
       
    #Evaluate expression and annotate AST in case of statically known value. Return abstract value.
    def eval_expr(self, state, expr):
        if state.is_bottom:
            return JSBot
        result = self.eval_expr_aux(state, expr)
        expr.static_value = State.value_join(expr.static_value, result)

        refs_to_add = set()
        if isinstance(result, JSRef):
            refs_to_add.add(result)
        elif isinstance(result, JSOr):
            for c in result.choices:
                if isinstance(c, JSRef):
                    refs_to_add.add(c)

        for ref in refs_to_add:
            state.pending.add(ref.target())
            if ref.is_bound() and type(ref.this()) is int:
                state.pending.add(ref.this())
        if expr.type == "CallExpression" and self.need_clean:
            self.bring_out_your_dead(state)
        return result
    
    def use_lvalue(self, state, lvalue_expr, consumed_refs=None):
        #try to find the dict holding the identifier or property that is being written to, and the property/identifier name
        target_id = None
        if lvalue_expr.type == "Identifier":
            #Identifier type: the simple case.
            target = state.scope_lookup(lvalue_expr.name)
            prop = lvalue_expr.name
            if target.properties is not state.objs[state.lref].properties:
                self.pure = False

        elif lvalue_expr.type == "MemberExpression": #member as lvalue
            self.pure = False
            #Member expression: identify target object (dict), and property name (string)
            target, prop, target_id = self.use_member(state, lvalue_expr, consumed_refs)
        else:
            raise ValueError("Invalid assignment left type")

        return target, prop, target_id
            
    def do_assignment(self, state, lvalue_expr, rvalue_expr, abs_rvalue, consumed_refs=None):
        target, prop, target_id = self.use_lvalue(state, lvalue_expr, consumed_refs)

        if rvalue_expr is not None and not rvalue_expr.processed and (target is None or (target_id is not None and "__probable_api" in target.properties.keys())) and isinstance(abs_rvalue, JSRef) and state.objs[abs_rvalue.target()].is_function():
            #self.deferred.append((state.clone(), state.objs[abs_rvalue.target()]))
            #print("Deferred callback handler:", prop)
            deferred_id = state.objs[state.gref].properties["___deferred"].target()
            fn_id = State.new_id()
            state.objs[deferred_id].properties[fn_id] = abs_rvalue
            rvalue_expr.processed = True

        if prop is None or target is None:
            return

        #Delete old value (if any)
        target.properties.pop(prop, None)

        target.set_member(prop, abs_rvalue)

    #Helper function to decompose member expression into object (dict) and property (string). Returns None if not found.
    def use_member(self, state, expr, consumed_refs=None):
        #Member expression type: first, try to find referenced object
        abs_target = self.eval_expr(state, expr.object)
        state.consume_expr(abs_target, consumed_refs)

        if isinstance(abs_target, JSOr) and config.use_filtering_err:
            #print("Or in usemember!", abs_target)
            c = abs_target.choices.difference({JSUndefNaN})
            if len(c) == 1:
                parent_target, parent_prop, parent_target_id = self.use_lvalue(state, expr.object, consumed_refs)
                parent_target.properties[parent_prop] = list(c)[0]
                abs_target = list(c)[0]

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
                prop = None
            elif abs_property == JSUndefNaN:
                prop = "__undefined"
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
            return None, prop, None

    #Takes state, expression, and returns a JSValue
    def eval_expr_aux(self, state, expr):
        if expr.type == "Literal":
            if expr.value is None:
                return JSPrimitive("<<NULL>>")
                #return JSUndefNaN
            return JSPrimitive(expr.value)

        elif expr.type == "Identifier":
            if expr.name == "undefined":
                return JSUndefNaN
            scope = state.scope_lookup(expr.name)
            if expr.name in scope.properties:
                return scope.properties[expr.name]
            else:
                #print("[warn] Unknown identifier: " + str(expr.name))
                return JSTop

        elif expr.type == "UpdateExpression":
            consumed_refs = set()
            argument = self.eval_expr(state, expr.argument)
            state.consume_expr(argument, consumed_refs)
            result = plugin_manager.handle_update_operation(expr.operator, state, argument)
            state.consume_expr(result, consumed_refs)

            self.do_assignment(state, expr.argument, None, result, consumed_refs)
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
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject({})
            state.pending.add(obj_id)
            ret = self.eval_func_helper(state, expr, consumed_refs, obj_id)
            state.consume_expr(ret, consumed_refs)
            state.pending.difference_update(consumed_refs)
            return JSRef(obj_id)
      
        elif expr.type == "ConditionalExpression":
            consumed_refs = set()
            abs_test_result = self.eval_expr(state, expr.test)
            state.consume_expr(abs_test_result, consumed_refs)


            if abs_test_result is JSTop:
                state_then = state
                state_else = state.clone()
                expr_then = self.eval_expr(state_then, expr.consequent)
                state.consume_expr(expr_then, consumed_refs)
                expr_else = self.eval_expr(state_else, expr.alternate)
                state.consume_expr(expr_else, consumed_refs)
                state_then.join(state_else)
                if State.value_equal(expr_then, expr_else):
                    result = expr_then
                else:
                    result = JSTop
            elif plugin_manager.to_bool(abs_test_result):
                result = self.eval_expr(state, expr.consequent)
                state.consume_expr(result, consumed_refs)
            else:
                result = self.eval_expr(state, expr.alternate)
                state.consume_expr(result, consumed_refs)

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
            if "__this" in state.objs[state.lref].properties:
                return state.objs[state.lref].properties["__this"]
            else:
                return JSRef(0)

        elif expr.type == "AssignmentExpression":
            consumed_refs = set()
            if expr.operator[0] == "=":
                abs_rvalue = self.eval_expr(state, expr.right)
                if state.is_bottom:
                    return JSBot
                state.consume_expr(abs_rvalue, consumed_refs)
                self.do_assignment(state, expr.left, expr.right, abs_rvalue, consumed_refs)
                state.pending.difference_update(consumed_refs)
                return abs_rvalue
            else:
                left = self.eval_expr(state, expr.left)
                state.consume_expr(left, consumed_refs)
                right = self.eval_expr(state, expr.right)
                state.consume_expr(right, consumed_refs)
                result = plugin_manager.handle_binary_operation(expr.operator[0], state, left, right)
                self.do_assignment(state, expr.left, None, result, consumed_refs)
                state.pending.difference_update(consumed_refs)
                return result

        elif expr.type == "ObjectExpression":
            properties = {}
            consumed_refs = set()
            prop_val = None
            for prop in expr.properties:
                if prop.type != "Property":
                    continue
                prop_val = self.eval_expr(state, prop.value)
                state.consume_expr(prop_val, consumed_refs)
                if prop_val is JSTop:
                    continue
                if not prop.computed:
                    if prop.key.name is not None:
                        properties[prop.key.name] = prop_val
                    else:
                        properties[prop.key.value] = prop_val

                else:
                    prop_key = self.eval_expr(state, prop.key)
                    state.consume_expr(prop_key, consumed_refs)
                    if isinstance(prop_key, JSPrimitive):
                        properties[prop_key.val] = prop_val
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(properties)
            state.objs[obj_id].tablength = None
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
            state.objs[obj_id].tablength = i
            state.pending.difference_update(consumed_refs)
            return JSRef(obj_id)

        elif expr.type == "MemberExpression":
            consumed_refs = set()
            target, prop, target_id = self.use_member(state, expr, consumed_refs)
            if target is None or prop is None:
                state.pending.difference_update(consumed_refs)
                return JSTop
            if isinstance(target, JSObject):
                if prop == "length":
                    state.pending.difference_update(consumed_refs)
                    if target.missing_mode == MissingMode.MISSING_IS_TOP:
                        return JSTop
                    else:
                        if target.tablength is None:
                            return JSTop
                        else:
                            return JSPrimitive(target.tablength)
                member = target.member(prop)
                if isinstance(member, JSRef) and not member.is_bound():
                    bound_member = JSRef(member.target(), target_id)
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
                        fct = JSRef(fct.target(), target)
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
                        fct = JSRef(fct.target(), target)
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
            #special handling for && and || due to shortcircuit evaluation
            if expr.operator == "&&":
                if left is JSTop:
                    state_right = state.clone()
                    right = self.eval_expr(state_right, expr.right)
                    state_right.consume_expr(right, consumed_refs)
                    state.join(state_right)
                    result = JSTop
                else:
                    if plugin_manager.to_bool(left):
                        right = self.eval_expr(state, expr.right)
                        state.consume_expr(right, consumed_refs)
                        result = right
                    else:
                        result = left
            elif expr.operator == "||":
                if left is JSTop:
                    state_right = state.clone()
                    right = self.eval_expr(state_right, expr.right)
                    state_right.consume_expr(right, consumed_refs)
                    state.join(state_right)
                    result = JSTop
                else:
                    if not plugin_manager.to_bool(left):
                        right = self.eval_expr(state, expr.right)
                        state.consume_expr(right, consumed_refs)
                        result = right
                    else:
                        result = left
            else:
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
            consumed_refs = set()
            ret = self.eval_func_helper(state, expr, consumed_refs)
            state.pending.difference_update(consumed_refs)
            return ret
        else:
            print("WARNING: Expr type not handled:" + expr.type)
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
                saved_unroll_trace = self.unroll_trace
                self.unroll_trace = None
                val = self.eval_expr(state, decl.init)
                self.unroll_trace = saved_unroll_trace
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
        state.value = self.eval_expr(state, expr)
        state.consume_expr(state.value)
    
    def do_while(self, state, statement):
        self.do_for(state, statement)

    def do_for(self, state, statement):
        if state.is_bottom:
            return
        (init, test, update, body) = (statement.init, statement.test, statement.update, statement.body.body)
        consumed_refs = set()
        saved_unroll_trace = self.unroll_trace
        self.unroll_trace = []
        prev_state = None
        i = 0
        warned = False
        saved_loopexit = self.break_state
        saved_return_state = self.return_state
        self.return_state = State.bottom()
        self.break_state = State.bottom()
        exit = False
        if init is not None:
            self.do_expr_or_statement(state, init)

        #Unrolling is performed as long as the test condition is true, and the maximum iteration count has not been reached
        unrolling = True

        #Loop analysis may terminate if one of the following conditions is met:
        # - the header state is stable
        # - the loop condition is proven false
        header_state = State.bottom()
        while True:
            if unrolling: #If we are unrolling, header_state saves current state
                if i & 31 == 0:
                    if header_state == state:
                        break
                    header_state = state.clone()
            else: #Otherwise, merge current state with header state and perform widening
                #print("merge header state because we are not unrolling")
                #print("current:", state)
                #print("header:", header_state)
                if i > config.max_iter + 10:
                    print("BUG: loop failed to stabilize after " + str(i) + " iterations")
                    print("cur: ", state)
                    print("hdr: ", header_state)
                    raise ValueError
                self.bring_out_your_dead(state)
                previous_header_state = header_state.clone()
                header_state.join(state)
                state.assign(header_state)
                previous_header_state.unify(header_state)
                if previous_header_state == header_state:
                    break
                #print("joined:", state)
            
            lastcond_is_true = False

            saved_loopcont = self.continue_state
            self.continue_state = State.bottom()
            i = i + 1
            abs_test_result = self.eval_expr(state, test)
            if state.is_bottom:
                break
            state.consume_expr(abs_test_result, consumed_refs)

            #stop unrolling because max iter reached
            if config.max_iter is not None and i > config.max_iter:
                if not warned:
                    print("[warning] Loop unrolling stopped after " + str(config.max_iter) + " iterations")
                    #raise ValueError
                    warned = True
                unrolling = False

            #print("condi: ", abs_test_result)
            if abs_test_result is JSTop or plugin_manager.to_bool(abs_test_result):
                statement.body.live = True
                self.do_sequence(state, body)
                if update:
                    self.do_expr_or_statement(state, update)
                state.join(self.continue_state)
                self.continue_state = saved_loopcont

                if not self.break_state.is_bottom: #a break was encountered
                    if state.is_bottom: #all paths go through the break
                        break
                    else:
                        unrolling = False #maybe some paths don't go through the break
                if abs_test_result is JSTop:
                    unrolling = False
                else:
                    lastcond_is_true = True
                #print("before exit:", state)
                #print("before exit:", header_state)
            
            else:
                break #stop because loop condition is proven false

        if lastcond_is_true: #Loop state stabilized and last test condition is true: this is an infinite loop
            state.set_to_bottom()

        state.join(self.break_state)
        if unrolling and not (state.is_bottom and self.return_state.is_bottom):
            if statement.unrolled is None:
                statement.unrolled = self.unroll_trace
            elif statement.unrolled != self.unroll_trace:
                statement.unrolled = False
                statement.reason = "not stable"
        else:
            statement.unrolled = False
            if not unrolling:
                statement.reason = "abstract test"
            else:
                statement.reason = "infinite loop"
        #print("loop exit:", header_state)
        #print("loop exit:", state)
        self.break_state = saved_loopexit

        self.return_state.join(saved_return_state)
      
        self.unroll_trace = saved_unroll_trace
        state.pending.difference_update(consumed_refs)

    def do_switch(self, state, statement):
        consumed_refs = set()
        (discriminant, cases) = (statement.discriminant, statement.cases)
        saved_unroll_trace = self.unroll_trace
        self.unroll_trace = None
        abs_discr = self.eval_expr(state, discriminant)
        self.unroll_trace = saved_unroll_trace
        state.consume_expr(abs_discr, consumed_refs)
        if config.merge_switch:
            abs_discr = JSTop
        has_true = False
        has_maybe = False
        states_after = []
        ncase = 0
        for case in cases:
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            abs_test = self.eval_expr(state, case.test)
            self.unroll_trace = saved_unroll_trace
            state.consume_expr(abs_test, consumed_refs)
            if (abs_test is not JSTop) and (abs_discr is not JSTop) and ((type(abs_test) != type(abs_discr)) or (abs_test != abs_discr)):
                pass #No
            elif isinstance(abs_test, JSPrimitive) and isinstance(abs_discr, JSPrimitive) and abs_test.val == abs_discr.val:
                for i in range(0, ncase + 1):
                    self.trace(cases[i].test)
                has_true = True
                state_clone = state.clone()
                saved_state = self.break_state
                self.break_state = State.bottom()
                for i in range(ncase, ncase+1):
                    self.do_sequence(state_clone, cases[i].consequent) #Yes
                    if state_clone.is_bottom:
                        break
                state_clone.join(self.break_state)
                self.break_state = saved_state
                states_after.append(state_clone)
                break
            else:
                has_maybe = True
                state_clone = state.clone()
                saved_state = self.break_state
                self.break_state = State.bottom()
                saved_unroll_trace = self.unroll_trace
                self.unroll_trace = None
                self.do_sequence(state_clone, case.consequent) #Maybe
                self.unroll_trace = saved_unroll_trace
                state_clone.join(self.break_state)
                self.break_state = saved_state
                states_after.append(state_clone)
            ncase += 1
        if not has_true:
            if has_maybe:
                self.trace(statement)
            else:
                for case in cases:
                    self.trace(case.test)
        if has_true:
            state.set_to_bottom()
        for s in states_after:
            state.join(s)
        state.pending.difference_update(consumed_refs)

    def do_filtering(self, state, condition, taken , consumed_refs=None):
        if not config.use_filtering_if:
            return
        if condition.operator == "===":
            cond = "==="
        elif condition.operator == "!==":
            cond = "!=="
            taken = not taken
        else:
            return
  
        if (condition.left.type == "Identifier" or condition.left.type == "MemberExpression") and (isinstance(condition.right.static_value, JSPrimitive) or (condition.right.static_value is JSUndefNaN)):
            left, right = condition.left, condition.right
        elif (condition.right.type == "Identifier" or condition.right.type == "MemberExpression") and (isinstance(condition.left.static_value, JSPrimitive) or (condition.left.static_value is JSUndefNaN)):
            right, left = condition.left, condition.right
        else:
            return
        
        target, prop, target_id = self.use_lvalue(state, left , consumed_refs)
        if target is None or prop is None:
            return

        if taken:
            target.properties[prop] = right.static_value
        else:
            if prop in target.properties and isinstance(target.properties[prop], JSOr):
                target.properties[prop] = JSOr(target.properties[prop].choices.difference({right.static_value}))
                if len(target.properties[prop].choices) == 0:
                    state.set_to_bottom()
                    return
                if len(target.properties[prop].choices) == 1:
                    target.properties[prop] = list(target.properties[prop].choices)[0]

    def do_if(self, state, statement):
        consumed_refs = set()
        (test, consequent, alternate) = (statement.test, statement.consequent, statement.alternate)
        saved_unroll_trace = self.unroll_trace
        self.unroll_trace = None
        abs_test_result = self.eval_expr(state, test)
        self.unroll_trace = saved_unroll_trace
        state.consume_expr(abs_test_result, consumed_refs)
        
        abs_bool = plugin_manager.abs_to_bool(abs_test_result)

        if type(abs_bool) is not bool:
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            state_then = state
            state_else = state.clone()
            self.do_filtering(state_then, test, True, consumed_refs)
            self.do_statement(state_then, consequent)

            self.do_filtering(state_else, test, False, consumed_refs)
            if alternate is not None:
                self.do_statement(state_else, alternate)
            #print("join")
            self.bring_out_your_dead(state_then)
            self.bring_out_your_dead(state_else)
            state_then.join(state_else)
            self.unroll_trace = saved_unroll_trace
            state.pending.difference_update(consumed_refs)
            return
            
        self.trace(test)

        if abs_bool is True:
            self.do_statement(state, consequent)
        else:
            #TODO temporary workaround for probably incorrect boolean value evaluation
            if config.process_not_taken:
                assert not config.simplify_control_flow, "config.simplify_control_flow is incompatible with config.process_not_taken"
                a = self.return_state
                b = self.return_value
                c = self.break_state
                d = self.continue_state
                self.return_state = State.bottom()
                self.return_value = None
                self.break_state = State.bottom()
                self.continue_state = State.bottom()
                cl = state.clone()
                self.do_statement(cl, consequent)
                self.return_state = a
                self.return_value = b
                self.break_state = c
                self.continue_state = d
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
        #do_break works by merging break_state with current state
        #break_state will be merged with the state after the loop
        self.break_state.join(state)
        state.set_to_bottom()
    
    def do_continue(self, state):
        #do_continue works by merging continue_state with current state
        #break_state will be merged with the state after the current iteration
        self.continue_state.join(state)
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

    def bring_out_your_dead(self, state, verbose=False):
        self.need_clean = False

        if not config.delete_unused:
            return
        
        state.cleanup(verbose)

    def trace(self, statement, unroll_trace=None):
        if unroll_trace is None:
            unroll_trace = self.unroll_trace
        if unroll_trace is not None:
            if statement.trace_id is None:
                newid = State.new_id()
                if newid == 108:
                    print(statement)
                statement.trace_id = newid
            unroll_trace.append(statement)
        return

    def do_statement(self, state, statement, hoisting=False):
        if state.is_bottom:
            debug("Ignoring dead code: ", statement.type)
            return

        statement.live = True

        debug("Current state: ", state)

        line1 = self.offset2line(statement.range[0])
        line2 = self.offset2line(statement.range[1])

        self.last = statement.type + ", range: " + str(statement.range) + ", lines: "+ str(line1) + "-" + str(line2) + "\nsource: " + self.data[statement.range[0]:statement.range[1]]

        debug("interpreting: ", self.last)


        if statement.type == "VariableDeclaration":
            if not hoisting:
                self.trace(statement)
                saved_unroll_trace = self.unroll_trace
                self.unroll_trace = None
            for decl in statement.declarations:
                self.do_vardecl(state, decl, hoisting)
            if not hoisting:
                self.unroll_trace = saved_unroll_trace

        elif statement.type == "ExpressionStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_exprstat(state, statement.expression)
            self.unroll_trace = saved_unroll_trace

        elif statement.type == "ForOfStatement":
            print("ForOfStatement")
            pass #TODO
        
        elif statement.type == "ForStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_for(state, statement)
            self.unroll_trace = saved_unroll_trace

        elif statement.type == "IfStatement":
            self.do_if(state, statement)

        elif statement.type == "FunctionDeclaration":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_fundecl(state, statement)
            self.unroll_trace = saved_unroll_trace
       
        elif statement.type == "ReturnStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_return(state, statement.argument)
            self.unroll_trace = saved_unroll_trace

        elif statement.type == "WhileStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_while(state, statement)
            self.unroll_trace = saved_unroll_trace
        
        elif statement.type == "BreakStatement":
            self.do_break(state)
        
        elif statement.type == "ContinueStatement":
            self.do_continue(state)

        elif statement.type == "TryStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_statement(state, statement.block) #TODO we assume that exceptions never happen  ¯\_(ツ)_/¯
            self.unroll_trace = saved_unroll_trace
        
        elif statement.type == "BlockStatement":
            self.trace(statement)
            saved_unroll_trace = self.unroll_trace
            self.unroll_trace = None
            self.do_sequence_with_hoisting(state, statement.body)
            self.unroll_trace = saved_unroll_trace
        
        elif statement.type == "EmptyStatement":
            pass

        elif statement.type == "SwitchStatement":
            self.do_switch(state, statement)

        elif statement.type == "ClassDeclaration":
            return 

        else:
            print("WARNING: Statement type not handled: " + statement.type)
            #raise ValueError("Statement type not handled: " + statement.type)



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


    def run(self, entry_state=None):
        self.return_value = None
        self.closure = {}
        self.return_state = State.bottom()
        self.break_state = State.bottom()
        self.continue_state = State.bottom()
        self.pure = True

        if entry_state is None:
            state = State(glob=True, bottom=False)

            eval_obj = plugin_manager.register_preexisting_object(JSObject.simfct(eval_fct))
            plugin_manager.register_global_symbol("eval", JSRef(eval_obj))

            deferred_obj = plugin_manager.register_preexisting_object(JSObject({}))
            plugin_manager.register_global_symbol("___deferred", JSRef(deferred_obj))

            for (ref_id, obj) in plugin_manager.preexisting_objects:
                state.objs[ref_id] = obj
            
            for (name, value) in plugin_manager.global_symbols:
                state.objs[state.gref].properties[name] = value
            
            State.set_next_id(plugin_manager.ref_id)
        else:
            state = entry_state

        debug("Dumping Abstract Syntax Tree:")
        debug(self.ast.body)
        debug("Init state: ", str(state))
        GCConfig.preexisting_objects = plugin_manager.preexisting_objects

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
        print("Abstract state stabilized.")
        self.bring_out_your_dead(state)
        debug("Abstract state at end: ", state)
        if config.debug:
            print("End value:", state.value, end="")
            if isinstance(state.value, JSRef):
                print("", state.objs[state.value.target()])
        dead_funcs = 0
        funcs = 0
        print("Processing callbacks...")
        deferred_id = state.objs[state.gref].properties["___deferred"].target()

        prev_header_state = None

        header_state = State.bottom()
        i = 0
        while True:
            i = i + 1
            if i == 5000:
                break
            prev_header_state = header_state.clone()
            self.bring_out_your_dead(state)
            header_state.join(state)
            state.assign(header_state)
            self.bring_out_your_dead(prev_header_state)
            self.bring_out_your_dead(header_state)
            prev_header_state.unify(header_state)
            self.bring_out_your_dead(prev_header_state)
            fn_refs = set()
            for d in state.objs[deferred_id].properties.values():
                if isinstance(d, JSRef):
                    fn_refs.add(d)
                elif isinstance(d, JSOr):
                    for c in d.choices:
                        if isinstance(c, JSRef):
                            fn_refs.add(c)
            
            if header_state == prev_header_state:
                break

            for r in fn_refs:
                state_fn = state.clone()
                self.eval_func_call(state_fn, state_fn.objs[r.target()], None)
                state.join(state_fn)

        print("End of callback processing.")
