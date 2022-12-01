import re
import config
import base64
import urllib.parse

from plugin_manager import register_preexisting_object, register_update_handler, register_unary_handler, register_binary_handler, register_global_symbol, register_method_hook, JSTop, JSUndefNaN, JSPrimitive, JSObject, JSRef, to_bool, State, Data, JSBot, JSSpecial, MissingMode, lift_top, lift_or, JSOr

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
    elif opname == "~":
        if isinstance(abs_arg, JSPrimitive):
            if type(abs_arg.val) is int or type(abs_arg.val) is float:
                return JSPrimitive(~abs_arg.val)
            elif type(abs_arg.val) is str:
                return JSPrimitive(~interpret_as_number(state, abs_arg))
            else:
                return JSUndefNaN
        elif abs_arg is JSUndefNaN:
            return JSUndefNaN
        else:
            return JSTop
    elif opname == "-":
        if isinstance(abs_arg, JSPrimitive):
            if type(abs_arg.val) is int or type(abs_arg.val) is float:
                return JSPrimitive(-abs_arg.val)
            elif type(abs_arg.val) is str:
                return JSPrimitive(-interpret_as_number(state, abs_arg))
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
    if opname == "instanceof":
        if isinstance(abs_arg2, JSRef) and abs_arg2.target() == function_ref and isinstance(abs_arg1, JSRef) and state.objs[abs_arg1.target()].is_callable():
            return JSPrimitive(True)
        else:
            return JSTop
    
#    if opname == "===" and abs_arg1 is JSTop and abs_arg2 is JSUndefNaN or abs_arg1 is JSUndefNaN and abs_arg2 is JSTop:
#        return JSPrimitive(True) #hack pour faire marcher le truc d'incapsula

    if abs_arg1 is JSTop or abs_arg2 is JSTop:
        return JSTop

    if abs_arg1 is JSBot or abs_arg2 is JSBot:
        return JSBot

    if opname == "===":
        if type(abs_arg1) != type(abs_arg2):
            return JSPrimitive(False)
        return JSPrimitive(abs_arg1 == abs_arg2) #TODO actually incorrect if test is undefined === NaN
    
    if opname == "!==":
        if type(abs_arg1) != type(abs_arg2):
            return JSPrimitive(True)
        return JSPrimitive(abs_arg1 != abs_arg2) #TODO actually incorrect if test is undefined === NaN
    
    if (opname == "===" or opname == "==") and (abs_arg1 is JSUndefNaN or abs_arg2 is JSUndefNaN): #TODO incorrect if test is undefined == undefined
        return JSPrimitive(type(abs_arg1) == type(abs_arg2))
    
    if opname == "+":
        if abs_arg1 is JSUndefNaN:
            abs_arg1 = JSPrimitive("undefined")
        
        if abs_arg2 is JSUndefNaN:
            abs_arg2 = JSPrimitive("undefined")
    if (abs_arg1 is JSUndefNaN or abs_arg2 is JSUndefNaN): #TODO incorrect if test is undefined == undefined
        return JSUndefNaN

    if opname == "+":
        if isinstance(abs_arg1, JSRef) and state.objs[abs_arg1.target()].is_function() and isinstance(abs_arg2, JSPrimitive) and type(abs_arg2.val) is str:
            return JSPrimitive(Data.source[state.objs[abs_arg1.target()].range[0]:state.objs[abs_arg1.target()].range[1]] + abs_arg2.val)
        
        if isinstance(abs_arg2, JSRef) and state.objs[abs_arg2.target()].is_function() and isinstance(abs_arg1, JSPrimitive) and type(abs_arg1.val) is str:
            return JSPrimitive(abs_arg1.val + Data.source[state.objs[abs_arg2.target()].range[0]:state.objs[abs_arg2.target()].range[1]])
        
    if isinstance(abs_arg1, JSRef):
        abs_arg1 = JSPrimitive("[object Object]")
    
    if isinstance(abs_arg2, JSRef):
        abs_arg2 = JSPrimitive("[object Object]")
   

    if isinstance(abs_arg1, JSPrimitive) and isinstance(abs_arg2, JSPrimitive):
        arg1 = abs_arg1.val
        arg2 = abs_arg2.val
       
        if opname == "+":
            if type(arg1) is float and float.is_integer(arg1):
                arg1 = int(arg1)
            
            if type(arg2) is float and float.is_integer(arg2):
                arg2 = int(arg2)

            if (type(arg1) is int or type(arg1) is float or type(arg1) is bool) and type(arg2) is str:
                arg1 = str(arg1)
            if type(arg1) is str and (type(arg2) is int or type(arg2) is float or type(arg2) is bool):
                arg2 = str(arg2)

        if opname == "^":
            if type(arg1) is float:
                arg1 = int(arg1)
            if type(arg2) is float:
                arg2 = int(arg2)

        if opname == "-" or opname == "/" or opname == "*" or opname == "&" or opname == "|" or opname == ">>" or opname == "<" :
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
        if (opname == "==" or opname == "===") and (type(arg1) is re.Pattern or type(arg2) is re.Pattern):
            return JSPrimitive(False) #TODO not always correct
        
        if (opname == "!=" or opname == "!==") and (type(arg1) is re.Pattern or type(arg2) is re.Pattern):
            return JSPrimitive(True) #TODO not always correct


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
            if arg2 == 0:
                return JSUndefNaN
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
        elif opname == "!=":
            r = not (arg1 == arg2)
        elif opname == "^":
            r = arg1 ^ arg2
        elif opname == "&":
            r = arg1 & arg2
        elif opname == "|":
            r = arg1 | arg2
        elif opname == "<<":
            r = arg1 << arg2
        elif opname == ">>":
            r = arg1 >> arg2
        else:
            #print("Unknown binary operation: ", opname)
            return JSTop
        return JSPrimitive(r)
    else:
        print("Failed to handle binary operation: ", opname)
        return JSTop

