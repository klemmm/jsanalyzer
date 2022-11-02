import re
import config
import base64
import urllib.parse

from plugin_manager import register_preexisting_object, register_update_handler, register_unary_handler, register_binary_handler, register_global_symbol, register_method_hook, JSTop, JSUndefNaN, JSPrimitive, JSObject, JSRef, to_bool, State, Data, JSBot, JSSpecial

def update_handler(opname, state, abs_arg):
    if isinstance(abs_arg, JSPrimitive) and type(abs_arg.val) is int:
        if opname == "++":
            return JSPrimitive(abs_arg.val + 1)
        elif opname == "--":
            return JSPrimitive(abs_arg.val - 1)
        else:
            print("Unknown update operation: ", opname)
            return JSTop
    else:
        return JSTop

register_update_handler(update_handler)

def unary_handler(opname, state, abs_arg):
    if abs_arg is JSTop:
        return JSTop

    if opname == "!":
        return JSPrimitive(not to_bool(abs_arg))
    elif opname == "-":
        if isinstance(abs_arg, JSPrimitive):
            if type(abs_arg.val) is int or type(abs_arg.val) is float:
                return JSPrimitive(-abs_arg.val)
            else:
                return JSUndefNaN
        elif abs_arg is JSUndefNaN:
            return JSUndefNaN
        else:
            return JSTop
    elif opname == "typeof":
        if abs_arg is JSUndefNaN:
            return JSPrimitive("undefined") #TODO
        elif isinstance(abs_arg, JSPrimitive):
            if type(abs_arg.val) is str:
                return JSPrimitive("string")
            elif type(abs_arg.val) is int:
                return JSPrimitive("number")
            else:
                return JSTop
        elif isinstance(abs_arg, JSRef):
            target = state.objs[abs_arg.target()]
            if target.is_function() or target.is_simfct():
                return JSPrimitive("function")
            return JSPrimitive("object")
    else:
        print("Unknown unary operation:", opname)
        return JSTop

register_unary_handler(unary_handler)

def binary_handler(opname, state, abs_arg1, abs_arg2):
    if abs_arg1 is JSTop or abs_arg2 is JSTop:
        return JSTop

    if abs_arg1 is JSBot or abs_arg2 is JSBot:
        return JSBot

    if opname == "===":
        if type(abs_arg1) != type(abs_arg2):
            return JSPrimitive(False)
        return JSPrimitive(abs_arg1 == abs_arg2) #TODO actually incorrect if test is undefined === NaN
    
    if abs_arg1 is JSUndefNaN or abs_arg2 is JSUndefNaN: #TODO incorrect if test is undefined == undefined
        return JSUndefNaN

    if opname == "+":
        if isinstance(abs_arg1, JSRef) and state.objs[abs_arg1.target()].is_function and isinstance(abs_arg2, JSPrimitive) and type(abs_arg2.val) is str:
            return JSPrimitive(Data.source[state.objs[abs_arg1.target()].range[0]:state.objs[abs_arg1.target()].range[1]] + abs_arg2.val)
        
        if isinstance(abs_arg2, JSRef) and state.objs[abs_arg2.target()].is_function() and isinstance(abs_arg1, JSPrimitive) and type(abs_arg1.val) is str:
            return JSPrimitive(abs_arg1.val + Data.source[state.objs[abs_arg2.target()].range[0]:state.objs[abs_arg2.target()].range[1]])

    if isinstance(abs_arg1, JSPrimitive) and isinstance(abs_arg2, JSPrimitive):
        arg1 = abs_arg1.val
        arg2 = abs_arg2.val
       
        if opname == "+":
            if (type(arg1) is int or type(arg1) is float) and type(arg2) is str:
                arg1 = str(arg1)
            if type(arg1) is str and (type(arg2) is int or type(arg2) is float):
                arg2 = str(arg2)

        if opname == "-" or opname == "/" or opname == "*":
            if type(arg1) is str:
                try:
                    arg1 = eval(arg1)
                except NameError:
                    arg1 = JSUndefNaN
            if type(arg2) is str:
                try:
                    arg2 = eval(arg2)
                except NameError:
                    arg2 = JSUndefNaN


        if opname == "+":
            r = arg1 + arg2
        elif opname == "-":
            r = arg1 - arg2
        elif opname == "*":
            r = arg1 * arg2
        elif opname == "/":
            if arg2 == 0:
                return JSUndefNaN
            r = arg1 / arg2
        elif opname == "%":
            r = arg1 % arg2
        elif opname == ">":
            r = arg1 > arg2
        elif opname == "<":
            r = arg1 < arg2
        elif opname == ">=":
            r = arg1 >= arg2
        elif opname == "<=":
            r = arg1 <= arg2
        elif opname == "==":
            r = arg1 == arg2
        elif opname == "^":
            r = arg1 ^ arg2
        else:
            print("Unknown binary operation: ", opname)
            return JSTop
        return JSPrimitive(r)
    else:
        print("Failed to handle binary operation: ", opname)
        return JSTop

