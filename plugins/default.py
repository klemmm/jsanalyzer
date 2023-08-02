"""
Default plugin implementing basic js functions and operators

"""
import re
import base64
import urllib.parse
import esprima
import math
import sys
from jseval import *
from typing import Callable


# Imported/injected symbols from plugin manager
JSValue : object = None
JSOr : JSValue = None
JSBot : JSValue = None
JSTop : JSValue = None
JSUndef : JSValue = None
JSPrimitive : JSValue = None
JSObject : JSValue = None
JSRef : JSValue = None
JSSpecial : object = None
JSNull : JSValue = None
State : object = None
MissingMode : object = None
set_ann : Callable = None
get_ann : Callable = None
register_update_handler : Callable = None
to_bool : Callable = None
register_preexisting_object : Callable = None
register_unary_handler : Callable = None
register_binary_handler : Callable = None
register_global_symbol : Callable = None
lift_or : Callable = None
register_method_hook : Callable = None
Interpreter : object = None
Data : object = None    

def initialize() -> None:
    """
    Plugin initialization. Called when the interpreter is initialized.
    
    """    
    def update_handler(opname : str, state : State, abs_arg : JSValue) -> JSValue:
        """
        Handler for updates (++ or --) operations. It returns the
        value to be assigned to the updated variable. The actual
        value of the expression is computed in the interpreter
        (based on the prefix/postfix flag).

        :param str opname: The operation ("++" or "--")
        :param State state: The abstract state
        :param JSValue abs_arg: Th abstract value of the expression
        :return: The abstract value to be assigned to the updated variable
        :rtype JSValue:
        
        """
        if isinstance(abs_arg, JSPrimitive) and type(abs_arg.val) is float:
            if opname == "++":
                return JSPrimitive(abs_arg.val + 1)
            elif opname == "--":
                return JSPrimitive(abs_arg.val - 1)
            else:
                print("Unknown update operation: ", opname)
                return JSTop
        else:
            return JSTop
    
    """
    Simfct to display arguments
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression (NOT the expressions to display)
    :param List[JSValue] args: The arguments to display
    """
    def ___display(state : State, expr : esprima.nodes.Node, *args : List[JSValue]) -> None:
        print("displaying args:")
        #print("state=", state)
        i = 0
        for a in args:
            print("Arg", i, "type:", type(a), "value:", a, end="")
            if isinstance(a, JSRef):
                print(" target:", state.objs[a.target()])
            elif isinstance(a, JSPrimitive):
                print(" concrete type:", type(a.val))
            else:
                print("")
            #print(expr.arguments[i])
            i += 1
        print("")
        return JSUndef

    """
    Simfct method to create a string of length 1 from a charcode.
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSRef obj: The "String" object
    :param JSValue code: The abstract value for char code (may be a string or array)
    :return: The JSValue for the string
    :rtype JSValue:
    """
    def string_fromcharcode(state : State, expr : esprima.nodes.Node, obj : JSRef, code : JSValue) -> JSValue:
        if code is JSTop or isinstance(code, JSOr):
            return JSTop

        n = any_to_number(state, code)
        if n is JSTop:
            return JSTop
        if math.isnan(n.val):
            return JSPrimitive("\x00")
        return JSPrimitive(chr(int(n.val)))    


    """
    Simfct to print the current state
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    """
    def ___state(state : State, expr : esprima.nodes.Node) -> None:
        print("___state:", state)
        return JSTop


    """
    Simfct to parse string to int
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param str s: The string to parse
    :param JSValue base: The base (defaults to 10)
    """
    def parse_int(state : State, expr : esprima.nodes.Node, s : JSPrimitive, base : JSValue = JSPrimitive(10.0)):
        if s is JSUndef:
            return JSUndef
        if isinstance(s, JSPrimitive) and type(s.val) is float:
            s = JSPrimitive(str(int(s.val)))
        if isinstance(s, JSPrimitive) and type(s.val) is str and isinstance(base, JSPrimitive) and type(base.val) is float:
            if base.val > 36:
                return JSPrimitive(float("nan"))
            alpha = ''
            if base.val > 10:
                alpha = 'a-' + chr(ord('a') + int(base.val) - 11)
            prefix = re.sub('[^0-9' + alpha + '].*', '', s.val.lower())
            if prefix == "":
                return JSPrimitive(float("nan"))
            else:
                return JSPrimitive(float(int(prefix, int(base.val))))
        return JSTop


    """
    Simfct to abort analysis if expression is not statically true
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue b: The value of the expression to test
    """
    def ___assert(state : State, expr : esprima.nodes.Node, b : JSValue) -> None:
        if (isinstance(b, JSPrimitive) or isinstance(b, JSRef)) and to_bool(b):
            return JSTop
        raise AssertionError("Analyzer assertion failed: " + str(b))


    """
    Simfct that tests whether an expression correspond to a single concrete value
    
    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue b: The value of the expression to test
    """
    def ___is_concretizable(state : State, expr : esprima.nodes.Node, b : JSValue) -> JSPrimitive:
        return JSPrimitive(b is not JSTop)


    """
    Simfct to get index of element in array or string. Bound to all objects via hook.

    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue arr: The array or string
    :param JSValue item: The value to search in the array
    :param JSValue start: The search start index (default to 0)
    :return: The index of the element, or JSPrimitive(-1.0)
    :rtype JSPrimitive:

    """
    def array_indexof(state : State, expr : esprima.nodes.Node, arr : JSValue, item : JSValue, start : JSValue = JSPrimitive(0.0)) -> JSValue:
        if arr is JSTop or item is JSTop or start is JSTop:
            return JSTop
        if hasattr(arr, 'properties'):
            i = 0
            for key,values in arr.properties.items():
                if i < start.val:
                    i = i + 1
                    continue
                if item is JSTop:
                    return JSTop
                if values == item:
                    return JSPrimitive(i)
                i = i + 1
            return JSPrimitive(-1.0)
        elif hasattr(arr, 'val') and type(arr.val) is str:
            return JSPrimitive(float(arr.val.find(item.val, int(start.val))))
        else:
            raise NameError('Invalid Javascript')
    """
    Simfct to get reverse array. Bound to all objects via hook.

    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue arr: The array to reverse
    :return: The reversed array
    :rtype JSValue:

    """
    def array_reverse(state : State, expr : esprima.nodes.Node, arr : JSValue) -> JSValue:
        if arr is JSTop:
            return JSTop
        obj_id = State.new_id()
        d = dict()
        l = len(arr.properties)
        for key,values in arr.properties.items():
            d[l - key - 1] = values
        state.objs[obj_id] = JSObject(d)
        return JSRef(obj_id)

    """
    Simfct to pop element from array. Bound to all objects via hook.

    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue arr: The array to pop
    :return: The popped element
    :rtype JSValue:

    """
    def array_pop(state : State, expr : esprima.nodes.Node, arr : JSValue) -> JSValue:
        if arr is JSTop:
            return JSTop
        if arr.tablength is None:
            arr.properties.clear()
            arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
            return JSTop
        if arr.tablength == 0:
            return JSUndef
        value = arr.properties[arr.tablength - 1]
        del arr.properties[arr.tablength - 1]
        arr.tablength -= 1
        return value

    """
    Simfct to push element to array. Bound to all objects via hook.

    :param State state: The abstract state
    :param esprima.nodes.Node expr: The call expression
    :param JSValue arr: The array to push
    :param JSValue value: The value to push


    """
    def array_push(state : State, expr : esprima.nodes.Node, arr : JSValue, value : JSValue) -> None:
        if arr is JSTop:
            return JSTop
        if arr.tablength is None:
            arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
            return JSTop
        arr.properties[arr.tablength] = value
        arr.tablength += 1
        return JSPrimitive(float(arr.tablength))

    def array_shift(state, expr, arr):
        if arr is JSTop:
            return JSTop
        if arr.tablength is None:
            arr.properties.clear()
            arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
        if arr.tablength == 0:
            return JSUndef
        indexes = sorted([i for i in arr.properties if type(i) is int])
        if 0 in indexes:
            retval = arr.properties[0]
            del arr.properties[0]
            del indexes[0]
            arr.tablength -= 1
        else:
            retval = JSUndef
        for i in indexes:
            arr.properties[i - 1] = arr.properties[i]
            del arr.properties[i]

        return retval

    def array_join(state, expr, arr, separator=JSPrimitive(",")):
        if arr.contains_top():
            return JSTop
        if separator is JSTop:
            return JSTop
        return JSPrimitive(separator.val.join([arr.properties[i].val for i in sorted(arr.properties)]))

    def array_hook(name):
        if name == "pop":
            return JSRef(array_pop_ref)
        elif name == "shift":
            return JSRef(array_shift_ref)
        elif name == "push":
            return JSRef(array_push_ref)
        elif name == "indexOf":
            return JSRef(array_indexof_ref)
        elif name == "reverse":
            return JSRef(array_reverse_ref)
        elif name == "join":
            return JSRef(array_join_ref)
        else:
            return JSTop

    def string_split(state, expr, string, separator=None, count=None):
        if separator is None:
            return string
        if isinstance(string, JSPrimitive) and isinstance(separator, JSPrimitive) and type(string.val) is str and type(separator.val) is str:
            if separator.val == "":
                result = [*string.val]
            else:
                result = string.val.split(separator.val)
            if count is not None:
                if isinstance(count, JSPrimitive) and type(count.val) is float:
                    result = result[0:int(count.val)]
                else:
                    return JSTop
            obj_id = State.new_id()
            state.objs[obj_id] = JSObject(dict(enumerate([JSPrimitive(r) for r in result])))
            state.objs[obj_id].tablength = len(state.objs[obj_id].properties)
            return JSRef(obj_id)
        return JSTop

    def any_to_string(state, value):
        if isinstance(value, JSRef):
            obj = state.objs[value.target()]
            if obj.is_function():
                return JSPrimitive(Data.source[obj.range[0]:obj.range[1]])
            if obj.tablength is None:
                return JSPrimitive("[object Object]")
            
            stringed_elems = []
            for i in range(obj.tablength):
                if i not in obj.properties:
                    return JSTop
                abs_stringed_item = any_to_string(state, obj.properties[i])
                if abs_stringed_item is JSTop:
                    return JSTop
                stringed_elems.append(abs_stringed_item.val)
            return JSPrimitive(",".join(stringed_elems))
        return binary_handler("+", state, JSPrimitive(""), value)

    def string_to_number(state, value):
        return unary_handler("+", state, value)
    
    def any_to_number(state, value):
        s = any_to_string(state, value)
        if s is JSTop:
            return JSTop
        return string_to_number(state, s)

    def any_to_boolean(state, value):
        if value is JSTop:
            return JSTop
        if isinstance(value, JSRef):
            return JSPrimitive(True)        
        r = unary_handler("!", state, value)
        if r is JSTop:
            return JSTop
        return JSPrimitive(not r.val)
            
    def string_charcodeat(state, expr, string, position):
        if not (isinstance(string, JSPrimitive) and type(string.val) is str):
            return JSTop
        if position is JSTop:
            return JSTop
        pos = any_to_number(state, position)
        if pos is JSTop:
            return JSTop
        if pos.val < 0 or pos.val >= len(string.val):
            return JSUndef
        return JSPrimitive(float(ord(string.val[int(pos.val)])))

    def string_charat(state, expr, string, position):
        if not (isinstance(string, JSPrimitive) and type(string.val) is str):
            return JSTop
        if position is JSTop:
            return JSTop
        pos = any_to_number(state, position)
        if pos is JSTop:
            return JSTop        
        if pos.val < 0 or pos.val >= len(string.val):
            return JSUndef
        return JSPrimitive(string.val[int(pos.val)])

    def string_substr(state, expr, string, start=JSPrimitive(0.0), length=JSPrimitive(None)):
        if not (isinstance(string, JSPrimitive) and type(string.val) is str):
            return JSTop
        if start is JSTop:
            return JSTop
        if length is JSTop:
            return JSTop
        sta = any_to_number(state, start)
        if length != JSPrimitive(None):
            leng = any_to_number(state, length)
            if leng is JSTop:
                return JSTop
        if sta is JSTop:
            return JSTop
        if sta.val < 0:
            return JSUndef
        if length == JSPrimitive(None):            
            return JSPrimitive(string.val[int(sta.val):])
        else:
            if sta.val + leng.val > len(string.val):
                return JSUndef
            else:
                return JSPrimitive(string.val[int(sta.val):int(sta.val) + int(leng.val)])

    def string_substring(state, expr, string, start=JSPrimitive(0.0), end=None):
        if not (isinstance(string, JSPrimitive) and type(string.val) is str):
            return JSTop
        if start is JSTop:
            return JSTop
        if end is JSTop:
            return JSTop
        sta = any_to_number(state, start)
        if sta is JSTop:
            return JSTop
        if end != None:
            end = any_to_number(state, end)
            if end is JSTop:
                return JSTop
        if sta.val < 0:
            return JSUndef
        if end is None:
            return JSPrimitive(string.val[int(sta.val):])
        else:
            if end.val > len(string.val):
                return JSUndef
            else:
                return JSPrimitive(string.val[int(sta.val):int(end.val)])

    def string_replace(state, expr, string, pattern, replacement):
        if string is JSTop or pattern is JSTop or replacement is JSTop:
            return JSTop
        if type(pattern.val) is re.Pattern:
            return JSPrimitive(re.sub(pattern.val, replacement.val, string.val))
        else:
            return JSPrimitive(string.val.replace(pattern.val, replacement.val, 1))

    def string_slice(state, expr, string, begin=JSPrimitive(0.0), end=JSPrimitive(None)):
        if isinstance(string, JSPrimitive) and type(string.val) is str and isinstance(begin, JSPrimitive) and type(begin.val) is float and isinstance(end, JSPrimitive) and (type(end.val) is float or end.val is None):
            if end.val is None:
                return JSPrimitive(string.val[int(begin.val):])
            return JSPrimitive(string.val[int(begin.val):int(end.val)])
        else:
            #print("slice: unhandled argument: ", string, " begin: ", begin, "end: ", end)
            return JSTop

    def string_hook(name):
        if name == "split":
            return JSRef(string_split_ref)
        if name == "charCodeAt":
            return JSRef(string_charcodeat_ref)
        if name == "charAt":
            return JSRef(string_charat_ref)
        if name == "slice":
            return JSRef(string_slice_ref)
        if name == "substr":
            return JSRef(string_substr_ref)
        if name == "substring":
            return JSRef(string_substring_ref)
        if name == "replace":
            return JSRef(string_replace_ref)
        return JSTop

    def baseconv(n, b):
        alpha = "0123456789abcdefghijklmnopqrstuvwxyz"
        ret = ""
        if n < 0:
            n = -n
            ret = "-"
        if n >= b:
            ret += baseconv(n // b, b)
        return ret + alpha[n % b]

    def function_or_int_tostring(state, expr, fn_or_int, base=JSPrimitive(10.0)):
        if isinstance(fn_or_int, JSPrimitive) and type(fn_or_int.val) is float and isinstance(base, JSPrimitive) and type(base.val) is float:
            return JSPrimitive(baseconv(int(fn_or_int.val), int(base.val)))
        elif fn_or_int.is_function():
            return JSPrimitive(Data.source[fn_or_int.range[0]:fn_or_int.range[1]])
        else:
            print("warning: .toString() unhandled argument: ", fn_or_int, "base:", base)
            return JSTop

    function_or_int_tostring_ref = register_preexisting_object(JSObject.simfct(function_or_int_tostring, True))
    def function_hook(name):
        if name == "toString":
            return JSRef(function_or_int_tostring_ref)
        return JSTop


    def atob(state, expr, string):
        if isinstance(string, JSPrimitive) and type(string.val) is str:
            return JSPrimitive(base64.b64decode(string.val).decode("latin-1"))
        return JSTop

    def btoa(state, expr, string):
        if isinstance(string, JSPrimitive) and type(string.val) is str:
            return JSPrimitive(base64.b64encode(str.encode(string.val)))
        return JSTop


    def decode_uri_component(state, expr, string):
        if isinstance(string, JSPrimitive) and type(string.val) is str:
            return JSPrimitive(urllib.parse.unquote(string.val))
        return JSTop

    def decode_uri(state, expr, string):
        if isinstance(string, JSPrimitive) and type(string.val) is str:
            return call_function("decodeURI", [string])
        else:
            return JSTop

    def math_round(state, expr, this, number):
        if isinstance(number, JSPrimitive) and type(number.val) is float:
            return JSPrimitive(float(round(number.val)))
        return JSTop

    def regexp_match(state, expr, this, target):
        return JSPrimitive(this.properties["regexp"].val.match(target.val) is not None)

    def regexp(state, expr, this, string):
        if isinstance(string, JSPrimitive) and type(string.val) is str:
            this.properties["regexp"] = JSPrimitive(re.compile(string.val))
            test_id = State.new_id()
            state.objs[test_id] = JSObject.simfct(regexp_match, True)
            this.properties["test"] = JSRef(test_id)
        else:
            this.set_missing_mode(MissingMode.MISSING_IS_TOP)
            this.properties.clear()
        return JSUndef


    def fn_cons(state, expr, this, *args):
        raw_body = args[-1]
        fn_args = args[0:-1] #TODO
        if raw_body is JSTop:
            return JSTop #TODO should clear entire state here
        if isinstance(raw_body, JSPrimitive) and type(raw_body.val) is str:
            fn_body = "(function() {" + raw_body.val + "})"
            ast = esprima.parse(fn_body, options={ 'range': True})
            i = Interpreter(ast, fn_body, True)
            i.run(state)
            set_ann(expr, "fn_cons", ast.body)
            return state.value
        else:
            return JSTop

    def eval_fct(state, expr, target): 
        if target is JSTop:
            return JSTop #TODO should clear entire state here
        if isinstance(target, JSPrimitive) and type(target.val) is str:
            print(get_ann(expr, "eval") is None)
            if get_ann(expr, "eval") is not None:
                ast = get_ann(expr, "eval")
            else:
                ast = esprima.parse(target.val, options={ 'range': True})
                set_ann(expr, "eval", ast) 
            print(get_ann(expr, "eval") is None)
            i = Interpreter(ast, target.val, True)
            i.run(state)
            #print(ast)
            return state.value
        else:
            return target

    init_duktape_binding()    

    auto_binops = ["+", "-", "*", "/", "%", ">", "<", ">=", "<=", "==", "!=", "===", "!==", "^", "|", "&", "<<", ">>"]
    binop_to_fn = {}
        
    for i in range(len(auto_binops)):
        fname = "binop_" + str(i)
        binop_to_fn[auto_binops[i]] = fname
        register_function("function " + fname + "(a, b) { return a " + auto_binops[i] + " b }")

    auto_unops = ["+", "-", "!", "~"]
    unop_to_fn = {}

    for i in range(len(auto_unops)):
        fname = "unop_" + str(i)
        unop_to_fn[auto_unops[i]] = fname
        register_function("function " + fname + "(a) { return " + auto_unops[i] + " a }")

    def unary_handler(opname, state, abs_arg):
        if abs_arg is JSTop:
            return JSTop        
        if isinstance(abs_arg, JSRef):
            #operators converting its arguments to string
            if opname == "+" or opname == "-" or opname == "~":
                abs_arg = any_to_string(state, abs_arg)

            #operators converting its arguments to boolean
            elif opname == "!":
                abs_arg = any_to_boolean(state, abs_arg)
            elif opname == "typeof":
                target = state.objs[abs_arg.target()]
                if target.is_function() or target.is_simfct():
                    return JSPrimitive("function")
                else:
                    return JSPrimitive("object")
        
        if opname in auto_unops:
            return call_function(unop_to_fn[opname], [abs_arg])
        return JSTop
    
    def binary_handler(opname, state, abs_arg1, abs_arg2):
        if abs_arg1 is JSTop or abs_arg2 is JSTop:
            return JSTop
        
        if isinstance(abs_arg1, JSRef) or isinstance(abs_arg2, JSRef):
            #special cases
            if opname == "instanceof":
                if isinstance(abs_arg2, JSRef) and abs_arg2.target() == function_ref and isinstance(abs_arg1, JSRef) and state.objs[abs_arg1.target()].is_callable():
                    return JSPrimitive(True)
                return JSTop
            
            if opname == "===":
                if type(abs_arg1) != type(abs_arg2):
                    return JSPrimitive(False)
                return JSPrimitive(abs_arg1.ref() == abs_arg2.ref())

            #operators converting objects to string
            if opname == "|" or opname == "&" or opname == "^" or opname == "+" or opname == "==" or opname == "-" or opname == "/" or opname == "*" or opname == "/" or opname == ">" or opname == "<" or opname == ">=" or opname == "<=":
                if isinstance(abs_arg1, JSRef):
                    abs_arg1 = any_to_string(state, abs_arg1)
                if isinstance(abs_arg2, JSRef):
                    abs_arg1 = any_to_string(state, abs_arg2)      

            #operators converting objects to booleans
            if opname == "||" or opname == "&&":
                if isinstance(abs_arg1, JSRef):
                    abs_arg1 = any_to_boolean(state, abs_arg1)
                if isinstance(abs_arg2, JSRef):
                    abs_arg1 = any_to_boolean(state, abs_arg2)                  
                        
        if opname in auto_binops:
            return call_function(binop_to_fn[opname], [abs_arg1, abs_arg2])
        else:
            return JSTop

    register_update_handler(update_handler)
    register_unary_handler(lift_or(unary_handler))
    register_binary_handler(lift_or(binary_handler))

    string_fromcharcode_ref = register_preexisting_object(JSObject.simfct(string_fromcharcode, True))
    string_ref = register_preexisting_object(JSObject({"fromCharCode": JSRef(string_fromcharcode_ref)}))
    register_global_symbol('String', JSRef(string_ref))

    ___display_ref = register_preexisting_object(JSObject.simfct(___display));
    register_global_symbol('___display', JSRef(___display_ref))

    ___state_ref = register_preexisting_object(JSObject.simfct(___state));
    register_global_symbol('___state', JSRef(___state_ref))

    parse_int_ref = register_preexisting_object(JSObject.simfct(parse_int, True));
    register_global_symbol('parseInt', JSRef(parse_int_ref))

    ___assert_ref = register_preexisting_object(JSObject.simfct(___assert));
    register_global_symbol('___assert', JSRef(___assert_ref))

    ___is_concretizable_ref = register_preexisting_object(JSObject.simfct(___is_concretizable, True));
    register_global_symbol('___is_concretizable', JSRef(___is_concretizable_ref))

    array_pop_ref = register_preexisting_object(JSObject.simfct(array_pop));
    array_push_ref = register_preexisting_object(JSObject.simfct(array_push));
    array_shift_ref = register_preexisting_object(JSObject.simfct(array_shift));
    array_indexof_ref = register_preexisting_object(JSObject.simfct(array_indexof, True));
    array_reverse_ref = register_preexisting_object(JSObject.simfct(array_reverse));
    array_join_ref = register_preexisting_object(JSObject.simfct(array_join))

    string_split_ref = register_preexisting_object(JSObject.simfct(string_split, True))
    string_charcodeat_ref = register_preexisting_object(JSObject.simfct(string_charcodeat, True))
    string_charat_ref = register_preexisting_object(JSObject.simfct(string_charat, True))
    string_slice_ref = register_preexisting_object(JSObject.simfct(string_slice, True))
    string_substr_ref = register_preexisting_object(JSObject.simfct(string_substr, True))
    string_substring_ref = register_preexisting_object(JSObject.simfct(string_substring, True))
    string_replace_ref = register_preexisting_object(JSObject.simfct(string_replace, True))

    register_method_hook(array_hook)
    register_method_hook(string_hook)
    register_method_hook(function_hook)

    atob_ref = register_preexisting_object(JSObject.simfct(atob, True))
    register_global_symbol('atob', JSRef(atob_ref))

    btoa_ref = register_preexisting_object(JSObject.simfct(btoa, True))
    register_global_symbol('btoa', JSRef(btoa_ref))

    decode_uri_component_ref = register_preexisting_object(JSObject.simfct(decode_uri_component, True))
    decode_uri_ref = register_preexisting_object(JSObject.simfct(decode_uri, True))

    register_global_symbol('decodeURIComponent', JSRef(decode_uri_component_ref))
    register_global_symbol('decodeURI', JSRef(decode_uri_ref))
    register_global_symbol('unescape', JSRef(decode_uri_component_ref))

    function_ref = register_preexisting_object(JSObject({}))
    register_global_symbol('Function', JSRef(function_ref))

    fn_cons_ref = register_preexisting_object(JSObject.simfct(fn_cons, True))
    number_obj = JSObject.simfct(parse_int, True)
    number_obj.properties["constructor"] = JSRef(fn_cons_ref)
    number_ref = register_preexisting_object(number_obj)
    register_global_symbol('Number', JSRef(number_ref))

    round_ref = register_preexisting_object(JSObject.simfct(math_round, True))
    math_ref = register_preexisting_object(JSObject({"round": JSRef(round_ref)}))
    register_global_symbol('Math', JSRef(math_ref))

    regexp_ref = register_preexisting_object(JSObject.simfct(regexp, True))
    register_global_symbol("RegExp", JSRef(regexp_ref))

    eval_obj = register_preexisting_object(JSObject.simfct(eval_fct))
    register_global_symbol("eval", JSRef(eval_obj))


