from plugin_manager import register_preexisting_object, register_binary_handler, register_global_symbol, register_method_hook, JSTop, JSUndefNaN, JSPrimitive, JSObject, JSSimFct, JSRef

def binary_handler(opname, abs_arg1, abs_arg2):
    if abs_arg1 is JSUndefNaN or abs_arg2 is JSUndefNaN:
        return JSUndefNaN
    
    if isinstance(abs_arg1, JSPrimitive) and isinstance(abs_arg2, JSPrimitive):
        arg1 = abs_arg1.val
        arg2 = abs_arg2.val

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
        else:
            return JSTop
        return JSPrimitive(r)
    else:
        return JSTop

register_binary_handler(binary_handler)

def console_log(*args):
    print("console log:", list(args))

console_ref = register_preexisting_object(JSObject({"log": JSSimFct(console_log)}))
register_global_symbol('console', JSRef(console_ref))

def array_hook(name, arr):
    def array_pop(arr):
        #FIXME array object should track its abstract size
        indexes = sorted([i for i in arr.properties if type(i) is int])
        retval = arr.properties[indexes[-1]]
        del arr.properties[indexes[-1]]
        return retval
    
    def array_push(arr, value):
        #FIXME array object should track its abstract size
        indexes = sorted([i for i in arr.properties if type(i) is int])
        retval = arr.properties[indexes[-1]]
        arr.properties[indexes[-1] + 1] = value
        return retval
    
    def array_shift(arr):
        #FIXME array object should track its abstract size
        indexes = sorted([i for i in arr.properties if type(i) is int])
        retval = JSTop
        if 0 in indexes:
            retval = arr.properties[0]
            del arr.properties[0]
            del indexes[0]

        for i in indexes:
            arr.properties[i - 1] = arr.properties[i]
            del arr.properties[i]

        return retval

    if name == "pop":
        return JSSimFct(array_pop)
    elif name == "shift":
        return JSSimFct(array_shift)
    elif name == "push":
        return JSSimFct(array_push)
    else:
        return JSTop

register_method_hook(array_hook)

