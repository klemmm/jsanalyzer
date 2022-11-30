import inspect

def call(fn, *args):
    stack = [[fn, *args]]
    result = None
    while len(stack) > 0:
        if inspect.isgeneratorfunction(stack[-1][0]):
            stack[-1][0] = stack[-1][0](*stack[-1][1:])
            result = None
        elif inspect.isgenerator(stack[-1][0]):
            try:
                callee = stack[-1][0].send(result)
                stack.append(callee)
            except StopIteration as e:
                stack.pop()
                result = e.value
        else:
            result = stack[-1][0](*stack[-1][1:])
            stack.pop()
    return result
