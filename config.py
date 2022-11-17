debug=False #Various debug info

#List of enabled plugins
enabled_plugins = [
    "default",
]

max_iter = 100000 #Stop loop unrolling after that much iterations
max_recursion = 10 #Stop inlining after that amount of recursion depth

delete_unused = True #Delete unused data from states (Performance will be really bad if you set this to False)

console_enable = True #Show expressions passed to console.log

inlining = True

process_not_taken = True #workaround for probably incorrect boolean evaluation

memoize = ['_0x4759', '_0x27b9']

regexp_rename = ['_0x']
rename_length = 3

