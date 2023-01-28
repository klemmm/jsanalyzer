debug=False #Various debug info

max_iter = 100000 #Stop loop unrolling after that much iterations
max_recursion = 10 #Stop inlining after that amount of recursion depth
max_unroll_ratio = 2.0 #Max acceptable unrolled_size/original_size ratio
simplify_function_calls = True
simplify_expressions = True
simplify_control_flow = True
use_or = True
use_unify = True
use_filtering_if = True
use_filtering_err = True
remove_dead_code = True

#List of enabled plugins
enabled_plugins = [
    "default",
]

delete_unused = True #Delete unused data from states (Performance will be really bad if you set this to False)
clean_top_objects = False #Delete objects that contain only top value
console_enable = True #Show expressions passed to console.log
process_not_taken = False #workaround for probably incorrect boolean evaluation
merge_switch = False #force switch discriminant to be JSTop
regexp_rename = ['_0x', '............................', '_____*']
rename_length = 3

max_loop_context = 32
max_loop_context_nesting = 1

