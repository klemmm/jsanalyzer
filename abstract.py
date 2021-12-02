## Abstract semantics (State)

class State(object):
    def __init__(self):
        self.glob = {} #globals
        self.loc = {} #locals
        self.objs = {} #objects/arrays

    # Class attributes
    next_id = 0

    # Class methods

    @staticmethod
    def bottom():
        st = State()
        st.is_bottom = True
        return st
    
    @staticmethod
    def top():
        st = State()
        st.is_bottom = False
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
            if (not (k in d2) or (d1[k] != d2[k])):
                bye.append(k)
        for b in bye:
            del d1[b]
        return d1

    @staticmethod
    def dict_assign(d1, d2):
        d1.clear()
        for k in d2:
            d1[k] = d2[k].clone()

    # Instance methods

    def set_to_bottom(self):
        self.glob.clear()
        self.loc.clear()
        self.objs.clear()
        self.is_bottom = True

    def clone(self):
        c = State()
        c.is_bottom = self.is_bottom
        c.glob = {}
        c.loc = {}
        State.dict_assign(c.glob, self.glob)
        if self.loc is self.glob:
            c.loc = c.glob
        else:
            State.dict_assign(c.loc, self.loc)
        State.dict_assign(c.objs, self.objs)
        return c 

    def __eq__(self, other):
        if self.is_bottom != other.is_bottom:
            return False
        if self.glob != other.glob:
            return False
        if self.loc != other.loc:
            return False
        if (self.glob is self.loc) != (other.glob is other.loc):
            return False
        if self.objs != other.objs:
            return False
        return True

    def assign(self, other):
        self.is_bottom = other.is_bottom
        self.glob.clear()
        self.loc.clear()
        State.dict_assign(self.glob, other.glob)

        if other.loc is other.glob:
            self.loc = self.glob
        else:
            State.dict_assign(self.loc, other.loc)
        State.dict_assign(self.objs, other.objs)

    def join(self, other):
        if other.is_bottom:
            return
        if self.is_bottom:
            self.assign(other)
            return
        State.dict_join(self.glob, other.glob)
        State.dict_join(self.loc, other.loc)

        bye = []
        for k in self.objs:
            if k in other.objs:
                State.dict_join(self.objs[k].properties, other.objs[k].properties)
            else:
                bye.append(k)
        for b in bye:
            del self.objs[b]

    def __str__(self):
        if self.is_bottom:
            return "Bottom";
        loc = ""
        if not (self.glob is self.loc):
            loc = ", loc=" + str(self.loc)
        return("glob=" + str(self.glob) + loc + ", objs=" + str(self.objs))

    def __repr__(self):
        return self.__str__()

## Classes for wrapping JS values

class JSValue(object):
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

JSUndefNaN = JSSpecial("Undef/NaN") #represents NaN or undefined
JSTop = JSSpecial("Top")

# Represents an object or array
class JSObject(JSValue):
    hooks = []

    @staticmethod
    def add_hook(hook):
        JSObject.hooks.append(hook)
    def __init__(self, properties):
        self.properties = properties
    def __str__(self):
        return "{" + (", ".join([(str(i) + ': ' + str(self.properties[i])) for i in self.properties])) + "} "
    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.properties == other.properties
    def clone(self):
        c = JSObject({})
        State.dict_assign(c.properties, self.properties)
        return c
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
    def clone(self):
        c = JSRef(self.ref_id)
        return c

# Represents a simulated function (i.e. a js function re-implemented in python)
class JSSimFct(JSValue):
    def __init__(self, fct):
        self.fct = fct
    def __str__(self):
        return "<simfct>"
    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.fct == other.fct
    def clone(self):
        c = JSSimFct(self.fct)
        return c

# Represents a closure (i.e. a js function AST and its closure environment)
class JSClosure(JSValue):
    def __init__(self, params, body, env):
        self.params = params
        self.body = body
        self.env = env
    def __str__(self):
        if len(self.env) == 0:
            return "<function>"
        else:
            return "<function, env=" + str(self.env) + ">"
    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.body == other.body and self.params == other.params and self.env == other.env
    def clone(self): # /!\ No deep-copy of params and function body, as it is not needed yet
        env = {}
        State.dict_assign(env, self.env)
        c = JSClosure(self.params, self.body, env)
        return c


