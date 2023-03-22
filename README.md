# JS Analyzer

This is a project to analyze obfuscated JS code using abstract interpretation and optimizations similar to compiler optimizations

This is a work in progress / proof of concept, it is very incomplete. A lot of
essential things are incorrectly handled or unhandled (exceptions, some OOP
stuff, async functions, etc), also it is not very optimized (for analysis speed).

## Setup

It requires `python3` or `pypy3` with module `esprima`. The usage of `pypy3` is
recommended for performance reasons.

Before use, you must type `make` in the project directory in order to compile jseval.so 

## Usage

```bash
./do.sh <input JS file without the .js extension>
```

It will produce a `yourfile-out.js`

## JSAnalyzer in action

This is an excerpt from a real obfuscated malware "as is" (it has only been automatically indented). Strings are obfuscated and replaced by calls to functions, and control flow has been flattened:
![Obfuscated code](https://klemm.7un.net/fileshare/obf/webhook1.png)

After processing by JSAnalyzer, the strings are recovered, and the control flow is clarified. We see that the code search for running Discords:
![Processed code](https://klemm.7un.net/fileshare/obf/webhook2.png)

This is an excerpt for another obfuscated JS served on some website. Strings are encrypted in RC4, there is control flow flatteing, and eval() calls. 
![Obfuscated code](https://klemm.7un.net/fileshare/obf/site1.png)

JSAnalyzer interprets automatically the RC4 decryption, emulates the eval() calls and clarifies the control flow. This excerpt show the exchange of requets with the server:
![Processed code](https://klemm.7un.net/fileshare/obf/site2.png)

## How it works ?

The obfuscated JS is processed in 4 steps

 * Parsing the JS into an Abstract Syntax Tree (AST) (this is done by the esprima module)
 * Abstract Interpretation on the AST to find out constant expressions (done by analyze.py)
 * Code Transformations on the AST, this is similar to compiler optimizations (done by transform.py)
 * Transformed JS output (done by prettyprint.js using the escodegen module)

![Workflow](https://klemm.7un.net/fileshare/obf/workflow.png)

## Abstract interpretation

### The general idea

This works by analyzing the program to identify constant expressions (that is,
expressions for which the value can be determined without actually executing
the program). For instance, let's consider the following example:

```js
x = 10;
if (x == 10) {
	y = 32 + x;
}

console.log(x);  /* x is constant (10) */
console.log(y);  /* y is constant (42) */

if (Math.random()*10 < 5) {
	a = 10;
	b = 20;
	console.log(b); /* b is constant (20) */
} else {
	a = 10;
	b = 30;
	console.log(b); /* b is constant (30) */
}
console.log(a); /* a is constant (10) */
console.log(b); /* b is not constant (it cannot be determined whether b is 20 or 30 without running the program */
```

JSanalyzer will replace each constant expression with its value, resulting in
this output:

```js

x = 10
if (true){
  y = 42
}
console.log(10)
console.log(42)
if (Math.random() * 10 < 5){
  a = 10
  b = 20
  console.log(20)
}
else
{
  a = 10
  b = 30
  console.log(30)
}
console.log(10)
console.log(b)
```


### Constant expression detection

JSanalyzer detects constant expressions by performing an abstract
interpretation of the program under the constants domain. 

It is basically the same thing as interpreting the program normally, except
that each expression is evaluated as an `abstract value`.  An abstract value is
either a concrete value (i.e. a number, a string, ...) or a special value named
`Top`, that essentially means that the value of the expression cannot be
determined withour running the program. `Top` values are generated when the
analyzer encounters something that cannot be determined statically (for
instance, a statement involving I/O, network operation, ...), and is propagated
in the various computations.

When execution path diverges based on an unknown condition (for instance, an
`if` with a `Top` test condition), the analyzer will process each path
separately, and perform state merging afterwards. State merging keeps variables
that have the same value along each paths, and set others to `Top`.

The loop are unrolled as long as loop condition is true, up to a configurable
number of iterations (default: 1000).

## Project code organization

The project is organized in several files:
 * `analyzer.py`: main program
 * `config.py`: user-editable configuration file
 * `abstract.py`: defines classes for abstract value and their operations: JSTop (Top), JSClosure (closure and functions), JSObject (objects and arrays), JSRef (references to object and arrays), JSUndefNaN (represents undefined or NaN), JSPrimitive (represents a primitive value such as number or string), and JSSimFct (built-in JS function coded in python)
 * `plugin_manager.py`: defines the plugin manager. Plugins live in the `plugins/` subdirectory, and can define behavior for unary and binary operators, as well as built-in JS functions.
 * `interpreter.py`: defines the "main" part of the interpreter. It processes the abstract syntax tree (AST), and interprets the programs using abstract values for each AST element.
 * `output.py`: defines the pretty-printer / output generator. It is executed after the interpreter, and outputs the result JS, where each constant expression is replaced with its value.


## Code Transforms

The used optimizations are common, and found in any good compilation book (dead code/variable elimination, unrolling, etc)
