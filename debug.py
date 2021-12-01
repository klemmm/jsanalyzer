
debug_flag = False
def set_debug(flag):
    global debug_flag
    debug_flag = flag

def debug(*args, **kwargs):
    if debug_flag:
        print(*args, **kwargs)
