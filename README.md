# JS Analyzer

This is a project to analyze obfuscated JS code using abstract interpretation.

It requires `python3` or `pypy3` with module `esprima`. The usage of `pypy3` is recommended for performance reasons.

This is a work in progress, a lot of essential things are missing, including but not limited to:
 * Exceptions handling
 * OOP stuff (classes, etc)
 * async functions
 * a lot of operators and built-in functions are not handled correctly, or not handled at all... 


## Usage

```bash
./analyze.py <input JS file> <output JS file>
```

## How it works

This works by analyzing the program to identify constant expressions (that is, expressions for which the
value can be determined without actually executing the program). For example:

```

```