register_binary_handler(lift_or(binary_handler))

def ___display(state, expr, *args):
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
    return JSUndefNaN


def string_fromcharcode(state, expr, obj, code):
    if code is JSTop or isinstance(code, JSOr):
        return JSTop

    return JSPrimitive(chr(interpret_as_number(state, code)))
    return JSTop

string_fromcharcode_ref = register_preexisting_object(JSObject.simfct(string_fromcharcode))
string_ref = register_preexisting_object(JSObject({"fromCharCode": JSRef(string_fromcharcode_ref)}))
register_global_symbol('String', JSRef(string_ref))

___display_ref = register_preexisting_object(JSObject.simfct(___display));
register_global_symbol('___display', JSRef(___display_ref))

def ___state(state, expr, *args):
    print("___state:", state)
    return JSTop

___state_ref = register_preexisting_object(JSObject.simfct(___state));
register_global_symbol('___state', JSRef(___state_ref))

def parse_int(state, expr, s, base=JSPrimitive(10)):
    if s is JSUndefNaN:
        return JSUndefNaN
    if isinstance(s, JSPrimitive) and type(s.val) is int:
        s = JSPrimitive(str(s.val))
    if isinstance(s, JSPrimitive) and type(s.val) is str and isinstance(base, JSPrimitive) and type(base.val) is int:
        if base.val > 36:
            return JSUndefNaN
        alpha = ''
        if base.val > 10:
            alpha = 'a-' + chr(ord('a') + base.val - 11)
        prefix = re.sub('[^0-9' + alpha + '].*', '', s.val.lower())
        if prefix == "":
            return JSUndefNaN
        else:
            return JSPrimitive(int(prefix, base.val))
    return JSTop

parse_int_ref = register_preexisting_object(JSObject.simfct(parse_int));
register_global_symbol('parseInt', JSRef(parse_int_ref))

def ___assert(state, expr, b):
    if (isinstance(b, JSPrimitive) or isinstance(b, JSRef)) and to_bool(b):
        return
    raise AssertionError("Analyzer assertion failed: " + str(b))

