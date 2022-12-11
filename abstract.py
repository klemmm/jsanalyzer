## Abstract semantics (State)
import sys
import traceback
import config
import copy
from debug import debug
from enum import Enum

class MissingMode(Enum):
    MISSING_IS_UNDEF = 0
    MISSING_IS_TOP = 1

class GCConfig:
    pass

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
                if not k in d2:
                    bye.append(k)
                else:
                    if not State.value_equal(d1[k], d2[k]):
                        d1[k] = State.value_join(d1[k], d2[k])
            for k in bye:
                del d1[k]
            return d1
        else:
            for k in d1:
                if not k in d2:
                    d1[k] = State.value_join(JSUndefNaN, d1[k])
                else:
                    if not State.value_equal(d1[k], d2[k]):
                        d1[k] = State.value_join(d1[k], d2[k])
            for k in d2:
                if not k in d1:
                    d1[k] = State.value_join(JSUndefNaN, d2[k])
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
    def dict_permissive_join(d1, d2):
        topify = []
        adds = []
        for k in d1:
            if k in d2 and not State.value_equal(d1[k], d2[k]) and not d1[k] is JSUndefNaN and not d2[k] is JSUndefNaN:
                topify.append(k)
        for k in d2:
            if not k in d1:
                adds.append((k, d2[k]))
        for k in topify:
            d1[k] = JSTop
        for k, v in adds:
            d1[k] = v
        return d1
    
    @staticmethod
    def object_permissive_join(obj1, obj2):
        if obj1.missing_mode != MissingMode.MISSING_IS_UNDEF or obj2.missing_mode != MissingMode.MISSING_IS_UNDEF:
            State.object_join(obj1, obj2)

        if obj1.tablength != obj2.tablength:
            obj1.tablength = None
        return State.dict_permissive_join(obj1.properties, obj2.properties)

    @staticmethod
    def dict_assign(d1, d2):
        d1.clear()
        for k in d2:
            d1[k] = d2[k].clone()

    @staticmethod
    def value_equal(v1, v2):
        return type(v1) == type(v2) and v1 == v2

    @staticmethod
    def keep_or(s):
        if not config.use_or:
            return False
        if len(s) > 2:
            return False
        return JSUndefNaN in s


    @staticmethod
    def value_join(v1, v2):
        if v1 is None or v1 is JSBot:
            return v2
        if v2 is None or v2 is JSBot:
            return v1
        if State.value_equal(v1, v2):
            return v1
        else:
            if isinstance(v1, JSOr):
                s1 = v1.choices
            else:
                s1 = set([v1])
            if isinstance(v2, JSOr):
                s2 = v2.choices
            else:
                s2 = set([v2])
            total = s1.union(s2)
            if State.keep_or(total):
                ret = JSOr(total)
                return ret
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
        c.assign(self)
        return c

    def __eq__(self, other):
        if self.is_bottom != other.is_bottom:
            return False
        if self.gref != other.gref:
            return False
        if self.lref != other.lref:
            return False
        if self.pending != other.pending:
            return False
        if self.value != other.value:
            return False
        if self.stack_frames != other.stack_frames:
            return False

        seen = set()
        def extract_ref(val):
            if isinstance(val, JSRef):
                return val
            if isinstance(val, JSOr):
                s = {v for v in val.choices if isinstance(v, JSRef)}
                if len(s) == 1:
                    return list(s)[0]
            return None
        def eq_aux(obj1, obj2):
            nonlocal self
            if obj1.is_closure() and obj2.is_closure():
                if obj1.closure_env() not in seen:
                    seen.add(obj1.closure_env())
                    if not eq_aux(self.objs[obj1.closure_env()], other.objs[obj2.closure_env()]):
                        return False
            for p in obj1.properties:
                if p not in obj2.properties or obj1.properties[p] != obj2.properties[p]:
                    return False
                ref = extract_ref(obj1.properties.get(p))
                if ref is not None:
                    if ref.target() not in seen:
                        seen.add(ref.target())
                        if not eq_aux(self.objs[ref.target()], other.objs[ref.target()]):
                            return False

                    if ref.is_bound() and type(ref.this()) is int:
                        if ref.this() not in seen:
                            seen.add(ref.this())
                            if not eq_aux(self.objs[ref1.this()], other.objs[ref2.this()]):
                                return False
            return obj1 == obj2

        if not eq_aux(self.objs[self.lref], other.objs[other.lref]):
            return False

        if not eq_aux(self.objs[self.gref], other.objs[other.gref]):
            return False

        for p in self.pending:
            if not eq_aux(self.objs[p], other.objs[p]):
                return False
        
        for s in self.stack_frames:
            if not eq_aux(self.objs[s], other.objs[s]):
                return False

        return True

    def assign(self, other):
        if other.is_bottom:
            self.set_to_bottom()
            return
        self.is_bottom = False
        self.gref = other.gref
        self.lref = other.lref
        self.pending = other.pending.copy()
        self.stack_frames = other.stack_frames.copy()
        self.value = other.value.clone()

        seen = set()
        def extract_ref(val):
            if isinstance(val, JSRef):
                return val
            if isinstance(val, JSOr):
                s = {v for v in val.choices if isinstance(v, JSRef)}
                if len(s) == 1:
                    return list(s)[0]
            return None

        def assign_aux(obj1, obj2):
            nonlocal self
            obj1.assign(obj2)

            if obj2.is_closure():
                if obj2.closure_env() not in seen:
                    seen.add(obj2.closure_env())
                    self.objs[obj2.closure_env()] = JSObject({})
                    assign_aux(self.objs[obj2.closure_env()], other.objs[obj2.closure_env()])

            for p in obj2.properties:
                ref = extract_ref(obj2.properties.get(p))
                if ref is not None:
                    if ref.target() not in seen:
                        seen.add(ref.target())
                        self.objs[ref.target()] = JSObject({})
                        assign_aux(self.objs[ref.target()], other.objs[ref.target()])

                    if ref.is_bound() and type(ref.this()) is int:
                        if ref.this() not in seen:
                            seen.add(ref.this())
                            self.objs[ref.this()] = JSObject({})
                            assign_aux(self.objs[ref.this()], other.objs[ref.this()])

        if other.lref not in seen:
            seen.add(other.lref)
            self.objs[other.lref] = JSObject({})
            assign_aux(self.objs[other.lref], other.objs[other.lref])

        if other.gref not in seen:
            seen.add(other.gref)
            self.objs[other.gref] = JSObject({})
            assign_aux(self.objs[other.gref], other.objs[other.gref])

        for p in other.pending:
            if p not in seen:
                seen.add(p)
                self.objs[p] = JSObject({})
                assign_aux(self.objs[p], other.objs[p])
        
        for s in other.stack_frames:
            if s not in seen:
                seen.add(s)
                self.objs[s] = JSObject({})
                assign_aux(self.objs[s], other.objs[s])
        

        for r in range(len(GCConfig.preexisting_objects)):
            if r not in seen:
                seen.add(r)
                self.objs[r] = JSObject({})
                assign_aux(self.objs[r], other.objs[r])
       
        self.value = other.value.clone()
        ref = extract_ref(self.value)
        if ref is not None and ref.target() not in self.objs:
            if ref.target() not in seen:
                seen.add(ref.target())
                self.objs[ref.target()] = JSObject({})
                assign_aux(self.objs[ref.target()], other.objs[ref.target()])
            if ref.is_bound() and type(ref.this()) is int and ref.this() not in seen:
                seen.add(ref.this())
                self.objs[ref.this()] = JSObject({})
                assign_aux(self.objs[ref.this()], other.objs[ref.this()])

    def visit(self, f):
        modify = []
        seen = set()
        def aux(val):
            nonlocal modify
            if isinstance(val, JSOr):
                s = set()
                for c in val.choices:
                    s.add(aux(c))
                if s != val.choices:
                    return JSOr(s)
                else:
                    return val
            elif isinstance(val, JSRef):
                target = f(val.target())
                #nr = JSRef(target)
                if val.target() not in seen:
                    seen.add(val.target())
                    aux(self.objs[val.target()])
                this = None
                if val.is_bound() and type(val.this()) is int:
                    this = f(val.this())
                    if val.this() not in seen:
                        seen.add(val.this())
                        aux(self.objs[val.this()])
                nr = JSRef(target, this)
                if nr == val:
                    return val
                else:
                    return nr
            elif isinstance(val, JSObject):
                for p, v in val.properties.items():
                    nv = aux(v)
                    if v != nv:
                        modify.append((val, p, nv))
                if val.is_closure():
                    if val.closure_env() not in seen:
                        seen.add(val.closure_env())
                        aux(self.objs[val.closure_env()])
                    val.env = f(val.env)
            else:
                return val

        aux(self.objs[self.lref])
        aux(self.objs[self.gref])
        for p in self.pending:
            aux(self.objs[p])
        for p in self.stack_frames:
            aux(self.objs[p])

        self.value = aux(self.value)

        for o, p, v in modify:
            o.properties[p] = v

    def unify(self, other):
        if not config.use_unify:
            return
        if self.lref != other.lref or self.stack_frames != other.stack_frames:
            return 
       
        #print("\n\nUnifying...")
        #print("self: ", self)
        #print("other:", other)
        seen = set()
        def extract_ref(val):
            if isinstance(val, JSRef):
                return val
            if isinstance(val, JSOr):
                s = {v for v in val.choices if isinstance(v, JSRef)}
                if len(s) == 1:
                    return list(s)[0]
            return None
        def unify_aux(obj1, obj2):
            nonlocal remap
            nonlocal self
            if obj1.is_closure() and obj2.is_closure():
                if obj1.closure_env() not in seen:
                    seen.add(obj1.closure_env())
                    unify_aux(self.objs[obj1.closure_env()], other.objs[obj2.closure_env()])
                if obj1.closure_env() != obj2.closure_env():
                    remap[obj1.closure_env()] = obj2.closure_env()
            for p in obj1.properties:
                #print("pre: ", p, obj1.properties.get(p), obj2.properties.get(p))
                ref1 = extract_ref(obj1.properties.get(p))
                ref2 = extract_ref(obj2.properties.get(p))
                if ref1 is not None and ref2 is not None:
                    #print("processing 1", p)
                    if ref1.target() not in seen:
                        #print("add", ref1.target(), ref2.target())
                        seen.add(ref1.target())
                        unify_aux(self.objs[ref1.target()], other.objs[ref2.target()])
                    if ref1.target() != ref2.target():
                        if ref2.target() in self.objs:
                            remap[ref2.target()] = State.new_id()
                        remap[ref1.target()] = ref2.target()
                    if ref1.is_bound() and ref2.is_bound() and type(ref1.this()) is int and type(ref2.this()) is int:
                        if ref1.this() not in seen:
                            seen.add(ref1.this())
                            unify_aux(self.objs[ref1.this()], other.objs[ref2.this()])
                        if ref1.this() != ref2.this():
                            if ref2.this() in self.objs:
                                remap[ref2.this()] = State.new_id()
                            remap[ref1.this()] = ref2.this()

        remap = {} 
        unify_aux(self.objs[self.lref], other.objs[other.lref])
        unify_aux(self.objs[self.gref], other.objs[other.gref])
        #for p in self.pending:
        #    unify_aux(self.objs[p], other.objs[p])
        
        for s in self.stack_frames:
            unify_aux(self.objs[s], other.objs[s])

        def do_remap(_id):
            if _id in remap:
                return remap[_id]
            return _id

        self.visit(do_remap)
        for old, new in remap.items():
            self.objs[new] = self.objs.pop(old)

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
        self.unify(other)

        seen = set()
        def extract_ref(val):
            if isinstance(val, JSRef):
                return val
            if isinstance(val, JSOr):
                s = {v for v in val.choices if isinstance(v, JSRef)}
                if len(s) == 1:
                    return list(s)[0]
            return None
        def join_aux(obj1, obj2):
            nonlocal self
            State.object_join(obj1, obj2)

            if obj1.is_closure() and obj2.is_closure():
                #and obj1.closure_env() == obj2.closure_env():
                assert(obj1.closure_env() == obj2.closure_env())
                if obj1.closure_env() not in self.objs:
                    self.objs[obj1.closure_env()] = other.objs[obj2.closure_env()].clone()
                if obj1.closure_env() not in seen:
                    seen.add(obj1.closure_env())
                    join_aux(self.objs[obj1.closure_env()], other.objs[obj2.closure_env()])

            for p in obj1.properties:
                ref1 = extract_ref(obj1.properties.get(p))
                ref2 = extract_ref(obj2.properties.get(p))
                if ref1 is not None and ref2 is not None:
                    assert ref1 == ref2
                    if ref1.target() not in self.objs:
                        self.objs[ref1.target()] = other.objs[ref1.target()].clone()
                    if ref1.target() not in seen:
                        seen.add(ref1.target())
                        join_aux(self.objs[ref1.target()], other.objs[ref2.target()])

                    if ref1.is_bound() and type(ref1.this()) is int:
                        if ref1.this() not in self.objs:
                            self.objs[ref1.this()] = other.objs[ref1.this()].clone()
                        if ref1.this() not in seen:
                            seen.add(ref1.this())
                            join_aux(self.objs[ref1.this()], other.objs[ref2.this()])

        join_aux(self.objs[self.lref], other.objs[other.lref])

        join_aux(self.objs[self.gref], other.objs[other.gref])

        for p in self.pending:
            join_aux(self.objs[p], other.objs[p])
        
        for s in self.stack_frames:
            join_aux(self.objs[s], other.objs[s])
        
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
        return("frames=" + str(self.stack_frames) + " gref=" + str(self.gref) + ", lref=" + str(self.lref) +", objs=" + str(self.objs) + ", pending="+ str(self.pending) + ", endval=" + str(self.value))

    def __repr__(self):
        return self.__str__()

    def consume_expr(self, expr, consumed_refs=None):

        refs_to_add = set()
        if isinstance(expr, JSRef):
            refs_to_add.add(expr)
        elif isinstance(expr, JSOr):
            for c in expr.choices:
                if isinstance(c, JSRef):
                    refs_to_add.add(c)

        if consumed_refs is None:
            for expr in refs_to_add:
                self.pending.discard(expr.target())
                #print("PEND discard: ", expr.target())
                if expr.is_bound() and type(expr.this()) is int:
                    self.pending.discard(expr.this())
                    #print("PEND discard: ", expr.this())
        else:
            for expr in refs_to_add:
                consumed_refs.add(expr.target())
                #print("PEND consume: ", expr.target())
                if expr.is_bound() and type(expr.this()) is int:
                    consumed_refs.add(expr.this())
                    #print("PEND consume: ", expr.this())


    def cleanup(self, verbose=False):
        debug("State before GC: ", self)

        if self.is_bottom:
            debug("GC: Not doing anything\n")
            return

        #first, unlink top objects
        changes = config.clean_top_objects
        while changes:
            changes = False
            for obj_id in self.objs:
                bye = []
                for p in self.objs[obj_id].properties:
                    if isinstance(self.objs[obj_id].properties[p], JSRef):
                        i = self.objs[obj_id].properties[p].target()
                        if self.objs[i].missing_mode == MissingMode.MISSING_IS_TOP and len([v for v in self.objs[i].properties.values() if v is not JSTop]) == 0:
                            bye.append(p)
                if len(bye) > 0:
                    changes = True
                for b in bye:
                    if self.objs[obj_id].missing_mode == MissingMode.MISSING_IS_TOP:
                        del self.objs[obj_id].properties[b]
                    else:
                        self.objs[obj_id].properties[b] = JSTop

        reachable = set()
        def visit(ref_id):
            if ref_id in reachable:
                return
            reachable.add(ref_id)
            if ref_id not in self.objs:
                print(self)
                raise ValueError
            obj = self.objs[ref_id]
            for k,p in obj.properties.items():
                if isinstance(p, JSOr):
                    fields = p.choices
                else:
                    fields = set([p])
                for v in fields:
                    if v.target() is None:
                        continue
                    visit(v.target())
                    if v.is_bound():
                        visit(v.this())
            if obj.is_closure():
                visit(obj.closure_env())

        visit(self.lref) #local context gc root
        visit(self.gref) #global context gc root

        if isinstance(self.value, JSRef): #end-value is a gc root
            visit(self.value.target())

        #callstack local contexts gc root
        for ref in self.stack_frames:
            visit(ref)

        #pending expressions gc root
        for ref in self.pending:
            visit(ref)

        #preexisting objects gc root
        for ref, obj in GCConfig.preexisting_objects:
            visit(ref)

        if verbose or config.debug:
            print("GC: Reachable nodes: ", reachable)
        bye = set()
        for o,v in self.objs.items():
            if o not in reachable:
                bye.add(o)

        for b in bye:
            del self.objs[b]

