## Abstract semantics (State)
import sys
import traceback
import config
import copy
from debug import debug
from enum import Enum
from typing import Set, Union, List, Dict, Optional, Callable
import re
import esprima

class MissingMode(Enum):
    """
    This enum is associated to each JSObject class. MISSING_IS_UNDEF means that a field not represented
    in the JSObject's properties is assumed to be undefined. Otherwise, it is assumed to be JSTop (any value)
    """
    MISSING_IS_UNDEF = 0
    MISSING_IS_TOP = 1

class GCConfig:
    """
    This class contains various fields useful to control the behavior of the garbage collector
    """
    pass

class State(object):
    """
    This class represents an abstract state (i.e. an over-approximation of possible concrete states at some point in the program)
    """
    def __init__(self, glob : bool = False, bottom : bool = False) -> None:
        """
        Class constructor

        :param bool glob: True to create State in global scope, False otherwise (local scope)
        :param bool bottom: True to create a bottom state (i.e. corresponding to no concrete state), False otherwise
        """
        if bottom:
            self.objs : Dict[int, 'JSObject']= {}
            """Dict from ref-ids to JSObjects, represents the "heap" """

            self.gref : int = None
            """ref-id to the JSObject representing global context"""

            self.lref : int = None
            """ref-id to the JSObject representing local context"""

            self.pending : Set[int]= set()
            """set of ref-ids representing newly-created objects that are not yet referenced"""

            self.is_bottom : bool = True
            """True if this is a bottom state"""

            self.stack_frames : List[int] = []
            """Stack of ref-ids, each element is a ref-id to the JSObject representing the stack frame local context"""

            self.value : 'JSValue' = JSBot
            """Represents the value computed by the current statement"""

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
    def bottom() -> 'State':
        """'
        Returns a new bottom state

        :rtype State:
        :return: a bottom state
        """
        st = State(glob=False, bottom=True)
        return st
    
    @staticmethod
    def new_id() -> int:
        """
        Returns a analysis-wide unique ID 

        :rtype int:
        :return: the ID
        """
        State.next_id += 1
        return State.next_id - 1

    @staticmethod
    def set_next_id(next_id : int) -> None:
        """
        Set the next id counter

        :param int next_id: The next ID
        """
        State.next_id = next_id

    @staticmethod
    def object_join(obj1 : 'JSObject', obj2 : 'JSObject') -> None:
        """
        Joins two JSObjects, storing the result in the first argument

        :param JSObject obj1: The first object to join (will be modified to store the join result)
        :param JSObject obj2: The second object (will not be modified)
        """
        if obj1.missing_mode == obj2.missing_mode:
            if obj1.tablength != obj2.tablength:
                obj1.tablength = None
        else:
            obj1.set_missing_mode(MissingMode.MISSING_IS_TOP)

        if obj1.missing_mode == MissingMode.MISSING_IS_TOP:
            bye = []
            for k in obj1.properties:
                if not k in obj2.properties:
                    bye.append(k)
                else:
                    if not State.value_equal(obj1.properties[k], obj2.properties[k]):
                        obj1.properties[k] = State.value_join(obj1.properties[k], obj2.properties[k])
            for k in bye:
                del obj1.properties[k]
        else:
            for k in obj1.properties:
                if not k in obj2.properties:
                    obj1.properties[k] = State.value_join(JSUndefNaN, obj1.properties[k])
                else:
                    if not State.value_equal(obj1.properties[k], obj2.properties[k]):
                        obj1.properties[k] = State.value_join(obj1.properties[k], obj2.properties[k])
            for k in obj2.properties:
                if not k in obj1.properties:
                    obj1.properties[k] = State.value_join(JSUndefNaN, obj2.properties[k])
        
    @staticmethod
    def value_equal(v1 : 'JSValue', v2 : 'JSValue') -> bool:
        """
        Compare two abstract values

        :param JSVal v1: First abstract value
        :param JSVal v2: Second abstract value
        :rtype: bool
        :return: Comparison result
        """
        return type(v1) == type(v2) and v1 == v2

    @staticmethod
    def keep_or(s : Set['JSValue']) -> bool:
        """
        Heuristic used to determine, when a variable / field / ... can have multiple values, if we
        keep all of them using a JSOr, or not.

        :param Set[JSValue] s: Set of values
        :rtype bool:
        :return: True if we keep the multiple values, False if we discard them
        """
        if not config.use_or:
            return False
        if len(s) > 2:
            return False
        return JSUndefNaN in s

    @staticmethod
    def value_join(v1 : 'JSValue', v2 : 'JSValue') -> 'JSValue':
        """
        Join two jsvalues, returning the result

        :param JSValue v1: First value
        :param JSValue v2: Second value
        :rtype: JSValue
        :return: The join result
        """
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
    def set_to_bottom(self) -> None:
        """
        Convert this state to the bottom state
        """
        self.objs.clear()
        self.gref = None
        self.lref = None
        self.is_bottom = True
        self.stack_frames = []
        self.pending = set()
        self.value = JSBot

    def clone(self) -> 'State':
        """
        Clone this state

        :rtype: State
        :return: State copy
        """
        c = State()
        c.assign(self)
        return c


    # TODO rewrite/revert
    def __eq__(self, other : 'State') -> bool:
        """
        Test state equality. The two states must have been garbage-collected before test.

        :param State other: the other state
        :rtype: bool
        :return: True if equal, False otherwise
        """
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
                            if not eq_aux(self.objs[ref.this()], other.objs[ref.this()]):
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

    #TODO revert/rewrite
    def assign(self, other : 'State') -> None:
        """
        Do state assignment (self <- other)

        :param State other: the other state
        """
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


    #TODO cleanup
    def unify(self, other : 'State') -> None:
        """
        Remap self state to use IDs from other state

        :param State other: the other state
        """        
        if not config.use_unify:
            return
        if self.lref != other.lref or self.stack_frames != other.stack_frames:
            return 
       
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

    #TODO rewrite/revert
    #In case of join on recursion state, other is the state of the greater recursion depth, self is the state of lesser recursion depth
    def join(self, other : 'State') -> None:
        """
        Perform join between two states, modify self to store result

        :param State other: the other state
        """          
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

    def scope_lookup(self, name : str) -> 'JSObject':
        """
        Search for a variable with the given name in local scope, then closure scopes, and global scope.
        Returns the JSObject representing the scope where the variable was found, otherwise returns the JSObject representing the global scope.

        :param str name: The variable name
        :rtype: JSObject
        :return: The JSObject representing the scope containing the variable
        """
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

    def __str__(self) -> str:
        """
        Gives string representation of state

        :rtype: str
        :return: String representation
        """
        if self.is_bottom:
            return "Bottom";
        return("frames=" + str(self.stack_frames) + " gref=" + str(self.gref) + ", lref=" + str(self.lref) +", objs=" + str(self.objs) + ", pending="+ str(self.pending) + ", endval=" + str(self.value))

    def __repr__(self) -> str:
        """
        Gives string representation of state

        :rtype: str
        :return: String representation
        """        
        return self.__str__()

    def consume_expr(self, expr : 'JSValue', consumed_refs:Set[int]=None) -> None:
        """
        Look for references in value, and remove them from pending set.
        If consumed_refs is not None, defer the removal and put ref id in consumed_refs instead

        :param JSValue expr: The value to examine
        :param Set[int] consumed_refs: Store removed ref-id here if not None, instead of removing from pending
        """

        #TODO faire une fonction pour recuperer les ref id
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
                if expr.is_bound() and type(expr.this()) is int:
                    self.pending.discard(expr.this())
        else:
            for expr in refs_to_add:
                consumed_refs.add(expr.target())
                if expr.is_bound() and type(expr.this()) is int:
                    consumed_refs.add(expr.this())

    def cleanup(self, verbose : bool = False) -> None:
        """
        Garbage-collect state

        :param bool verbose: Display debug info
        """
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
    """
    This is an abstract class representing any abstract JS value
    """
    def is_callable(self) -> bool:
        """
        Is this value a callable? (function or simfct)

        :rtype bool:
        :return: True if the value is a callable 
        """
        return False

    def is_simfct(self) -> bool:
        """
        Is this value a simfct?

        :rtype bool:
        :return: True if the value is a simfct 
        """        
        return False

    def is_pure_simfct(self) -> bool:
        """
        Is this value a simfct without side effects?

        :rtype bool:
        :return: True if the value is a simfct without side effects
        """        
        return False

    def is_function(self) -> bool:
        """
        Is this value a function ? (a real function, not a simfct)

        :rtype bool:
        :return: True if the value is a function 
        """        
        return False

    def is_closure(self) -> bool:
        """
        Is this value a closure ? (i.e. a function with captured environment)

        :rtype bool:
        :return: True if the value is a closure 
        """        
        return False

    def is_bound(self) -> bool:
        """
        Is this value a reference to a function bound to an object?

        :rtype bool:
        :return: True if the value is bound 
        """        
        return False

    def contains_top(self) -> bool:
        """
        Test if this value contains top (i.e.: array containing a TOP value)

        :rtype bool:
        :return: True if the value contains top
        """        
        return False

    def target(self) -> int:
        """
        If this value is a reference, returns ref-id

        :rtype int:
        :return: the ref-id
        """        
        return None

    def this(self) -> Union[int, str]:
        """
        If this value is a bound reference, returns ref-id (if bound to object) or string (if bound to string)

        :rtype Union[int, str]:
        :return: the ref-id or string
        """        
        return None

    def clone(self) -> 'JSValue':
        """
        Returns a copy of the JSValue. Note that this may return either a shallow copy or a deep copy.
        A shallow copy is returned if the JSValue is immutable, otherwise a deep copy is performed.

        :rtype: JSValue
        :return: The copy
        """
        raise NotImplementedError

    def __hash__(self) -> int:
        """
        Returns hash value of the object

        :rtype: int
        :return: the hash value
        """
        raise NotImplementedError   

    def closure_env(self) -> int:
        """
        If this value is a closure, returns the ref-id to the closure environment

        :rtype int:
        :return: the ref-id
        """        
        return None           

