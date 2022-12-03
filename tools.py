class Try(object):
    def __init__(self, site, args):
        self.site = site
        self.args = args

class Raise(object):
    def __init__(self, site):
        self.site = site

class Except(object):
    def __init__(self, site):
        self.site = site

def call(fn, *args):
    stack = [fn(*args)]
    result = None
    while len(stack) > 0:
        current = stack[-1]
        if isinstance(current, Try):
            current = current.args

        try:
            yielded = current.send(result)
            if isinstance(yielded, Raise):
                found = False
                while not found:
                    frame = stack.pop()
                    if isinstance(frame, Try):
                        found = True
                        break
                assert found
                result = Except(yielded.site)
            else:
                if isinstance(yielded, Try):
                    yielded.args = yielded.args[0](*(yielded.args[1:]))
                    stack.append(yielded)
                else:
                    stack.append(yielded[0](*(yielded[1:])))
                result = None
        except StopIteration as e:
            stack.pop()
            result = e.value
    return result