## Classes for wrapping JS values

class JSValue(object):
    def is_callable(self):
        return False
    def is_simfct(self):
        return False
    def is_pure_simfct(self):
        return False
    def is_function(self):
        return False
    def is_closure(self):
        return False
    def is_bound(self):
        return False
    def contains_top(self):
        return False
    def target(self):
        return None

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
    def __hash__(self):
        return self.val.__hash__()
    def clone(self):
        return self

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
    def __hash__(self):
        return self.name.__hash__()
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
        return cls({}, body, params, None, None, False)
    
    @classmethod
    def closure(cls, body, params, env):
        return cls({}, body, params, env, None, False)
    
    @classmethod
    def simfct(cls, simfct, pure_simfct=False):
        return cls({}, None, None, None, simfct, pure_simfct)

    @classmethod
    def object(cls):
        return cls({}, None, None, None, None, False)

    @staticmethod
    def add_hook(hook):
        JSObject.hooks.append(hook)
    def __init__(self, properties, body=None, params=None, env=None, simfct=None, pure_simfct=False):
        self.properties = properties #dict listing properties of the object / array elements
        self.body = body #if function, represents the body AST
        self.params = params #if function, represents the arguments ASTs
        self.env = env #if function, this is the ID of object representing closure-captured environment, if any
        self.simfct = simfct #Simulated function, if any
        self.missing_mode = MissingMode.MISSING_IS_UNDEF
        self.fn_isexpr = False
        self.pure_simfct = pure_simfct
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
        def fn(s):
            if type(s) is int:
                return s
            return -1
        props = "{" + l + (", ".join([(str(i) + ': ' + str(self.properties[i])) for i in sorted(self.properties, key=fn)])) + missing_mode + "} "
        if self.simfct is not None:
            return "<simfct " + props + " pure=" + str(self.pure_simfct) + ">"
        elif self.env is not None:
            return "<closure, isexpr=" + str(self.fn_isexpr) + ", env=" + str(self.env) + " " + props + ">"
        elif self.body is not None:
            return "<function, isexpr=" + str(self.fn_isexpr) + " " + props + ">"
        else:
            return "<object " + props + ">"

    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        if type(self) != type(other):
            return False
        return self.properties == other.properties and self.body == other.body and self.params == other.params and self.env == other.env and self.simfct == other.simfct and self.missing_mode == other.missing_mode and self.tablength == other.tablength and self.fn_isexpr == other.fn_isexpr 

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
    def is_pure_simfct(self):
        return self.pure_simfct

    def assign(self, other):
        self.properties = other.properties.copy()
        self.body = other.body
        self.params = other.params
        self.env = other.env
        self.simfct = other.simfct
        self.missing_mode = other.missing_mode
        self.tablength = other.tablength
        self.fn_isexpr = other.fn_isexpr
        self.pure_simfct = other.pure_simfct

    def clone(self):
        c = JSObject({})
        c.assign(self)
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
            #print("Member not found:", name, "mode:", self.missing_mode)
            #raise ValueError
            if self.missing_mode == MissingMode.MISSING_IS_TOP:
                return JSTop
            else:
                return JSUndefNaN
        return r

# Represents a reference to an object or array
class JSRef(JSValue):
    def __init__(self, ref_id, this=None):
        self.ref_id = ref_id
        self._this = this
    def __str__(self):
        if type(self._this) is int:
            return "<ref: " + str(self.ref_id) + " bound:" + str(self._this) + ">"
        else:
            return "<ref: " + str(self.ref_id) + ">"
    def __repr__(self):
        return self.__str__() 
    def __eq__(self, other):
        if type(self) != type(other):
            return False
        return self.ref_id == other.ref_id and self._this == other._this
    def target(self):
        return self.ref_id
    def clone(self):
        return self
    def is_bound(self):
        return self._this is not None
    def this(self):
        return self._this
    def __hash__(self):
        return self.ref_id.__hash__()

# Represent a choice between values
class JSOr(JSValue):
    def __init__(self, choices):
        self.choices = set(choices)
    def __str__(self):
        return "Or(" + ",".join([str(c) for c in self.choices]) + ")"
    def __eq__(self, other):
        if type(self) != type(other):
            return False
        return self.choices == other.choices
    def __repr__(self):
        return self.__str__() 
    def clone(self):
        return self

