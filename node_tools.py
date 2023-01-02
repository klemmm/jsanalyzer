import esprima

annotations = {}
nodes = {}
node_id = 0

def mark_node(node):
    global node_id
    if node.node_id is None:
        node.node_id = node_id
        annotations[node_id] = {}
        nodes[node_id] = node
        node_id += 1        

def get_ann(node, name, default=None):
    mark_node(node)
    try:
        return annotations[node.node_id][name]
    except KeyError:
        return default

def set_ann(node, name, value):
    mark_node(node)
    annotations[node.node_id][name] = value

def del_ann(node, name):
    mark_node(node)
    del annotations[node.node_id][name]


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

def clear_ann(name):
        for n in annotations.keys():
            if name in annotations[n]:
                del annotations[n][name]

def node_copy(node):
    if isinstance(node, esprima.nodes.Node):
        nc = esprima.nodes.Node()
        for k in node.__dict__.keys():
            if k == "notrans_static_value":
                continue
            nc.__dict__[k] = node_copy(node.__dict__[k])
        return nc
    elif isinstance(node, list):
        lc = []
        for e in node:
            lc.append(node_copy(e))
        return lc
    else:
        return node     
