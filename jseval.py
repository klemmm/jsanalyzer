"""
Bindings for the duktape library.

This is used by the default plugin when evaluating some JS operators and functions.
"""
from ctypes import *
from abstract import JSPrimitive, JSNull, JSUndef
from typing import List
import sys

class JSCType(object):
    """
    Represents a C enum for describing the type of a JS scalar value
    """
    NUMBER = 0
    STRING = 1
    UNDEFINED = 2
    NUL = 3
    BOOL = 4

class JSCData(Union):
    """
    Represents a C union for storing a JS scalar value
    
    """
    _fields_ = [("s", c_char_p), ("n", c_double), ("b", c_int)]

class JSCPrimitive(Structure):
    """
    Represents a C struct for storing a JS scalar value with its type
    
    """
    _fields_ = [("type", c_int), ("data", JSCData)]

def register_function(d : str):
    """
    Takes the definition (string) of a function and registers it into the duktape engine global symbols

    :param str d: The function definition
    """
    __funcs.register_function(d.encode("utf-8"))

def concretize(a : JSPrimitive) -> JSCPrimitive:
    """
    Convert a JSPrimitive value to a JSCPrimitive value in ordre to use it in duktape to call a JS function

    :param JSPrimitive a: The JSPrimitive value
    :rtype JSCPrimitive:
    :return: The JSCPrimitive value
    """
    if isinstance(a, JSPrimitive):
        if type(a.val) is float:
            r = JSCPrimitive()
            r.type = JSCType.NUMBER
            r.data.n = a.val
            return r
        elif type(a.val) is str:
            r = JSCPrimitive()
            r.type = JSCType.STRING
            r.data.s = a.val.encode("utf-8")
            return r
        elif type(a.val) is bool:
            r = JSCPrimitive()
            r.type = JSCType.BOOL
            r.data.b = a.val
            return r
    elif a == JSUndef:
        r = JSCPrimitive()
        r.type = JSCType.UNDEFINED
        return r
    elif a == JSNull:
        r = JSCPrimitive()
        r.type = JSCType.NUL
        return r
    raise NotImplementedError(type(a), a, a == JSUndef)


def abstract(c : JSCPrimitive) -> JSPrimitive:
    """
    Converts a JSCPrimitive value back to a JSPrimitive value. Used to process return values from JS functions evaluated
    with duktape
    
    :param JSCPrimitive c: The JSCPrimitive value
    :rtype JSPrimitive:
    :return: The JSPrimitive value
    """
    if c.type == JSCType.NUMBER:
        return JSPrimitive(c.data.n)
    elif c.type == JSCType.STRING:
        return JSPrimitive(c.data.s.decode("utf-8"))
    elif c.type == JSCType.UNDEFINED:
        return JSUndef
    elif c.type == JSCType.NUL:
        return JSNull
    elif c.type == JSCType.BOOL:
        return JSPrimitive(c.data.b != 0)        
    else:
        raise NotImplementedError

def call_function(name : str, args : List[JSCPrimitive]) -> JSPrimitive:
    """
    Call a JS function using the duktape engine
    
    :param str name: The function name
    :param List[JSCPrimitive] args: The function arguments
    :rtype JSCPrimitive:
    :return: The function result
    """
    c_args = (JSCPrimitive * len(args))()
    for i in range(len(args)):
        c_args[i] = concretize(args[i])
    __funcs.call_function.argtypes = [c_char_p, POINTER(JSCPrimitive*len(args)), c_int]
    res =__funcs.call_function(name.encode("utf-8"), byref(c_args), len(args))
    abs_res = abstract(res)
    __funcs.free_val(res)
    return abs_res

def init_duktape_binding() -> None:
    """
    Initialize duktape bindings. Should be called first.
    
    """
    global __funcs
    try:
        __funcs = CDLL(sys.path[0] + "/jseval.so")
    except OSError as e:
        print("Please compile the jseval.so library by typing \"make\" in the project main directory")
        raise e
    __funcs.initialize()
    __funcs.register_function.argtypes = [c_char_p]
    __funcs.call_function.restype = JSCPrimitive
