## Abstract semantics (State)
import sys
import traceback
import config
from enum import Enum

class MissingMode(Enum):
    MISSING_IS_UNDEF = 0
    MISSING_IS_TOP = 1

class State(object):
    def __init__(self, glob=False, bottom=False):
        if bottom:
            self.objs = {}
            self.gref = None
            self.lref = None
            self.pending = set()
            self.is_bottom = True
            self.stack_frames = []
            self.value = JSBot
        else:
            self.is_bottom = False
            self.objs = {} 
            self.pending = set()
            self.stack_frames = []
            self.gref = State.new_id()
            self.objs[self.gref] = JSObject({})
            if glob:
                self.lref = self.gref
            else:
                self.lref = State.new_id()
                self.objs[self.lref] = JSObject({})
            self.objs[self.gref].set_missing_mode(MissingMode.MISSING_IS_TOP)
            self.objs[self.lref].set_missing_mode(MissingMode.MISSING_IS_TOP)
            self.value = JSTop

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
    def dict_join(d1, d2, missing_mode):
        if missing_mode == MissingMode.MISSING_IS_TOP:
            bye = []
            for k in d1:
                if not k in d2 or not State.value_equal(d1[k], d2[k]):
                    bye.append(k)
            for k in bye:
                del d1[k]
            return d1
        else:
            topify = []
            for k in d1:
                if not k in d2 or not State.value_equal(d1[k], d2[k]):
                    topify.append(k)
            for k in d2:
                if not k in d1:
                    topify.append(k)
            for k in topify:
                d1[k] = JSTop
            return d1

    @staticmethod
    def object_join(obj1, obj2):
        if obj1.missing_mode == obj2.missing_mode:
            if obj1.tablength != obj2.tablength:
                obj1.tablength = None
            return State.dict_join(obj1.properties, obj2.properties, obj1.missing_mode)
        else:
            obj1.set_missing_mode(MissingMode.MISSING_IS_TOP)
            obj2_copy = obj2.clone()
            obj2_copy.set_missing_mode(MissingMode.MISSING_IS_TOP)
            return State.dict_join(obj1.properties, obj2_copy.properties, MissingMode.MISSING_IS_TOP)

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
        self.stack_frames = []
        self.pending = set()
        self.value = JSBot

    def clone(self):
        c = State()
        State.dict_assign(c.objs, self.objs)
        c.is_bottom = self.is_bottom
        c.lref = self.lref
        c.gref = self.gref
        c.pending = self.pending.copy()
        c.stack_frames = self.stack_frames.copy()
        c.value = self.value.clone()
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
        if self.pending != other.pending:
            return False
        if self.stack_frames != other.stack_frames:
            return False
        return True

    def assign(self, other):
        self.is_bottom = other.is_bottom
        self.gref = other.gref
        self.lref = other.lref
        State.dict_assign(self.objs, other.objs)
        self.pending = other.pending.copy()
        self.stack_frames = other.stack_frames.copy()
        self.value = other.value.clone()

    #In case of join on recursion state, other is the state of the greater recursion depth, self is the state of lesser recursion depth
    def join(self, other):
        if other.is_bottom:
            return
        if self.is_bottom:
            self.assign(other)
            return

        assert self.gref == other.gref
        
        #handle recursion
        if self.lref != other.lref or self.stack_frames != other.stack_frames:
            if len(self.stack_frames) >= len(other.stack_frames):
                print(self)
                print(other)
                raise ValueError
            assert self.lref < other.lref
            assert(self.lref in other.stack_frames)
            lref_idx = other.stack_frames.index(self.lref)
            assert(self.stack_frames == other.stack_frames[0:lref_idx])
            State.object_join(self.objs[self.lref], other.objs[other.lref])

        self.pending.intersection_update(other.pending)

        bye = []
        for k in self.objs:
            if k in other.objs:
                if k == 11151749:
                    if 55 in self.objs[k].properties and 55 not in other.objs[k].properties:
                        raise ValueError
                    if 55 not in self.objs[k].properties and 55 in other.objs[k].properties:
                        raise ValueError
                    if 55 in self.objs[k].properties and (self.objs[k].properties[55] != other.objs[k].properties[55]):
                        raise ValueError
                State.object_join(self.objs[k], other.objs[k])
            else:
                bye.append(k)
        for b in bye:
            del self.objs[b]

        if self.value is JSBot:
            self.value = other.value.clone()
        elif not State.value_equal(self.value, other.value):
            self.value = JSTop

    def scope_lookup(self, name):
        if name in self.objs[self.lref].properties:
            return self.objs[self.lref]

        current_scope = self.objs[self.lref]
        found = False
        while '__closure' in current_scope.properties and not found:
            current_scope = self.objs[current_scope.properties['__closure'].ref_id]
            found = name in current_scope.properties
        if found:
            return current_scope
        return self.objs[self.gref]

    def __str__(self):
        if self.is_bottom:
            return "Bottom";
        return("frames=" + str(self.stack_frames) + " gref=" + str(self.gref) + ", lref=" + str(self.lref) +", objs=" + str(self.objs) + ", pending="+ str(self.pending))

    def __repr__(self):
        return self.__str__()

    def consume_expr(self, expr, consumed_refs=None):
        if consumed_refs is None:
            if isinstance(expr, JSRef):
                self.pending.discard(expr.target())
                #print("PEND discard: ", expr.target())
                if expr.is_bound() and type(expr.this()) is int:
                    self.pending.discard(expr.this())
                    #print("PEND discard: ", expr.this())
        else:
            if isinstance(expr, JSRef):
                consumed_refs.add(expr.target())
                #print("PEND consume: ", expr.target())
                if expr.is_bound() and type(expr.this()) is int:
                    consumed_refs.add(expr.this())
                    #print("PEND consume: ", expr.this())