# Represents any simple type (for example: a number)
class JSPrimitive(JSValue):
    """
    This class represent any simple (scalar) type.
    """
    def __init__(self, val : Union[int, str, float, re.Pattern]) -> None:
        """
        Class constructor

        :param Union[int, str, float, re.Pattern]: The concrete value
        """
        self.val : Union[int, str, float, re.Pattern] = val
        """The concrete value"""
        
    def __eq__(self, other : JSValue) -> bool:
        if type(self) != type(other):
            return False
        return self.val == other.val

    def __str__(self) -> str:
        return repr(self.val)

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        return self.val.__hash__()

    def clone(self) -> 'JSPrimitive':
        return self

class JSSpecial(JSValue):
    """
    Represents special values, such as Top (i.e. any/unknown value), Bottom (no value), undefined, or NaN
    """
    def __init__(self, name : str) -> None:
        """
        Class constructor

        :param str name: Either "Top", "Bot" or "JSUndefNaN"
        """
        self.name : str = name
        """ Either "Top", "Bot" or "JSUndefNaN" """

    def clone(self) -> 'JSSpecial':
        return self

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.__str__()

    def __eq__(self, other : JSValue) -> bool:
        if type(self) != type(other):
            return False
        return self.name == other.name

    def __hash__(self) -> int:
        return self.name.__hash__()

    def contains_top(self) -> bool:
        return self.name == "Top"

