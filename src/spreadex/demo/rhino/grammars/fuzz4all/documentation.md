# Rhino 1.8.1

Rhino is an ECMAScript engine written in Java. The pinned build
(1.8.1-SNAPSHOT, `ddaa491f`) is embedded as a script host: the harness compiles
one standalone source file and evaluates it once, top to bottom, in a single
global scope. There is no module loader, no event loop and no host object graph
beyond the two output functions the embedding installs. A script's observable
result is whatever it prints before it either runs off the end or terminates
with an uncaught exception.

## Execution model

Evaluation happens in **sloppy mode**; the embedding does not opt the script
into strict mode, and there is no directive prologue in effect. Two consequences
matter more than the rest. Assigning to a `const` binding after initialization
does not throw — the assignment is silently discarded and the binding keeps its
original value. Assigning to an undeclared name does not throw either; it
creates a property on the global object. Both make a program *look* like it is
exercising a behaviour it is not.

Function declarations are hoisted in full, so a function may be called textually
above its declaration. `var` declarations are hoisted without their
initializers and read as `undefined` until the assignment executes.

`let` and `const` behave less like the standard than their names suggest on this
build, and the differences are easy to mistake for a bug in the script. There is
**no temporal dead zone**: reading a `let` or `const` binding above its own
declaration yields `undefined` instead of throwing, in script, block and
function scope alike. `let` is block scoped — reading it after its block closes
throws a `ReferenceError` — but `const` is **not**, and remains readable after
its block ends. Redeclaring a `let` binding in the same block is a syntax error
and rejects the whole script at compile time, before any of it runs.

## Values and coercion

The primitive types are number (IEEE-754 double), BigInt, string, boolean,
`null`, `undefined` and symbol; everything else is an object. Numeric literals
may be decimal, hexadecimal (`0x`), octal (`0o`) or binary (`0b`), and may carry
`_` digit separators; appending `n` makes a BigInt. BigInt and number do not mix
under arithmetic — `1n + 1` is a `TypeError` — though they compare with `==`.

`+` is overloaded: if either operand is a string after primitive conversion it
concatenates, otherwise it adds. The other arithmetic operators always coerce to
number, so `"3" * "4"` is `12` while `"3" + 4` is `"34"`. `==` applies coercion
across types, `===` does not, and both treat `NaN` as unequal to itself. The
falsy values are `false`, `0`, `-0`, `0n`, `""`, `null`, `undefined` and `NaN`.
`&&` and `||` return one of their operands rather than a boolean, `??` returns
the right operand only for `null` and `undefined`, and `?.` short-circuits the
whole member chain to `undefined` when the base is nullish.

## Operators

Precedence runs, loosest to tightest: assignment and the compound forms
(`+= -= *= /= %= ||= ??=`), the conditional `?:`, `??`, `||`, `&&`, bitwise
`| ^ &`, equality, relational (including `in` and `instanceof`), shifts
(`<< >> >>>`), additive, multiplicative, `**`, then unary
(`typeof - + ! void delete ++ --`). `**` is right-associative, and its left
operand may not be an unparenthesized unary expression — `-2 ** 2` is a syntax
error, `(-2) ** 2` is not. The bitwise and shift operators coerce to 32-bit
integers, except `>>>`, which is unsigned and therefore yields a non-negative
result.

## Statements

`if`/`else`, `while`, `do`/`while`, three-clause `for`, `for-in`, `for-of`,
`switch` with `case`/`default` fallthrough, and `try`/`catch`/`finally` are all
supported, as are labelled statements with `break label` and `continue label`.
`for-in` iterates enumerable string keys, including inherited ones, and yields
array indices as strings; `for-of` iterates a value's iterator and yields
elements. `catch` may omit its binding. A `finally` block runs on both the
normal and the exceptional path, and a `return` inside it overrides a pending
one.

## Functions, objects and text

Functions come as declarations, expressions, arrow functions and generators.
Parameters may carry defaults and a trailing rest parameter; an arrow with a
single plain parameter may omit the parentheses, and an arrow whose body is an
expression returns it implicitly. Arrows have no `this`, `arguments` or
`prototype` of their own. Generators declared with `function*` produce an
iterator: `yield` suspends and surrenders a value, `yield*` delegates to another
iterable, and `return` sets the final result.

Object literals support shorthand properties, computed keys, getters, setters,
method shorthand and spread of another object's own enumerable properties.
Property access is `.name`, `[expr]`, or the optional forms `?.name`, `?.[expr]`
and `?.()`. Arrays are objects with a live `length`, and reading a missing index
gives `undefined` rather than throwing. Template literals interpolate with
`${...}` and may span lines; a tagged template passes the literal chunks and the
interpolated values to the tag function instead of building a string. Regular
expression literals accept the `g`, `i` and `m` flags.

## Errors and output

`throw` accepts any value. The built-in constructors relevant here are `Error`,
`TypeError`, `ReferenceError` and `RangeError`; an uncaught throw ends the
script and the harness records it as a runtime failure.

Unbounded recursion is not recoverable. It exhausts the Java host with an
`OutOfMemoryError` rather than raising a catchable JavaScript exception, so a
`try`/`catch` around the call does not survive it and the process terminates.
Unbounded loops are likewise ended by the harness timeout, not by the engine.

The embedding installs exactly two output functions: `print(value)` and
`console.log(value)`. Both stringify their argument and emit one line.

## Target restrictions

This is standalone script mode on a pinned build. Classes, modules, `import`
and `export`, `async`/`await`, Java interoperation, array and call-argument
spread, arrow rest parameters, `for (const ... of ...)`, browser APIs, Node.js
APIs and Rhino shell-only helpers are all outside this embedding.
