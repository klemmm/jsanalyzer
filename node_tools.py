import esprima
from abstract import JSPrimitive

annotations = {}
nodes = {}
node_id = 0

def mark_node(node):
    global node_id
    if node.node_id is None:
        node.node_id = node_id
        node_id += 1

    if node.node_id not in nodes: 
        annotations[node.node_id] = {}
        nodes[node.node_id] = node

def get_ann(node, name, default=None):
    mark_node(node)
    try:
        return annotations[node.node_id][name]
    except KeyError:
        return default

def set_ann(node, name, value):
    mark_node(node)
    if node.node_id == 14:
        pass
        #print("SET: ", node.node_id, name)
    annotations[node.node_id][name] = value

def del_ann(node, name):
    mark_node(node)
    if node.node_id == 14:
        pass
        #print("DEL: ", node.node_id, name)
    try:
        del annotations[node.node_id][name]
    except KeyError:
        pass


def node_from_id(node_id):
    return nodes[node_id]

def id_from_node(node):
    mark_node(node)
    return node.node_id


def dump_ann(name):
    for n in annotations.keys():
        for a in annotations[n].keys():
            if a == name:
                print(name, n, "-->", annotations[n][a]) 

def copy_all_ann(dst, src, skip=[]):
    for k in annotations[src.node_id].keys():
        if k not in skip:
            annotations[dst.node_id][k] = annotations[src.node_id][k]

def clear_ann(name):
        for n in annotations.keys():
            if name in annotations[n]:
                del annotations[n][name]

def node_copy(node, ann_skip=[], mapping=None):
    if isinstance(node, esprima.nodes.Node):
        nc = esprima.nodes.Node()
        for k in node.__dict__.keys():
            if k == "notrans_static_value" or k == "node_id":
                continue
            nc.__dict__[k] = node_copy(node.__dict__[k], ann_skip, mapping)
        nc.node_id = None
        mark_node(nc)
        if node.node_id is None:
            mark_node(node)
        if mapping is not None:
            mapping[nc.node_id] = node.node_id
      
        copy_all_ann(nc, node, ann_skip)


        return nc
    elif isinstance(node, list):
        lc = []
        for e in node:
            lc.append(node_copy(e, ann_skip, mapping))
        return lc
    else:
        return node

def node_assign(dst, src, keep=[]):
    saved = {}
    for k in keep:
        saved[k] = get_ann(dst, k)
    src_copy = node_copy(src, keep)
    dst.__dict__ = src_copy.__dict__
    for k in keep:
        set_ann(dst, k, saved[k])

def mark_node_recursive(node):
    if isinstance(node, esprima.nodes.Node):
        for k in node.__dict__.keys():
            mark_node_recursive(node.__dict__[k])
        mark_node(node)
    elif isinstance(node, list):
        for e in node:
            mark_node_recursive(e)


def save_annotations():
    return (annotations, nodes, node_id) 

def load_annotations(_annotations, _nodes, _node_id):
    global annotations, nodes, node_id
    annotations = _annotations
    nodes = _nodes
    node_id = _node_id
    

def node_equals(n1, n2):
    if type(n1) is not type(n2):
        return False
    if isinstance(n1, esprima.nodes.Node):
        for k in n1.__dict__.keys():
            if not node_equals(n1.__dict__[k], n2.__dict__[k]) and k != "node_id" and k != "site": #TODO site ann                
                return False
        if get_ann(n1, "static_value") != get_ann(n2, "static_value"):
            del_ann(n1, "static_value")
        return True
    elif isinstance(n1, list):        
        for i in range(len(n1)):
            if not node_equals(n1[i], n2[i]):
                return False            
        return True
    else:
        return n1 == n2