JSUndefNaN = JSSpecial("Undef/NaN") #represents NaN or undefined
JSTop = JSSpecial("Top")
JSBot = JSSpecial("Bot")

# 
class JSObject(JSValue):
    """
    This class represents an object, array, or callable (simfct, or real function)

    :members: hooks
    """

    hooks : List[Callable] = []
    """
    List of hooks, i.e. functions that returns methods that are available in any object
    """

    #convenience functions to build obj/simfct/function/closure
    @classmethod
    def function(cls, body : esprima.nodes.Node, params : esprima.nodes.Node) -> 'JSObject':
        """
        Build a JSObject for a function
        
        :param esprima.nodes.Node body: The function's body
        :param esprima.nodes.Node params: The function's formal args
        :rtype JSObject:
        :return: The JSObject representing the function
        """
        return cls({}, body, params, None, None, False)
    
    @classmethod
    def closure(cls, body : esprima.nodes.Node, params : esprima.nodes.Node, env : int) -> 'JSObject':
        """
        Build a JSObject for a closure
        
        :param esprima.nodes.Node body: The function's body
        :param esprima.nodes.Node params: The function's formal args
        :param env int: The ref-id to the closure environment
        :rtype JSObject:
        :return: The JSObject representing the closure
        """        
        return cls({}, body, params, env, None, False)
    
    @classmethod
    def simfct(cls, simfct : function, pure_simfct : bool =False) -> 'JSObject':
        """ 
        Build a JSObject for a simfct
        
        :param function simfct: A python function to simulate the JS function
        :param bool pure_simfct: True if the function is pure (i.e. no side effects)
        :rtype JSObject:
        :return: The JSObject representing the simfct
        """        
        return cls({}, None, None, None, simfct, pure_simfct)

    @classmethod
    def object(cls) -> 'JSObject':
        """
        Builds an empty JSObject (for object or array, for example)

        :rtype JSObject:
        :return: The JSObject
        """
        return cls({}, None, None, None, None, False)

    @staticmethod
    def add_hook(hook : List[Callable]) -> None:
        """
        Register new hook
        
        :param List[Callable] hook: The hook to add
        """
        JSObject.hooks.append(hook)

    def __init__(self, properties: Dict[Union[str, int], JSValue], body : esprima.nodes.Node = None, params : esprima.nodes.Node = None, env : Optional[int] = None, simfct : Optional[Callable] = None, pure_simfct : bool = False) -> None:
        """
        Class constructor (avoid direct use, instead use convenience functions simfct/function/closure/object)
        
        :param Dict[Union[str, int], JSValue] properties: Dictionary representing properties of the object
        :param esprima.nodes.Node body: The function's body
        :param esprima.nodes.Node params: The function's formal args
        :param env Optional[int]: The ref-id to the closure environment
        :param Optional[Callable] simfct: A python function to simulate the JS function
        :param bool pure_simfct: True if the function is pure (i.e. no side effects)
        """
        self.properties : Dict[Union[str, int], JSValue] = properties #dict listing properties of the object / array elements
        """Dictionary representing properties of the object"""

        self.body : esprima.nodes.Node = body #if function, represents the body AST
        """The function's body"""

        self.params : esprima.nodes.Node = params #if function, represents the arguments ASTs
        """The function's formal args"""

        self.env : Optional[int] = env #if function, this is the ID of object representing closure-captured environment, if any
        """The ref-id to the closure environment"""

        self.simfct : Optional[Callable] = simfct #Simulated function, if any
        """A python function to simulate the JS function"""

        self.missing_mode : MissingMode = MissingMode.MISSING_IS_UNDEF
        """The object's missing-mode (how to interpret absent properties"""

        self.fn_isexpr : bool = False
        """True if this JSObject represents an arrow-function containing only an expression"""

        self.pure_simfct : bool = pure_simfct
        """True if this simfct is pure"""

        self.tablength : Optional[int] = 0
        """Represents the array length, or None if unknown"""

    def __str__(self) -> str:
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

    def __repr__(self) -> str:
        return self.__str__()

    def __eq__(self, other) -> str:
        if type(self) != type(other):
            return False
        return self.properties == other.properties and self.body == other.body and self.params == other.params and self.env == other.env and self.simfct == other.simfct and self.missing_mode == other.missing_mode and self.tablength == other.tablength and self.fn_isexpr == other.fn_isexpr 

    def contains_top(self) -> str:
        return self.missing_mode == MissingMode.MISSING_IS_TOP or JSTop in self.properties.values()

    def is_callable(self) -> bool:
        return not (self.body is None and self.simfct is None)

    def is_simfct(self) -> bool:
        return self.simfct is not None

    def is_function(self) -> bool:
        return self.body is not None

    def is_closure(self) -> bool:
        return self.env is not None

    def closure_env(self) -> bool:
        return self.env

    def is_pure_simfct(self) -> bool:
        return self.pure_simfct

    def assign(self, other : 'JSObject') -> None:
        """
        Do object assignment

        :param JSObject other: The source JSObject        
        """
        self.properties = other.properties.copy()
        self.body = other.body
        self.params = other.params
        self.env = other.env
        self.simfct = other.simfct
        self.missing_mode = other.missing_mode
        self.tablength = other.tablength
        self.fn_isexpr = other.fn_isexpr
        self.pure_simfct = other.pure_simfct

    def clone(self) -> 'JSObject':
        c = JSObject({})
        c.assign(self)
        return c

    def set_missing_mode(self, missing_mode : MissingMode) -> None:
        """
        Sets the object's missing-mode. When we set the missing-mode to MISSING_IS_TOP, we
        remove all JSTop properties and set tablength to None

        :param MissingMode missing_mode: The new missing mode
        """
        if self.missing_mode == MissingMode.MISSING_IS_UNDEF and missing_mode == MissingMode.MISSING_IS_TOP:
            self.properties = {k: v for k,v in self.properties.items() if v is not JSTop}
            self.tablength = None
        self.missing_mode = missing_mode 
    
    def set_member(self, name : Optional[Union[str, int]], value : JSValue) -> None:
        """
        Set object member (i.e. field/attribute/property...). Also updates tablength.

        :param str name: The member name, or None to represent writing to an unknown field
        :param JSValue value: The member value
        """
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
    """
    Get object member. Tries hooks if member cannot be found.

    :param str name: The member name.
    """
    def member(self, name : str) -> JSValue:
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

