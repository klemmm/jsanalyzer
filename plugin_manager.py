import abstract
import config

JSTop = abstract.JSTop
JSUndefNaN = abstract.JSUndefNaN
JSPrimitive = abstract.JSPrimitive
JSClosure = abstract.JSClosure
JSSimFct = abstract.JSSimFct
JSObject = abstract.JSObject
JSRef = abstract.JSRef

ref_id = 0
binary_handlers = []
global_symbols = []
preexisting_objects = []

def handle_binary_operation(opname, arg1, arg2):
    r = JSTop
    for f in binary_handlers:
        r = f(opname, arg1, arg2)
        if r is not JSTop:
            break
    return r

def register_preexisting_object(obj):
    global ref_id
    preexisting_objects.append((ref_id, obj))
    ref_id = ref_id + 1
    return ref_id - 1

def register_binary_handler(h):
    binary_handlers.append(h)

def register_global_symbol(name, value):
    global_symbols.append((name, value))

def register_method_hook(hook):
    JSObject.add_hook(hook)

for p in config.enabled_plugins:
    __import__("plugins." + p)