___assert_ref = register_preexisting_object(JSObject.simfct(___assert));
register_global_symbol('___assert', JSRef(___assert_ref))

def ___is_concretizable(state, expr, b):
    return JSPrimitive(b is not JSTop)

___is_concretizable_ref = register_preexisting_object(JSObject.simfct(___is_concretizable));
register_global_symbol('___is_concretizable', JSRef(___is_concretizable_ref))

def array_indexof(state, expr, arr, item, start=JSPrimitive(0)):
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
        return JSPrimitive(-1)
    elif hasattr(arr, 'val') and type(arr.val) is str:
        return JSPrimitive(arr.val.find(item.val, start.val))
    else:
        raise NameError('Invalid Javascript')

def array_reverse(state, expr, arr):
    if arr is JSTop:
        return JSTop
    obj_id = State.new_id()
    d = dict()
    l = len(arr.properties)
    for key,values in arr.properties.items():
        d[l - key - 1] = values
    state.objs[obj_id] = JSObject(d)
    return JSRef(obj_id)

 
def array_pop(state, expr, arr):
    if arr is JSTop:
        return JSTop
    if arr.tablength is None:
        arr.properties.clear()
        arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
        return JSTop
    if arr.tablength == 0:
        return JSUndefNaN
    value = arr.properties[arr.tablength - 1]
    del arr.properties[arr.tablength - 1]
    arr.tablength -= 1
    return value

def array_push(state, expr, arr, value):
    if arr is JSTop:
        return JSTop
    if arr.tablength is None:
        arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
        return JSTop
    arr.properties[arr.tablength] = value
    arr.tablength += 1
    return JSPrimitive(arr.tablength)

def array_shift(state, expr, arr):
    if arr is JSTop:
        return JSTop
    if arr.tablength is None:
        arr.properties.clear()
        arr.set_missing_mode(MissingMode.MISSING_IS_TOP) #TODO could improve precision
    if arr.tablength == 0:
        return JSUndefNaN
    indexes = sorted([i for i in arr.properties if type(i) is int])
    if 0 in indexes:
        retval = arr.properties[0]
        del arr.properties[0]
        del indexes[0]
        arr.tablength -= 1
    else:
        retval = JSUndefNaN
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

array_pop_ref = register_preexisting_object(JSObject.simfct(array_pop));
array_push_ref = register_preexisting_object(JSObject.simfct(array_push));
array_shift_ref = register_preexisting_object(JSObject.simfct(array_shift));
array_indexof_ref = register_preexisting_object(JSObject.simfct(array_indexof));
array_reverse_ref = register_preexisting_object(JSObject.simfct(array_reverse));
array_join_ref = register_preexisting_object(JSObject.simfct(array_join))

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

def string_split(state, expr, string, separator=None):
    if separator is None:
        return string
    if isinstance(string, JSPrimitive) and isinstance(separator, JSPrimitive) and type(string.val) is str and type(separator.val) is str:
        if separator.val == "":
            result = [*string.val]
        else:
            result = string.val.split(separator.val)
        obj_id = State.new_id()
        state.objs[obj_id] = JSObject(dict(enumerate([JSPrimitive(r) for r in result])))
        state.objs[obj_id].tablength = len(state.objs[obj_id].properties)
        return JSRef(obj_id)
    return JSTop

def interpret_as_number(state, value):
    if isinstance(value, JSPrimitive):
        if type(value.val) is int:
            return value.val
        elif type(value.val) is str:
            try:
                if value.val[0:2] == '0x':
                    return int(value.val, 16)
                else:
                    return int(value.val)
            except ValueError:
                return 0
        elif value.val is None:
            return None
        elif type(value.val) is bool:
            if value.val:
                return 1
            else:
                return 0
        else:
            raise ValueError("interpret_as_number: unhandled value " + repr(value))
    elif isinstance(value, JSRef):
        obj = state.objs[value.target()]
        if len(obj.properties) == 1 and 0 in obj.properties:
            return interpret_as_number(state, obj.properties[0])
        else:
            return 0
    elif value is JSUndefNaN:
        return 0
    else:
        raise ValueError("interpret_as_number: invalid value: " + str(value))