class JSRef(JSValue):
    """
    Class to represent a reference. It wraps a ref-id (i.e. an integer) that allows retrieval of the referenced JSObject
    """
    def __init__(self, ref_id : int, this : Optional[int] = None) -> None:
        """
        Class constructor

        :param int ref_id: The ref-id for retrieving the referenced JSObject
        :param Optional[int] this: If the referenced JSObject is a bound function, this contains the ref-id for the "this" JSObject (otherwise, is None)
        """

        self.ref_id : int = ref_id
        """The ref-id for retrieving the referenced JSObject"""

        self._this : Optional[int] = this
        """If the referenced JSObject is a bound function, this contains the ref-id for the "this" JSObject (otherwise, is None)"""

    def __str__(self) -> str:
        if type(self._this) is int:
            return "<ref: " + str(self.ref_id) + " bound:" + str(self._this) + ">"
        else:
            return "<ref: " + str(self.ref_id) + ">"

    def __repr__(self) -> str:
        return self.__str__() 

    def __eq__(self, other) -> bool:
        if type(self) != type(other):
            return False
        return self.ref_id == other.ref_id and self._this == other._this

    def target(self) -> int:
        return self.ref_id

    def clone(self) -> 'JSRef':
        return self

    def is_bound(self) -> bool:
        return self._this is not None

    def this(self) -> Optional[int]:
        return self._this

    def __hash__(self) -> int:
        return self.ref_id.__hash__()

#TODO remplacer par une classe Maybe() ou qqch comme ca... jsp
class JSOr(JSValue):
    """
    This class represent a value with multiple, enumarated, possibilities
    """

    def __init__(self, choices : Set[JSValue]) -> None:
        """
        Class constructor
        
        :param Set[JSValue] choices: The set of possibilities for this value
        """
        self.choices : Set[JSValue] = set(choices)
        """The set of possibilities for this value"""

    def __str__(self) -> str:
        return "Or(" + ",".join([str(c) for c in self.choices]) + ")"

    def __eq__(self, other) -> bool:
        if type(self) != type(other):
            return False
        return self.choices == other.choices

    def __repr__(self) -> str:
        return self.__str__()

    def clone(self) -> 'JSOr':
        return self