register_binary_handler(binary_handler)

def console_log(state, this, *args):
    if config.console_enable:
        print("console log:")
        i = 0
        for a in args:
            print("Arg", i, "type:", type(a), "value:", a, end="")
            if isinstance(a, JSRef):
                print(" target:", state.objs[a.target()])
            elif isinstance(a, JSPrimitive):
                print(" concrete type:", type(a.val))
            else:
                print("")
            i += 1
        print("")
    return JSUndefNaN


def string_fromcharcode(state, obj, code):
    if code is JSTop:
        return JSTop
    if isinstance(code, JSPrimitive) and type(code.val) is int:
        return JSPrimitive(chr(code.val))
    print("warning: fromCharCode: unhandled argument: ", code)
    return JSTop

string_fromcharcode_ref = register_preexisting_object(JSObject.simfct(string_fromcharcode))
string_ref = register_preexisting_object(JSObject({"fromCharCode": JSRef(string_fromcharcode_ref)}))
register_global_symbol('String', JSRef(string_ref))

console_log_ref = register_preexisting_object(JSObject.simfct(console_log));
console_ref = register_preexisting_object(JSObject({"log": JSRef(console_log_ref)}))
register_global_symbol('console', JSRef(console_ref))

def parse_int(state, s):
    if s is JSUndefNaN:
        return JSUndefNaN
    if isinstance(s, JSPrimitive) and type(s.val) is str:
        prefix = re.sub('\D.*', '', s.val)
        if prefix == "":
            return JSUndefNaN
        else:
            return JSPrimitive(int(prefix))
    return JSTop

parse_int_ref = register_preexisting_object(JSObject.simfct(parse_int));
register_global_symbol('parseInt', JSRef(parse_int_ref))

def analyzer_assert(b):
    if (isinstance(b, JSPrimitive) or isinstance(b, JSRef)) and to_bool(b):
        return
    raise AssertionError("Analyzer assertion failed: " + str(b))

analyzer_assert = register_preexisting_object(JSObject.simfct(analyzer_assert));
register_global_symbol('analyzer_assert', JSRef(analyzer_assert))
    
def array_pop(state, arr):
    #FIXME array object should track its abstract size
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if len(indexes) == 0:
        return JSTop
    retval = arr.properties[indexes[-1]]
    del arr.properties[indexes[-1]]
    return retval

def array_push(state, arr, value):
    #FIXME array object should track its abstract size
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if len(indexes) == 0:
        return JSTop
    retval = arr.properties[indexes[-1]]
    arr.properties[indexes[-1] + 1] = value
    return retval

def array_shift(state, arr):
    #FIXME array object should track its abstract size
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if len(indexes) == 0:
        return JSTop
    retval = JSTop
    if 0 in indexes:
        retval = arr.properties[0]
        del arr.properties[0]
        del indexes[0]

    for i in indexes:
        arr.properties[i - 1] = arr.properties[i]
        del arr.properties[i]

    return retval