def string_charcodeat(state, expr, string, position):
    if not (isinstance(string, JSPrimitive) and type(string.val) is str):
        return JSTop
    if position is JSTop:
        return JSTop
    pos = interpret_as_number(state, position)
    if pos < 0 or pos >= len(string.val):
        return JSUndefNaN
    return JSPrimitive(ord(string.val[pos]))

def string_charat(state, expr, string, position):
    if not (isinstance(string, JSPrimitive) and type(string.val) is str):
        return JSTop
    if position is JSTop:
        return JSTop
    pos = interpret_as_number(state, position)
    if pos < 0 or pos >= len(string.val):
        return JSUndefNaN
    return JSPrimitive(string.val[pos])

def string_substr(state, expr, string, start=JSPrimitive(0), length=JSPrimitive(None)):
    if not (isinstance(string, JSPrimitive) and type(string.val) is str):
        return JSTop
    if start is JSTop:
        return JSTop
    if length is JSTop:
        return JSTop
    sta = interpret_as_number(state, start)
    leng = interpret_as_number(state, length)
    if sta < 0:
        return JSUndefNaN
    if leng is None:
        return JSPrimitive(string.val[sta:])
    else:
        if sta + leng > len(string.val):
            return JSUndefNaN
        else:
            return JSPrimitive(string.val[sta:sta + leng])

def string_substring(state, expr, string, start=JSPrimitive(0), end=JSPrimitive(None)):
    if not (isinstance(string, JSPrimitive) and type(string.val) is str):
        return JSTop
    if start is JSTop:
        return JSTop
    if end is JSTop:
        return JSTop
    sta = interpret_as_number(state, start)
    end = interpret_as_number(state, end)
    if sta < 0:
        return JSUndefNaN
    if end is None:
        return JSPrimitive(string.val[sta:])
    else:
        if end > len(string.val):
            return JSUndefNaN
        else:
            return JSPrimitive(string.val[sta:end])

def string_replace(state, expr, string, pattern, replacement):
    if string is JSTop or pattern is JSTop or replacement is JSTop:
        return JSTop
    if type(pattern.val) is re.Pattern:
        return JSPrimitive(re.sub(pattern.val, replacement.val, string.val))
    else:
        return JSPrimitive(string.val.replace(pattern.val, replacement.val, 1))

def string_slice(state, expr, string, begin=JSPrimitive(0), end=JSPrimitive(None)):
    if isinstance(string, JSPrimitive) and type(string.val) is str and isinstance(begin, JSPrimitive) and type(begin.val) is int and isinstance(end, JSPrimitive) and (type(end.val) is int or end.val is None):
        return JSPrimitive(string.val[begin.val:end.val])
    else:
        #print("slice: unhandled argument: ", string, " begin: ", begin, "end: ", end)
        return JSTop



string_split_ref = register_preexisting_object(JSObject.simfct(string_split))
string_charcodeat_ref = register_preexisting_object(JSObject.simfct(string_charcodeat))
string_charat_ref = register_preexisting_object(JSObject.simfct(string_charat))
string_slice_ref = register_preexisting_object(JSObject.simfct(string_slice))
string_substr_ref = register_preexisting_object(JSObject.simfct(string_substr))
string_substring_ref = register_preexisting_object(JSObject.simfct(string_substring))
string_replace_ref = register_preexisting_object(JSObject.simfct(string_replace))

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

def function_or_int_tostring(state, expr, fn_or_int, base=JSPrimitive(10)):
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

