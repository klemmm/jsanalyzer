import abstract
import config

JSOr = abstract.JSOr
JSBot = abstract.JSBot
JSTop = abstract.JSTop
JSUndefNaN = abstract.JSUndefNaN
JSPrimitive = abstract.JSPrimitive
JSObject = abstract.JSObject
JSRef = abstract.JSRef
State = abstract.State
JSSpecial = abstract.JSSpecial
MissingMode = abstract.MissingMode

ref_id = 1 # id 0 is reserved for global scope
binary_handlers = []
update_handlers = []
unary_handlers = []
global_symbols = []
preexisting_objects = []


class Data(object):
    source = "" 

def set_source(_source):
    Data.source = _source

def to_bool(v):
    if v is JSUndefNaN:
        return False

    if isinstance(v, JSPrimitive):
        if type(v.val) is int:
            return v.val != 0
        elif type(v.val) is bool:
            return v.val
        elif type(v.val) is str:
            if v.val == "<<NULL>>":
                return 0
            return len(v.val) > 0
        else:
            raise ValueError("truth_value: unhandled concrete type" + str(type(v.val)))
    elif isinstance(v, JSRef):
        return True
    else:
        raise ValueError("truth_value: unhandled abstract type" + str(type(v)) + "(value: " + str(v) + ")")

def handle_binary_operation(opname, state, arg1, arg2):
    r = JSTop
    for f in binary_handlers:
        r = f(opname, state, arg1, arg2)
        if r is not JSTop:
            break
    return r

def handle_update_operation(opname, state, arg):
    r = JSTop
    for f in update_handlers:
        r = f(opname, state, arg)
        if r is not JSTop:
            break
    return r

def handle_unary_operation(opname, state, arg):
    r = JSTop
    for f in unary_handlers:
        r = f(opname, state, arg)
        if r is not JSTop:
            break
    return r

def register_preexisting_object(obj):
    global ref_id
    preexisting_objects.append((ref_id, obj))
    ref_id = ref_id + 1
    return ref_id - 1

def register_update_handler(h):
    update_handlers.append(h)

def register_binary_handler(h):
    binary_handlers.append(h)

def register_unary_handler(h):
    unary_handlers.append(h)

def register_global_symbol(name, value):
    global_symbols.append((name, value))

def register_method_hook(hook):
    JSObject.add_hook(hook)

def lift_top(f):
    def f2(*args):
        for l in args:
            if l is JSTop:
                return JSTop
        return f(*args)
    return f2

def lift_or(f):
    def f2(*args):
        or_pos = None
        i = 0
        for l in args:
            if isinstance(l, JSOr):
                or_pos = i
                break
            i += 1
        if or_pos is None:
            return f(*args)
        else:
            l = [*args]
            results = set()
            for c in l[or_pos].choices:
                k = l[0:or_pos] + [c] + l[or_pos + 1:]
                r = f2(*k)
                if isinstance(r, JSOr):
                    results = results.union(r.choices)
                else:
                    results.add(r)
            if abstract.State.keep_or(results):
                if len(results) == 1:
                    return results.pop()
                return JSOr(results)
            else:
                return JSTop
    return f2

abs_to_bool = lift_or(lift_top(to_bool))

for p in config.enabled_plugins:
    __import__("plugins." + p)