array_pop_ref = register_preexisting_object(JSObject.simfct(array_pop));
array_push_ref = register_preexisting_object(JSObject.simfct(array_push));
array_shift_ref = register_preexisting_object(JSObject.simfct(array_shift));

def array_hook(name):
    if name == "pop":
        return JSRef(array_pop_ref)
    elif name == "shift":
        return JSRef(array_shift_ref)
    elif name == "push":
        return JSRef(array_push_ref)
    else:
        return JSTop

def string_split(state, string, separator):
    if isinstance(string, JSPrimitive) and isinstance(separator, JSPrimitive) and type(string.val) is str and type(separator.val) is str:
        result = string.val.split(separator.val)
        obj_id = State.new_id()
        state.objs[obj_id] = JSObject(dict(enumerate([JSPrimitive(r) for r in result])))
        return JSRef(obj_id)
    return JSTop

def interpret_as_number(state, value):
    if isinstance(value, JSPrimitive):
        if type(value.val) is int:
            return value.val
        elif type(value.val) is str:
            try:
                return int(value.val)
            except ValueError:
                return 0
    elif isinstance(value, JSRef):
        obj = state.objs[value.target()]
        if len(obj.properties) == 1 and 0 in obj.properties:
            return interpret_as_number(state, obj.properties[0])
        else:
            return 0
    else:
        raise ValueError("interpret_as_number: invalid value" + str(value))

def string_charcodeat(state, string, position):
    if not (isinstance(string, JSPrimitive) and type(string.val) is str):
        return JSTop
    if position is JSTop:
        return JSTop
    pos = interpret_as_number(state, position)
    if pos < 0 or pos >= len(string.val):
        return JSUndefNaN
    return JSPrimitive(ord(string.val[pos]))

def string_slice(state, string, begin=JSPrimitive(0), end=JSPrimitive(None)):
    if isinstance(string, JSPrimitive) and type(string.val) is str and isinstance(begin, JSPrimitive) and type(begin.val) is int and isinstance(end, JSPrimitive) and (type(end.val) is int or end.val is None):
        return JSPrimitive(string.val[begin.val:end.val])
    else:
        print("slice: unhandled argument: ", string, " begin: ", begin, "end: ", end)
        return JSTop


string_split_ref = register_preexisting_object(JSObject.simfct(string_split))
string_charcodeat_ref = register_preexisting_object(JSObject.simfct(string_charcodeat))
string_slice_ref = register_preexisting_object(JSObject.simfct(string_slice))
def string_hook(name):
    if name == "split":
        return JSRef(string_split_ref)
    if name == "charCodeAt":
        return JSRef(string_charcodeat_ref)
    if name == "slice":
        return JSRef(string_slice_ref)
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

def function_or_int_tostring(state, fn_or_int, base=JSPrimitive(10)):
    if isinstance(fn_or_int, JSPrimitive) and type(fn_or_int.val) is int and isinstance(base, JSPrimitive) and type(base.val) is int:
        return JSPrimitive(baseconv(fn_or_int.val, base.val))
    elif fn_or_int.is_function():
        return JSPrimitive(Data.source[fn_or_int.range[0]:fn_or_int.range[1]])
    else:
        print("warning: .toString() unhandled argument: ", fn_or_int, "base:", base)
        return JSTop

function_or_int_tostring_ref = register_preexisting_object(JSObject.simfct(function_or_int_tostring))
def function_hook(name):
    if name == "toString":
        return JSRef(function_or_int_tostring_ref)
    return JSTop

register_method_hook(array_hook)
register_method_hook(string_hook)
register_method_hook(function_hook)


def atob(state, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        return JSPrimitive(base64.b64decode(string.val).decode("latin-1"))
    return JSTop

atob_ref = register_preexisting_object(JSObject.simfct(atob))
register_global_symbol('atob', JSRef(atob_ref))

def decode_uri_component(state, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        return JSPrimitive(urllib.parse.unquote(string.val))
    return JSTop

decode_uri_component_ref = register_preexisting_object(JSObject.simfct(decode_uri_component))
register_global_symbol('decodeURIComponent', JSRef(decode_uri_component_ref))