## Classes for wrapping JS values

class JSValue(object):
    def is_callable(self):
        return False
    def is_simfct(self):
        return False
    def is_function(self):
        return False
    def is_closure(self):
        return False
    def is_bound(self):
        return False
    def contains_top(self):
        return False
    pass

# Represents any simple type (for example: a number)
class JSPrimitive(JSValue):
    def __init__(self, val):
        self.val = val
    def __eq__(self, other):
        if type(self) != type(other):
            return False
        return self.val == other.val
    def __str__(self):
        return repr(self.val)
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
        if type(self) != type(other):
            return False
        return self.name == other.name
    def contains_top(self):
        return self.name == "Top"

JSUndefNaN = JSSpecial("Undef/NaN") #represents NaN or undefined
JSTop = JSSpecial("Top")
JSBot = JSSpecial("Bot")

# Represents an object or array
class JSObject(JSValue):
    hooks = []
    GC_IGNORE = -1

    #convenience functions to build obj/simfct/function/closure
    @classmethod
    def function(cls, body, params):
        return cls({}, body, params, None, None)
    
    @classmethod
    def closure(cls, body, params, env):
        return cls({}, body, params, env, None)
    
    @classmethod
    def simfct(cls, simfct):
        return cls({}, None, None, None, simfct)
    
    @classmethod
    def object(cls):
        return cls({}, None, None, None, None)

    @staticmethod
    def add_hook(hook):
        JSObject.hooks.append(hook)
    def __init__(self, properties, body=None, params=None, env=None, simfct=None):
        self.properties = properties #dict listing properties of the object / array elements
        self.body = body #if function, represents the body AST
        self.params = params #if function, represents the arguments ASTs
        self.env = env #if function, this is the ID of object representing closure-captured environment, if any
        self.simfct = simfct #Simulated function, if any
        self.missing_mode = MissingMode.MISSING_IS_UNDEF
        self.tablength = 0
    def __str__(self):
        missing_mode = ""
        if self.missing_mode == MissingMode.MISSING_IS_UNDEF:
            missing_mode = " ...undefined"
        elif self.missing_mode == MissingMode.MISSING_IS_TOP:
            missing_mode = " ...Top"
        l = ""
        if self.tablength is not None:
            l = "len=" + str(self.tablength) + ", "
        props = "{" + l + (", ".join([(str(i) + ': ' + str(self.properties[i])) for i in sorted(self.properties)])) + missing_mode + "} "
        if self.simfct is not None:
            return "<simfct " + props + ">"
        elif self.env is not None:
            return "<closure, env=" + str(self.env) + " " + props + ">"
        elif self.body is not None:
            return "<function " + props + ">"
        else:
            return "<object " + props + ">"

    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return self.properties == other.properties and self.body == other.body and self.params == other.params and self.env == other.env and self.simfct == other.simfct and self.missing_mode == other.missing_mode and self.tablength == other.tablength

    def contains_top(self):
        return self.missing_mode == MissingMode.MISSING_IS_TOP or JSTop in self.properties.values()
    def is_callable(self):
        return not (self.body is None and self.simfct is None)
    def is_simfct(self):
        return self.simfct is not None
    def is_function(self):
        return self.body is not None
    def is_closure(self):
        return self.env is not None
    def closure_env(self):
        return self.env
    def clone(self):
        c = JSObject({})
        State.dict_assign(c.properties, self.properties)
        c.body = self.body
        c.params = self.params
        c.env = self.env
        c.simfct = self.simfct
        c.missing_mode = self.missing_mode
        c.tablength = self.tablength
        return c

    def set_missing_mode(self, missing_mode):
        if self.missing_mode == MissingMode.MISSING_IS_UNDEF and missing_mode == MissingMode.MISSING_IS_TOP:
            self.properties = {k: v for k,v in self.properties.items() if v is not JSTop}
            self.tablength = None
        self.missing_mode = missing_mode 

    def set_member(self, name, value):
        if name is None:
            self.missing_mode = MissingMode.MISSING_IS_TOP
            self.properties.clear()
        else:
            if self.missing_mode == MissingMode.MISSING_IS_TOP:
                if value is not JSTop:
                    self.properties[name] = value
            else:
                self.properties[name] = value
                if type(name) is int and self.tablength is not None:
                    self.tablength = max(self.tablength, name + 1)

    def member(self, name):
        for h in JSObject.hooks:
            r = h(name)
            if r is not JSTop:
                return r
        r = self.properties.get(name, None)
        if r is None:
            print("Member not found:", name, "mode:", self.missing_mode)
            #raise ValueError
            if self.missing_mode == MissingMode.MISSING_IS_TOP:
                return JSTop
            else:
                return JSUndefNaN
        return r

# Represents a reference to an object or array
class JSRef(JSValue):
    def __init__(self, ref_id):
        self.ref_id = ref_id
        self._this = None
    def __str__(self):
        if type(self._this) is int:
            return "<ref: " + str(self.ref_id) + " bound:" + str(self._this) + ">"
        else:
            return "<ref: " + str(self.ref_id) + ">"
    def __repr__(self):
        return self.__str__() 
    def __eq__(self, other):
        return self.ref_id == other.ref_id
    def target(self):
        return self.ref_id
    def clone(self):
        c = JSRef(self.ref_id)
        return c
    def is_bound(self):
        return self._this is not None
    def bind(self, this):
        self._this = this
    def this(self):
        return self._this

