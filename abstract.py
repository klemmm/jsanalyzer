## Abstract semantics (State)
import sys
import traceback

class State(object):
    def __init__(self, glob=False, bottom=False):
        if bottom:
            self.objs = {}
            self.gref = None
            self.lref = None
            self.is_bottom = True
        else:
            self.is_bottom = False
            self.objs = {} 
            self.gref = State.new_id()
            self.objs[self.gref] = JSObject({})
            if glob:
                self.lref = self.gref
            else:
                self.lref = State.new_id()
                self.objs[self.lref] = JSObject({})

    # Class attributes
    next_id = 0

    # Class methods
    @staticmethod
    def bottom():
        st = State(glob=False, bottom=True)
        return st
    
    @staticmethod
    def top():
        st = State(glob=False, bottom=False)
        return st
    
    @staticmethod
    def new_id():
        State.next_id += 1
        return State.next_id - 1

    @staticmethod
    def set_next_id(next_id):
        State.next_id = next_id

    @staticmethod
    def dict_join(d1, d2):
        bye = []
        for k in d1:
            if not k in d2 or not State.value_equal(d1[k], d2[k]):
                bye.append(k)
        for b in bye:
            del d1[b]
        return d1

    @staticmethod
    def dict_assign(d1, d2):
        d1.clear()
        for k in d2:
            if isinstance(d2[k], dict):
                d1[k] = {}
                State.dict_assign(d1[k], d2[k])
            else:
                d1[k] = d2[k].clone()

    @staticmethod
    def value_equal(v1, v2):
        return type(v1) == type(v2) and v1 == v2

    @staticmethod
    def value_join(v1, v2):
        if v1 is None:
            return v2
        if v2 is None:
            return v1
        if State.value_equal(v1, v2):
            return v1
        else:
            return JSTop

    # Instance methods
    def set_to_bottom(self):
        self.objs.clear()
        self.gref = None
        self.lref = None
        self.is_bottom = True

    def clone(self):
        c = State()
        State.dict_assign(c.objs, self.objs)
        c.is_bottom = self.is_bottom
        c.lref = self.lref
        c.gref = self.gref
        return c 

    def __eq__(self, other):
        if self.is_bottom != other.is_bottom:
            return False
        if self.gref != other.gref:
            return False
        if self.lref != other.lref:
            return False
        if self.objs != other.objs:
            return False
        return True

    def assign(self, other):
        self.is_bottom = other.is_bottom
        self.gref = other.gref
        self.lref = other.lref
        State.dict_assign(self.objs, other.objs)

    def join(self, other):
        if other.is_bottom:
            return
        if self.is_bottom:
            self.assign(other)
            return
        assert(self.lref == other.lref)
        assert(self.gref == other.gref)

        bye = []
        for k in self.objs:
            if k in other.objs:
                if isinstance(self.objs[k],dict):
                    State.dict_join(self.objs[k], other.objs[k])
                else:
                    State.dict_join(self.objs[k].properties, other.objs[k].properties)
            else:
                bye.append(k)
        for b in bye:
            del self.objs[b]

    def scope_lookup(self, name):
        if name in self.objs[self.lref].properties:
            return self.objs[self.lref].properties

        current_scope = self.objs[self.lref].properties
        found = False
        while '__closure' in current_scope and not found:
            current_scope = self.objs[current_scope['__closure'].ref_id].properties
            found = name in current_scope
        if found:
            return current_scope
        return self.objs[self.gref].properties

    def __str__(self):
        if self.is_bottom:
            return "Bottom";
        return("gref=" + str(self.gref) + ", lref=" + str(self.lref) +", objs=" + str(self.objs))

    def __repr__(self):
        return self.__str__()

## Classes for wrapping JS values

class JSValue(object):
    def ref(self):
        return None
    pass

# Represents any simple type (for example: a number)
class JSPrimitive(JSValue):
    def __init__(self, val):
        self.val = val
    def __eq__(self, other):
        return self.val == other.val
    def __str__(self):
        return str(self.val)
    def __repr__(self):
        return self.__str__()
    def clone(self):
        c = JSPrimitive(self.val)
        return c

#Represents any special value (like undefined or NaN or Top)
class JSSpecial(JSValue):
    def __init__(self, name):
        self.name = name
    def clone(self):
        return self
    def __str__(self):
        return self.name
    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.name == other.name

JSUndefNaN = JSSpecial("Undef/NaN") #represents NaN or undefined
JSTop = JSSpecial("Top")

# Represents an object or array
class JSObject(JSValue):
    hooks = []

    @staticmethod
    def add_hook(hook):
        JSObject.hooks.append(hook)
    def __init__(self, properties, body=None, params=None, env=None, simfct=None):
        self.refcount = 0 #Number of references to that object
        self.properties = properties #dict listing properties of the object / array elements
        self.body = body #if function, represents the body AST
        self.params = params #if function, represents the arguments ASTs
        self.env = env #if function, this is the ID of object representing closure-captured environment, if any
        self.simfct = simct #Simulated function, if any
    def __str__(self):
        props = "{rc:" + str(self.refcount) + " " + (", ".join([(str(i) + ': ' + str(self.properties[i])) for i in self.properties])) + "} "
        if self.simfct is not None:
            return "<simfct " + props + ">"
        elif self.env is None:
            return "<function " + props + ">"
        else:
            return "<closure, env=" + str(self.env) + " " + props + ">"

    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.properties == other.properties and self.body == other.body and self.params == other.params and self.env == other.env and self.simfct == other.simfct
    def is_callable(self):
        return not (self.body is None and self.simfct is None)
    def is_simfct(self):
        return self.simfct is not None
    def is_function(self):
        return self.body is not None
    def is_closure(self):
        return self.env is not None
    def ref(self):
        return self.env
    def clone(self):
        c = JSObject({})
        State.dict_assign(c.properties, self.properties)
        c.refcount = self.refcount
        c.body = self.body
        c.params = self.params
        c.env = self.env
        c.simfct = self.simfct
        return c

    def inc(self):
        self.refcount += 1

    def dec(self, scope, _id):
        self.refcount -= 1
        if self.refcount == 0:
            for k in self.properties:
                if isinstance(self.properties[k], JSRef):
                    if self.properties[k].ref_id in scope:
                        scope[self.properties[k].ref_id].dec(scope, self.properties[k].ref_id)
                elif isinstance(self.properties[k], JSClosure) and self.properties[k].env is not None:
                    if self.properties[k].env in scope:
                        scope[self.properties[k].env].dec(scope, self.properties[k].env)
        
    def member(self, name):
        for h in JSObject.hooks:
            r = h(name, self)
            if r is not JSTop:
                def bound_method(*args):
                    return r.fct(self, *args)
                return JSSimFct(bound_method)
        return self.properties.get(name, JSUndefNaN) #TODO should be JSTop here (workaround until array bounds are handled)

# Represents a reference to an object or array
class JSRef(JSValue):
    def __init__(self, ref_id):
        self.ref_id = ref_id
    def __str__(self):
        return "<ref: " + str(self.ref_id) + ">"
    def __repr__(self):
        return self.__str__() 
    def __eq__(self, other):
        return self.ref_id == other.ref_id
    def ref(self):
        return self.ref_id
    def clone(self):
        c = JSRef(self.ref_id)
        return c

