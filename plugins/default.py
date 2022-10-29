import re
import config

from plugin_manager import register_preexisting_object, register_unary_handler, register_binary_handler, register_global_symbol, register_method_hook, JSTop, JSUndefNaN, JSPrimitive, JSObject, JSRef, to_bool


def unary_handler(opname, abs_arg):
    if abs_arg is JSUndefNaN:
        return JSUndefNaN

    if opname == '!' and abs_arg is not JSTop:
        return JSPrimitive(not to_bool(abs_arg))

    if isinstance(abs_arg, JSPrimitive):
        arg = abs_arg.val

        if opname == '-':
            return JSPrimitive(-arg)
        else:
            return JSTop
    return JSTop

register_unary_handler(unary_handler)

def binary_handler(opname, abs_arg1, abs_arg2):
    if type(abs_arg1) != type(abs_arg2) and opname == "===":
        return JSPrimitive(False)
    if abs_arg1 is JSUndefNaN or abs_arg2 is JSUndefNaN:
        return JSUndefNaN
    
    if isinstance(abs_arg1, JSPrimitive) and isinstance(abs_arg2, JSPrimitive):
        arg1 = abs_arg1.val
        arg2 = abs_arg2.val
       
        if opname == "+":
            if type(arg1) is int and type(arg2) is str:
                arg1 = str(arg1)
            if type(arg1) is str and type(arg2) is int:
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
        elif opname == "===":
            r = arg1 == arg2
        else:
            return JSTop
        return JSPrimitive(r)
    else:
        return JSTop

register_binary_handler(binary_handler)

def console_log(this, *args):
    if config.console_enable:
        print("console log:", list(args))
    return JSUndefNaN

console_log_ref = register_preexisting_object(JSObject.simfct(console_log));
console_ref = register_preexisting_object(JSObject({"log": JSRef(console_log_ref)}))
register_global_symbol('console', JSRef(console_ref))

def parse_int(s):
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
    
def array_pop(arr):
    #FIXME array object should track its abstract size
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if len(indexes) == 0:
        return JSTop
    retval = arr.properties[indexes[-1]]
    del arr.properties[indexes[-1]]
    return retval

def array_push(arr, value):
    #FIXME array object should track its abstract size
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if len(indexes) == 0:
        return JSTop
    retval = arr.properties[indexes[-1]]
    arr.properties[indexes[-1] + 1] = value
    return retval

def array_shift(arr):
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

register_method_hook(array_hook)
