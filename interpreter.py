from abstract import State, JSClosure, JSObject, JSUndefNaN, JSTop, JSRef, JSSimFct, JSPrimitive, JSValue

from debug import debug

import esprima
import plugin_manager
import output
import config
import sys
import bisect

class Stats:
    computed_values = 0
    beta_reductions = 0
    steps = 0

class Interpreter(object):
    def __init__(self, ast, data):
        self.ast = ast
        self.funcs = []
        self.data = data
        self.lines  = []
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
        else:
            raise ValueError("beta_reduction: unhandled expression type " + str(expression.type))

    #Evaluate a function call, takes callee and function arguments, returns abstract value
    def eval_func_call(self, state, callee, expr):
        if expr is None:
            arguments = []
        else:
            arguments = expr.arguments
        #callee can be either JSTop, JSClosure or JSSimFct
        
        #Argument evaluation is the same in each case.
        #Evaluate argument, then handle the actual function call.
        args_val = []
        for argument in arguments:
            v = self.eval_expr_annotate(state, argument)
            if isinstance(callee, JSSimFct) or isinstance(callee, JSClosure):
                args_val.append(v)
            elif isinstance(v, JSClosure):
                #If the function is unknown, and closures are passed as arguments, we assume these closures will be called by the unknown function.
                self.eval_func_call(state, v, None)

        if isinstance(callee, JSSimFct):
            self.pure = False #TODO implement a way for plugins to tell the interpreter that a python function is pure.
            return callee.fct(*args_val)

        if isinstance(callee, JSClosure):
            callee.body.used = True
            
            if callee.body.type is "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body

            if callee.body.type is "BlockStatement" and len(callee.body.body) > 0 and callee.body.body[0].type is "ReturnStatement":
                callee.body.redex = True
                return_statement = callee.body.body[0]

            if config.inlining and callee.body.redex and expr is not None:
                Stats.beta_reductions += 1
                expr.reduced = Interpreter.beta_reduction(return_statement.argument, callee.params, arguments)
        
            #Enter callee context 
            saved_return = self.return_value
            saved_rstate = self.return_state
            saved_lref = state.lref
            saved_pure = self.pure

            self.return_value = None
            self.return_state = State.bottom()
            state.lref = State.new_id()
            state.objs[state.lref] = JSObject({})
            state.objs[state.lref].inc()
            self.pure = True

            #bind argument values
            i = 0
            for v in args_val:
                state.objs[state.lref].properties[callee.params[i].name] = v
                if v.ref() is not None:
                    state.objs[v.ref()].inc()
                i = i + 1
       
            #bind closure environment, if any
            if callee.ref() is not None:
                state.objs[state.lref].properties["__closure"] = JSRef(callee.ref())
                state.objs[callee.env].inc()
           
            #evaluate function, join any return states
            self.do_statement(state, callee.body)
            callee.body.pure = self.pure
            state.join(self.return_state)
           
            #Save function return value
            return_value = self.return_value
       
            #Leave callee context
            self.return_value = saved_return
            self.return_state = saved_rstate
            state.objs[state.lref].dec(state.objs, state.lref)
            state.lref = saved_lref
            self.pure = saved_pure and self.pure

            if return_value is None:
                return JSUndefNaN

            return return_value
        self.pure = False
        return JSTop
       
    #Evaluate expression and annotate AST in case of statically known value. Return abstract value.
    def eval_expr_annotate(self, state, expr):
        result = self.eval_expr(state, expr)
        if result is not JSTop:
            expr.static_value = State.value_join(expr.static_value, result)
            Stats.computed_values += 1
        return result

    #Helper function to decompose member expression into object (dict) and property (string). Returns None if not found.
    def use_member(self, state, expr):
        #Member expression type: first, try to find referenced object
        abs_ref = self.eval_expr_annotate(state, expr.object)

        #If we cannot locate the referenced object, we will return JSTop later (but still evaluate computed property, if needed)
        has_ref_obj = isinstance(abs_ref, JSRef)

        if has_ref_obj:
            target = state.objs[abs_ref.ref()]

        #Now, try to find the property name, it can be directly given, or computed.
        if expr.computed:
            #Property name is computed (i.e. tab[x + 1])
            abs_property = self.eval_expr_annotate(state, expr.property)
            if abs_property is JSTop:
                return None
            elif isinstance(abs_property, JSPrimitive):
                prop = abs_property.val
            else:
                raise ValueError("Invalid property type")
        else:
            #Property name is directly given (i.e. foo.bar)
            prop = expr.property.name
        if not has_ref_obj:
            return None
        return target, prop

    #Takes state, expression, and returns a JSValue
    def eval_expr(self, state, expr):
        if expr.type == "Literal":
            if expr.value is None:
                return JSUndefNaN
            return JSPrimitive(expr.value)

        elif expr.type == "Identifier":
            scope = state.scope_lookup(expr.name)
            if expr.name in scope:
                return scope[expr.name]
            else:
                return JSTop #untracked identifier

        elif expr.type == "UpdateExpression":
            print("UpdateExpression")
            return JSTop #TODO

        elif expr.type == "NewExpression":
            for argument in expr.arguments:
                arg_val = self.eval_expr_annotate(state, argument)
            return JSTop
      
        elif expr.type == "ConditionalExpression":
            abs_test_result = self.eval_expr_annotate(state, expr.test)

            if abs_test_result is JSTop:
                state_then = state
                state_else = state.clone()
                expr_then = self.eval_expr_annotate(state_then, expr.consequent)
                expr_else = self.eval_expr_annotate(state_else, expr.alternate)
                state_then.join(state_else)
                if State.value_equal(expr_then, expr_else):
                    return expr_then
                else:
                    return JSTop

            if plugin_manager.to_bool(abs_test_result):
                return self.eval_expr_annotate(state, expr.consequent)
            else:
                return self.eval_expr_annotate(state, expr.alternate)

        elif expr.type == "SequenceExpression":
            for e in expr.expressions:
                r = self.eval_expr_annotate(state, e)
            return r

        elif expr.type == "ThisExpression":
            return JSTop

        elif expr.type == "AssignmentExpression":
            #Assignment can be either to an identifier (simple variable) or member expression (object.field or object[field])
            #In case of member expression, the field can be computed (blah[i + i]) or not (blah.toto)

            #In any case, we start by computing the (source) rvalue. 
            #Even if it is JSTop, we cannot return right away, because we might need to delete dict entries
            abs_rvalue = self.eval_expr_annotate(state, expr.right)

            #Next try to find the dict holding the identifier or property that is being written to, and the property/identifier name
            if expr.left.type == "Identifier":
                #Identifier type: the simple case.
                target = state.scope_lookup(expr.left.name)
                prop = expr.left.name
                if target is not state.objs[state.lref].properties:
                    self.pure = False

            elif expr.left.type == "MemberExpression":
                self.pure = False
                #Member expression: identify target object (dict), and property name (string)
                r = self.use_member(state, expr.left)
                if r is None:
                    return JSTop
                target = r[0].properties
                prop = r[1]

            else:
                raise ValueError("Invalid assignment left type")

            #Delete old value (if any), and decrease reference counter if needed
            old = target.pop(prop, None)
            if old is not None and old.ref() is not None:
                state.objs[old.ref()].dec(state.objs, old.ref())

            if abs_rvalue is not JSTop:
                target[prop] = abs_rvalue
                if abs_rvalue.ref() is not None:
                    state.objs[abs_rvalue.ref()].inc()
            return abs_rvalue

        elif expr.type == "ObjectExpression":
            properties = {}
            for prop in expr.properties:
                if prop.type != "Property":
                    continue
                prop_val = self.eval_expr_annotate(state, prop.value)
                if prop_val is JSTop:
                    continue
                if not prop.computed:
                    properties[prop.key.value] = prop_val
                    if prop_val.ref() is not None:
                        state.objs[prop_val.ref()].inc()

                else:
                    prop_key = self.eval_expr_annotate(state, prop.key)
                    if isinstance(prop_key, JSPrimitive):
                        properties[prop_key.val] = prop_val
                        if prop_val.ref() is not None:
                            state.objs[prop_val.ref()].inc()
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(properties)
            return JSRef(obj_id)

        elif expr.type == "ArrayExpression":
            elements = {}
            i = 0
            for elem in expr.elements:
                elements[i] = self.eval_expr_annotate(state, elem)
                if elements[i].ref() is not None:
                    state.objs[elements[i].ref()].inc()
                i = i + 1
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(elements)
            return JSRef(obj_id)

        elif expr.type == "MemberExpression":
            r = self.use_member(state, expr)
            if r is None:
                return JSTop
            target, prop = r
            return target.member(prop)

        elif expr.type == "UnaryExpression": #Unary expression computation delegated to plugins
            argument = self.eval_expr_annotate(state, expr.argument)
            return plugin_manager.handle_unary_operation(expr.operator, argument)

        elif expr.type == "BinaryExpression" or expr.type == "LogicalExpression": #Also delegated to plugins
            left = self.eval_expr_annotate(state, expr.left)
            right = self.eval_expr_annotate(state, expr.right)
            return plugin_manager.handle_binary_operation(expr.operator, left, right)

        elif expr.type == "FunctionExpression" or expr.type == "ArrowFunctionExpression":
            if state.lref == state.gref: #if global scope, no closure
                f = JSClosure(expr.params, expr.body, None)
            else: #otherwise, closure referencing local scope
                f = JSClosure(expr.params, expr.body, state.lref)
            
            if f.body.seen is not True:
                if False and state.lref != state.gref:
                    state.objs[state.lref].inc()
                f.body.seen = True
                f.body.name = "<anonymous>"
                self.funcs.append(f)
            return f

        elif expr.type == "CallExpression":
            callee = self.eval_expr_annotate(state, expr.callee)
            ret =  self.eval_func_call(state, callee, expr)
            return ret

        else:
            raise ValueError("Expr type not handled:" + expr.type)
        return

    def do_vardecl(self, state, decl, hoisting=False):
        #This is called twice.
        #One time during hoisting (to declare variables)
        #And one time to do variable initialization
        if decl.type == "VariableDeclarator":
            if hoisting or decl.init is None: #Only declaration (set value to undefined)
                scope = state.objs[state.lref].properties
                scope[decl.id.name] = JSUndefNaN
            else:
                val = self.eval_expr_annotate(state, decl.init)
                scope = state.objs[state.lref].properties
                #remove old variable
                old = scope.pop(decl.id.name, None)
                if old is not None and old.ref() is not None:
                    state.objs[old.ref()].dec(state.objs, old.ref())

                #compute new value
                if val is not JSTop:
                    scope[decl.id.name] = val
                    if val.ref() is not None:
                        state.objs[val.ref()].inc()
        else:
            raise ValueError("Vardecl type not handled:" + decl.type)

    def do_exprstat(self, state, expr):
        self.eval_expr_annotate(state, expr)

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
            abs_test_result = self.eval_expr_annotate(state, test)
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
            
            elif plugin_manager.to_bool(abs_test_result):
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
        abs_discr = self.eval_expr_annotate(state, discriminant)
        has_true = False
        states_after = []
        for case in cases:
            abs_test = self.eval_expr_annotate(state, case.test)
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
        abs_test_result = self.eval_expr_annotate(state, test)

        if abs_test_result is JSTop:
            state_then = state
            state_else = state.clone()
            self.do_statement(state_then, consequent)
            if alternate is not None:
                self.do_statement(state_else, alternate)
            state_then.join(state_else)
            return

        if plugin_manager.to_bool(abs_test_result):
            self.do_statement(state, consequent)
        else:
            #TODO temporary workaround for probably incorrect boolean value evaluation
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

    def do_fundecl(self, state, name, params, body):
        scope = state.objs[state.lref].properties
        if state.lref == state.gref:
            scope[name] = JSClosure(params, body, None)
        else:
            if name in scope:
                if scope[name].ref() is not None:
                    state.objs[scope[name].ref()].dec()
            scope[name] = JSClosure(params, body, state.lref)
            state.objs[state.lref].inc()

        if scope[name].body.seen is not True:
            if False and state.lref != state.gref:
                state.objs[state.lref].inc()
            scope[name].body.seen = True
            scope[name].body.name = name
            self.funcs.append(scope[name])

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
            arg_val = self.eval_expr_annotate(state, argument)
        if self.return_value is None:
            self.return_value = arg_val.clone()
        elif not (type(self.return_value) == type(arg_val) and self.return_value == arg_val):
            self.return_value = JSTop
        
        self.return_state.join(state)
        
        state.set_to_bottom()

    def bring_out_your_dead(self, state):
        #garbage collect all unreferenced objects

        #print("before clean", state)
        if config.delete_unused:
            bye = []
            for o in state.objs:
                if o != state.gref:
                    nclosures = 0
                    for c in state.objs[o].properties:
                        c_obj = state.objs[o].properties[c]
                        if isinstance(c_obj, JSClosure) and c_obj.env == o:
                            nclosures += 1
                    #when counting references to object, do not count closures within it, referencing to the object itself
                    if state.objs[o].refcount == nclosures:
                        bye.append(o)
            for b in bye:
                del state.objs[b]
        #print("after clean", state)

    def do_statement(self, state, statement, hoisting=False):
        if state.is_bottom:
            debug("Ignoring dead code: ", statement.type)
            return

        Stats.steps += 1

        #debug("Current state: ", state)

        line1 = self.offset2line(statement.range[0])
        line2 = self.offset2line(statement.range[1])

        debug("Interpreting statement:", statement.type, " range:", statement.range, " lines:", str(line1) + "-" + str(line2))

        if statement.type == "VariableDeclaration":
            for decl in statement.declarations:
                self.do_vardecl(state, decl, hoisting)

        elif statement.type == "ExpressionStatement":
            self.do_exprstat(state, statement.expression)

        elif statement.type == "ForOfStatement":
            print("ForOfStatement")
            pass #TODO
        
        elif statement.type == "ForStatement":
            print("ForStatement")
            pass #TODO

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
        self.pure = True

        for (ref_id, obj) in plugin_manager.preexisting_objects:
            state.objs[ref_id] = obj
        
        for (name, value) in plugin_manager.global_symbols:
            state.objs[state.gref].properties[name] = value
            if value.ref() is not None:
                state.objs[value.ref()].inc()
        
        State.set_next_id(plugin_manager.ref_id)

        debug("Dumping Abstract Syntax Tree:")
        debug(self.ast.body)
        debug("Init state: ", str(state))
        print("Starting abstract interpretation...")
        self.do_sequence_with_hoisting(state, self.ast.body)
        print("\nAbstract state stabilized after", Stats.steps, "steps")
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



