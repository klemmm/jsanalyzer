import inspect

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
    stack = [[fn, *args]]
    result = None
    while len(stack) > 0:
        current = stack[-1]
        if isinstance(current, Try):
            current = current.args

        if inspect.isgeneratorfunction(current[0]):
            current[0] = current[0](*current[1:])
            result = None
        elif inspect.isgenerator(current[0]):
            try:
                yielded = current[0].send(result)
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
                    stack.append(yielded)
            except StopIteration as e:
                stack.pop()
                result = e.value
        else:
            result = stack[-1][0](*stack[-1][1:])
            stack.pop()
    return result