def atob(state, expr, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        return JSPrimitive(base64.b64decode(string.val).decode("latin-1"))
    return JSTop

atob_ref = register_preexisting_object(JSObject.simfct(atob))
register_global_symbol('atob', JSRef(atob_ref))

def btoa(state, expr, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        return JSPrimitive(base64.b64encode(str.encode(string.val)))
    return JSTop

btoa_ref = register_preexisting_object(JSObject.simfct(btoa))
register_global_symbol('btoa', JSRef(btoa_ref))

def decode_uri_component(state, expr, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        return JSPrimitive(urllib.parse.unquote(string.val))
    return JSTop

def decode_uri(state, expr, string):
    subst = [("%00", "\x00"),("%01", "\x01"),("%02", "\x02"),("%03", "\x03"),("%04", "\x04"),("%05", "\x05"),("%06", "\x06"),("%07", "\x07"),("%08", "\x08"),("%09", "\x09"),("%0A", "\x0a"),("%0B", "\x0b"),("%0C", "\x0c"),("%0D", "\x0d"),("%0E", "\x0e"),("%0F", "\x0f"),("%10", "\x10"),("%11", "\x11"),("%12", "\x12"),("%13", "\x13"),("%14", "\x14"),("%15", "\x15"),("%16", "\x16"),("%17", "\x17"),("%18", "\x18"),("%19", "\x19"),("%1A", "\x1a"),("%1B", "\x1b"),("%1C", "\x1c"),("%1D", "\x1d"),("%1E", "\x1e"),("%1F", "\x1f"),("%20", "\x20"),("%22", "\x22"),("%25", "\x25"),("%3C", "\x3c"),("%3E", "\x3e"),("%5B", "\x5b"),("%5C", "\x5c"),("%5D", "\x5d"),("%5E", "\x5e"),("%60", "\x60"),("%7B", "\x7b"),("%7C", "\x7c"),("%7D", "\x7d"),("%7F", "\x7f"),("%C2%80", "\x80"),("%C2%81", "\x81"),("%C2%82", "\x82"),("%C2%83", "\x83"),("%C2%84", "\x84"),("%C2%85", "\x85"),("%C2%86", "\x86"),("%C2%87", "\x87"),("%C2%88", "\x88"),("%C2%89", "\x89"),("%C2%8A", "\x8a"),("%C2%8B", "\x8b"),("%C2%8C", "\x8c"),("%C2%8D", "\x8d"),("%C2%8E", "\x8e"),("%C2%8F", "\x8f"),("%C2%90", "\x90"),("%C2%91", "\x91"),("%C2%92", "\x92"),("%C2%93", "\x93"),("%C2%94", "\x94"),("%C2%95", "\x95"),("%C2%96", "\x96"),("%C2%97", "\x97"),("%C2%98", "\x98"),("%C2%99", "\x99"),("%C2%9A", "\x9a"),("%C2%9B", "\x9b"),("%C2%9C", "\x9c"),("%C2%9D", "\x9d"),("%C2%9E", "\x9e"),("%C2%9F", "\x9f"),("%C2%A0", "\xa0"),("%C2%A1", "\xa1"),("%C2%A2", "\xa2"),("%C2%A3", "\xa3"),("%C2%A4", "\xa4"),("%C2%A5", "\xa5"),("%C2%A6", "\xa6"),("%C2%A7", "\xa7"),("%C2%A8", "\xa8"),("%C2%A9", "\xa9"),("%C2%AA", "\xaa"),("%C2%AB", "\xab"),("%C2%AC", "\xac"),("%C2%AD", "\xad"),("%C2%AE", "\xae"),("%C2%AF", "\xaf"),("%C2%B0", "\xb0"),("%C2%B1", "\xb1"),("%C2%B2", "\xb2"),("%C2%B3", "\xb3"),("%C2%B4", "\xb4"),("%C2%B5", "\xb5"),("%C2%B6", "\xb6"),("%C2%B7", "\xb7"),("%C2%B8", "\xb8"),("%C2%B9", "\xb9"),("%C2%BA", "\xba"),("%C2%BB", "\xbb"),("%C2%BC", "\xbc"),("%C2%BD", "\xbd"),("%C2%BE", "\xbe"),("%C2%BF", "\xbf"),("%C3%80", "\xc0"),("%C3%81", "\xc1"),("%C3%82", "\xc2"),("%C3%83", "\xc3"),("%C3%84", "\xc4"),("%C3%85", "\xc5"),("%C3%86", "\xc6"),("%C3%87", "\xc7"),("%C3%88", "\xc8"),("%C3%89", "\xc9"),("%C3%8A", "\xca"),("%C3%8B", "\xcb"),("%C3%8C", "\xcc"),("%C3%8D", "\xcd"),("%C3%8E", "\xce"),("%C3%8F", "\xcf"),("%C3%90", "\xd0"),("%C3%91", "\xd1"),("%C3%92", "\xd2"),("%C3%93", "\xd3"),("%C3%94", "\xd4"),("%C3%95", "\xd5"),("%C3%96", "\xd6"),("%C3%97", "\xd7"),("%C3%98", "\xd8"),("%C3%99", "\xd9"),("%C3%9A", "\xda"),("%C3%9B", "\xdb"),("%C3%9C", "\xdc"),("%C3%9D", "\xdd"),("%C3%9E", "\xde"),("%C3%9F", "\xdf"),("%C3%A0", "\xe0"),("%C3%A1", "\xe1"),("%C3%A2", "\xe2"),("%C3%A3", "\xe3"),("%C3%A4", "\xe4"),("%C3%A5", "\xe5"),("%C3%A6", "\xe6"),("%C3%A7", "\xe7"),("%C3%A8", "\xe8"),("%C3%A9", "\xe9"),("%C3%AA", "\xea"),("%C3%AB", "\xeb"),("%C3%AC", "\xec"),("%C3%AD", "\xed"),("%C3%AE", "\xee"),("%C3%AF", "\xef"),("%C3%B0", "\xf0"),("%C3%B1", "\xf1"),("%C3%B2", "\xf2"),("%C3%B3", "\xf3"),("%C3%B4", "\xf4"),("%C3%B5", "\xf5"),("%C3%B6", "\xf6"),("%C3%B7", "\xf7"),("%C3%B8", "\xf8"),("%C3%B9", "\xf9"),("%C3%BA", "\xfa"),("%C3%BB", "\xfb"),("%C3%BC", "\xfc"),("%C3%BD", "\xfd"),("%C3%BE", "\xfe")]
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        txt = string.val
        for (k, v) in subst:
            txt = txt.replace(k, v)
        return JSPrimitive(txt)
    else:
        return JSTop

decode_uri_component_ref = register_preexisting_object(JSObject.simfct(decode_uri_component))
decode_uri_ref = register_preexisting_object(JSObject.simfct(decode_uri))
register_global_symbol('decodeURIComponent', JSRef(decode_uri_component_ref))
register_global_symbol('decodeURI', JSRef(decode_uri_ref))
register_global_symbol('unescape', JSRef(decode_uri_component_ref))

function_ref = register_preexisting_object(JSObject({}))
register_global_symbol('Function', JSRef(function_ref))

number_ref = register_preexisting_object(JSObject.simfct(parse_int))
register_global_symbol('Number', JSRef(number_ref))

def math_round(state, expr, this, number):
    if isinstance(number, JSPrimitive) and type(number.val) is float:
        return JSPrimitive(round(number.val))
    return JSTop

round_ref = register_preexisting_object(JSObject.simfct(math_round))
math_ref = register_preexisting_object(JSObject({"round": JSRef(round_ref)}))
register_global_symbol('Math', JSRef(math_ref))

def regexp_match(state, expr, this, target):
    return JSPrimitive(this.properties["regexp"].val.match(target.val) is not None)

def regexp(state, expr, this, string):
    if isinstance(string, JSPrimitive) and type(string.val) is str:
        this.properties["regexp"] = JSPrimitive(re.compile(string.val))
        test_id = State.new_id()
        state.objs[test_id] = JSObject.simfct(regexp_match)
        this.properties["test"] = JSRef(test_id)
    else:
        this.set_missing_mode(MissingMode.MISSING_IS_TOP)
        this.properties.clear()
    return JSUndefNaN

regexp_ref = register_preexisting_object(JSObject.simfct(regexp))
register_global_symbol("RegExp", JSRef(regexp_ref))
