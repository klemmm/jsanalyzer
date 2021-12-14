# JS Analyzer

This is a project to analyze obfuscated JS code using abstract interpretation.

It requires python3 with module `esprima`

This is a work in progress, a lot of essential things are missing, including but not limited to:
 * Exceptions handling
 * OOP stuff (classes, etc)
 * async functions
 * a lot of operators and built-in functions are not handled correctly, or not handled at all... 


## Usage

```bash
./analyze.py <input JS file> <output JS file>`
```
