# Rhino JavaScript common grammar — expanded verified profile
#
# Target: Rhino 1.8.1-SNAPSHOT, ddaa491f42e377fd6715011c32d0828a6aaaa123.
# Every reachable syntax family was accepted by the pinned runtime through the
# Rhino harness. This remains a bounded fuzzing grammar, not full ECMAScript.
#
# Deliberately unreachable: class, async/await, array or call spread, arrow
# rest parameters, for (const ... of ...), modules, and Java-host interop.
<start> ::= <program>
<program> ::= <statementList>
<statementList> ::= (
    <statement> |
    <statement> <newline> <statementList>
)
<statement> ::= (
    <variableStatement> |
    <destructuringStatement> |
    <expressionStatement> |
    <ifStatement> |
    <whileStatement> |
    <doWhileStatement> |
    <forStatement> |
    <labeledLoop> |
    <switchStatement> |
    <tryStatement> |
    <throwStatement> |
    <functionDeclaration> |
    <generatorDeclaration> |
    <printStatement> |
    <consoleStatement> |
    <commentStatement>
)
<variableStatement> ::= (
    <declKeyword><identifier> " = " <expression> ";" |
    <mutableDeclKeyword><identifier> ";" |
    <declKeyword><identifier> " = " <arrayLiteral> ";" |
    <declKeyword><identifier> " = " <objectLiteral> ";" |
    <declKeyword><identifier> " = " <functionExpression> ";" |
    <declKeyword><identifier> " = " <arrowFunction> ";" |
    <declKeyword><declarator> ", " <declarator> ";"
)

# Any of var/let/const may declare two bindings in one statement; this rule
# previously hard-coded "var", so `let a = 1, b = 2;` -- which this runtime
# accepts -- had no derivation. Held at exactly two declarators to match
# <destructuringStatement>, which is also fixed at two.
#
# The declared name is a direct child of <declarator>, not of
# <variableStatement>, so every binding pool below must list
# *<declarator>.<identifier> alongside *<variableStatement>.<identifier>.
<declarator> ::= <identifier> " = " <expression>
<destructuringStatement> ::= (
    <declKeyword> "[" <identifier> ", " <identifier> "] = " <arrayLiteral> ";" |
    <declKeyword> "{" <identifier> "} = " <objectLiteral> ";" |
    <declKeyword> "{" <property> ": " <identifier> "} = " <objectLiteral> ";"
)
<declKeyword> ::= (
    "var " |
    "let " |
    "const "
)
<mutableDeclKeyword> ::= (
    "var " |
    "let "
)
<expressionStatement> ::= (
    <assignmentTarget> " = " <expression> ";" |
    <assignmentTarget> <compoundAssignOp> <expression> ";" |
    <identifier> "++;" |
    <identifier> "--;" |
    <callExpression> ";"
)
<assignmentTarget> ::= (
    <identifier> |
    <memberExpression>
)
<compoundAssignOp> ::= (
    " += " |
    " -= " |
    " *= " |
    " /= " |
    " %= " |
    " ||= " |
    " ??= "
)
<ifStatement> ::= (
    "if (" <booleanExpression> ") {" <statementList> "}" |
    "if (" <booleanExpression> ") {" <statementList> "} else {" <statementList> "}"
)
<whileStatement> ::= "while (" <booleanExpression> ") {" <loopBody> "}"
<doWhileStatement> ::= "do {" <loopBody> "} while (" <booleanExpression> ");"
<loopBody> ::= (
    <statementList> |
    <statementList> <newline> "break;" |
    <statementList> <newline> "continue;"
)
<forStatement> ::= (
    "for (var " <identifier> " = " <numericLiteral> "; " <booleanExpression> "; " <identifier> "++) {" <loopBody> "}" |
    "for (let " <identifier> " = " <numericLiteral> "; " <booleanExpression> "; " <identifier> "++) {" <loopBody> "}" |
    "for (var " <identifier> " in " <identifier> ") {" <loopBody> "}" |
    "for (var " <identifier> " of " <identifier> ") {" <loopBody> "}" |
    "for (let " <identifier> " of " <identifier> ") {" <loopBody> "}"
)
<labeledLoop> ::= "outer: for (var " <identifier> " = " <numericLiteral> "; " <booleanExpression> "; " <identifier> "++) {break outer;}"
<switchStatement> ::= "switch (" <expression> ") {case " <literal> ": " <statementList> " break; default: " <statementList> "}"
<tryStatement> ::= (
    "try {" <statementList> "} catch (" <identifier> ") {" <statementList> "}" |
    "try {" <statementList> "} catch {" <statementList> "}" |
    "try {" <statementList> "} catch (" <identifier> ") {" <statementList> "} finally {" <statementList> "}"
)
<throwStatement> ::= "throw new "<errorType> "(" <stringLiteral> ");"
<errorType> ::= (
    "Error" |
    "TypeError" |
    "ReferenceError" |
    "RangeError"
)
<functionDeclaration> ::= (
    "function "<identifier> "() {" <functionBody> "}" |
    "function "<identifier> "(" <parameterList> ") {" <functionBody> "}"
)
<generatorDeclaration> ::= (
    "function* "<identifier> "() {" <generatorBody> "}" |
    "function* "<identifier> "(" <parameterList> ") {" <generatorBody> "}"
)
<functionExpression> ::= (
    "function() {" <functionBody> "}" |
    "function(" <parameterList> ") {" <functionBody> "}"
)
<functionBody> ::= (
    <statementList> |
    <statementList> " return " <expression> ";" |
    "return " <expression> ";" |
    "return;"
)
<generatorBody> ::= (
    "yield " <expression> ";" |
    "yield* " <identifier> ";" |
    "yield " <expression> "; return " <expression> ";"
)
<arrowFunction> ::= (
    "() => " <expression> |
    "(" <arrowParameterList> ") => " <expression> |
    <identifier> " => " <expression> |
    "() => {" <statementList> "}" |
    "(" <arrowParameterList> ") => {" <statementList> "}"
)
<parameterList> ::= (
    <parameter> |
    <parameter> ", " <parameterList> |
    <arrowParameterList> ", ..." <identifier>
)
<arrowParameterList> ::= (
    <parameter> |
    <parameter> ", " <arrowParameterList>
)
<parameter> ::= (
    <identifier> |
    <identifier> " = " <defaultValue>
)
<defaultValue> ::= (
    <literal> |
    <identifier> |
    <arrayLiteral> |
    <objectLiteral>
)
<expression> ::= <assignmentExpression>
<commaExpression> ::= <assignmentExpression> ", " <assignmentExpression>
<assignmentExpression> ::= (
    <conditionalExpression> |
    <assignmentTarget> <compoundAssignOp> <assignmentExpression>
)
<conditionalExpression> ::= (
    <coalesceExpression> |
    <booleanExpression> " ? " <expression> " : " <expression>
)
<coalesceExpression> ::= (
    <booleanExpression> |
    <bitwiseOrExpression> " ?? " <bitwiseOrExpression>
)
<booleanExpression> ::= (
    <bitwiseOrExpression> |
    <bitwiseOrExpression> " && " <booleanExpression> |
    <bitwiseOrExpression> " || " <booleanExpression>
)
<bitwiseOrExpression> ::= (
    <bitwiseXorExpression> |
    <bitwiseXorExpression> " | " <bitwiseOrExpression>
)
<bitwiseXorExpression> ::= (
    <bitwiseAndExpression> |
    <bitwiseAndExpression> " ^ " <bitwiseXorExpression>
)
<bitwiseAndExpression> ::= (
    <equalityExpression> |
    <equalityExpression> " & " <bitwiseAndExpression>
)
<equalityExpression> ::= (
    <relationalExpression> |
    <relationalExpression> " == " <equalityExpression> |
    <relationalExpression> " != " <equalityExpression> |
    <relationalExpression> " === " <equalityExpression> |
    <relationalExpression> " !== " <equalityExpression>
)
<relationalExpression> ::= (
    <shiftExpression> |
    <shiftExpression> " > " <shiftExpression> |
    <shiftExpression> " < " <shiftExpression> |
    <shiftExpression> " >= " <shiftExpression> |
    <shiftExpression> " <= " <shiftExpression> |
    <shiftExpression> " in " <shiftExpression> |
    <shiftExpression> " instanceof " <shiftExpression>
)
<shiftExpression> ::= (
    <additiveExpression> |
    <additiveExpression> " << " <shiftExpression> |
    <additiveExpression> " >> " <shiftExpression> |
    <additiveExpression> " >>> " <shiftExpression>
)
<additiveExpression> ::= (
    <multiplicativeExpression> |
    <multiplicativeExpression> " + " <additiveExpression> |
    <multiplicativeExpression> " - " <additiveExpression>
)
<multiplicativeExpression> ::= (
    <exponentExpression> |
    <exponentExpression> " * " <multiplicativeExpression> |
    <exponentExpression> " / " <multiplicativeExpression> |
    <exponentExpression> " % " <multiplicativeExpression>
)
<exponentExpression> ::= (
    <unaryExpression> |
    <exponentBase> " ** " <exponentExpression>
)
<exponentBase> ::= (
    <primaryExpression> |
    "(" <unaryExpression> ")"
)
<unaryExpression> ::= (
    <primaryExpression> |
    "typeof " <unaryExpression> |
    "-" <unaryExpression> |
    "+" <unaryExpression> |
    "!" <unaryExpression> |
    "void " <unaryExpression> |
    "delete " <memberExpression> |
    "++" <assignmentTarget> |
    "--" <assignmentTarget> |
    <newExpression>
)
<newExpression> ::= (
    "new "<constructor> "()" |
    "new "<constructor> "(" <argumentList> ")"
)
<constructor> ::= (
    <errorType> |
    "Object" |
    "Array" |
    <identifier>
)
<primaryExpression> ::= (
    <literal> |
    <identifier> |
    "this" |
    "(" <expression> ")" |
    <arrayLiteral> |
    <objectLiteral> |
    <templateLiteral> |
    <taggedTemplate> |
    <functionExpression> |
    <arrowFunction> |
    <callExpression> |
    <memberExpression> |
    <optionalMemberExpression> |
    "(" <commaExpression> ")"
)
<literal> ::= (
    <numericLiteral> |
    <bigIntLiteral> |
    <stringLiteral> |
    <regexLiteral> |
    "true" |
    "false" |
    "null" |
    "undefined"
)
<callExpression> ::= (
    <identifier> "()" |
    <identifier> "(" <argumentList> ")" |
    <memberExpression> "()" |
    <memberExpression> "(" <argumentList> ")"
)
<memberExpression> ::= <memberBase> <memberTail>
<memberBase> ::= (
    <identifier> |
    "this" |
    <arrayLiteral> |
    <objectLiteral>
)
<memberTail> ::= (
    "." <property> |
    "[" <expression> "]" |
    "." <property> <memberTail> |
    "[" <expression> "]" <memberTail>
)
<optionalMemberExpression> ::= (
    <identifier> "?." <property> |
    <identifier> "?.[" <expression> "]" |
    <identifier> "?.()"
)
<property> ::= (
    "length" |
    "x" |
    "y" |
    "z" |
    "value" |
    "name" |
    "item" |
    "next" |
    <identifier>
)
<arrayLiteral> ::= (
    "[]" |
    "[" <expressionList> "]"
)
<objectLiteral> ::= (
    "{}" |
    "{" <propertyList> "}" |
    "{" "[" <expression> "]: " <expression> "}" |
    "{" <identifier> "}" |
    "{..." <identifier> ", " <propertyList> "}" |
    "{get "<property> "() {return " <expression> ";}}" |
    "{set "<property> "(" <identifier> ") {" <statementList> "}}" |
    "{" <property> "() {return " <expression> ";}}"
)
<argumentList> ::= (
    <expression> |
    <expression> ", " <argumentList>
)
<expressionList> ::= (
    <expression> |
    <expression> ", " <expressionList>
)
<propertyList> ::= (
    <property> ": " <expression> |
    <property> ": " <expression> ", " <propertyList>
)
<templateLiteral> ::= (
    "``" |
    "`" <templateChars> "`" |
    "`" <templateChars> "${" <identifier> "}" <templateChars> "`"
)
<taggedTemplate> ::= (
    <identifier> "``" |
    <identifier> "`" <templateChars> "`" |
    <identifier> "`" <templateChars> "${" <identifier> "}" <templateChars> "`"
)
<printStatement> ::= "print(" <printable> ");"
<consoleStatement> ::= "console.log(" <printable> ");"
<printable> ::= <expression>
<commentStatement> ::= "/* " <commentChars> " */"
<numericLiteral> ::= (
    "0" |
    <decimalInteger> |
    <decimalInteger> "." <digitSeq> |
    <underscoredDecimalInteger> |
    "0x" <hexDigitSeq> |
    "0o" <octalDigitSeq> |
    "0b" <binaryDigitSeq>
)
<bigIntLiteral> ::= (
    "0n" |
    <decimalInteger> "n" |
    <underscoredDecimalInteger> "n" |
    "0x" <hexDigitSeq> "n" |
    "0o" <octalDigitSeq> "n" |
    "0b" <binaryDigitSeq> "n"
)
<decimalInteger> ::= (
    <nonzeroDigit> |
    <nonzeroDigit> <digitSeq>
)
<underscoredDecimalInteger> ::= <decimalInteger> "_" <underscoredDigits>
<underscoredDigits> ::= (
    <digitSeq> |
    <digitSeq> "_" <underscoredDigits>
)
<digitSeq> ::= (
    <digit> |
    <digit> <digitSeq>
)
<hexDigitSeq> ::= (
    <hexDigit> |
    <hexDigit> <hexDigitSeq>
)
<octalDigitSeq> ::= (
    <octalDigit> |
    <octalDigit> <octalDigitSeq>
)
<binaryDigitSeq> ::= (
    <binaryDigit> |
    <binaryDigit> <binaryDigitSeq>
)
<digit> ::= (
    "0" |
    "1" |
    "2" |
    "3" |
    "4" |
    "5" |
    "6" |
    "7" |
    "8" |
    "9"
)
<nonzeroDigit> ::= (
    "1" |
    "2" |
    "3" |
    "4" |
    "5" |
    "6" |
    "7" |
    "8" |
    "9"
)
<hexDigit> ::= (
    <digit> |
    "a" |
    "b" |
    "c" |
    "d" |
    "e" |
    "f" |
    "A" |
    "B" |
    "C" |
    "D" |
    "E" |
    "F"
)
<octalDigit> ::= (
    "0" |
    "1" |
    "2" |
    "3" |
    "4" |
    "5" |
    "6" |
    "7"
)
<binaryDigit> ::= (
    "0" |
    "1"
)
<regexLiteral> ::= (
    "/"<regexPattern>"/" |
    "/"<regexPattern>"/"<regexFlags>
)
<regexPattern> ::= (
    <regexTerm> |
    <regexTerm> <regexPattern>
)
<regexTerm> ::= (
    <regexAtom> |
    <regexAtom> <regexQuantifier>
)
<regexAtom> ::= (
    <regexTextChar> |
    "." |
    "[" <regexClassChars> "]"
)
<regexQuantifier> ::= (
    "*" |
    "+" |
    "?"
)
<regexFlags> ::= (
    "g" |
    "i" |
    "m" |
    "gi" |
    "gm" |
    "im" |
    "gim"
)
<regexTextChar> ::= (
    <alphabetic> |
    <digit> |
    "_" |
    "-"
)
<regexClassChars> ::= (
    <regexClassChar> |
    <regexClassChar> <regexClassChars>
)
<regexClassChar> ::= (
    <alphabetic> |
    <digit> |
    "_" |
    "-"
)
<identifier> ::= (
    <identifierStart> |
    <identifierStart> <identifierTail>
)
<identifierTail> ::= (
    <identifierPart> |
    <identifierPart> <identifierTail>
)
<identifierStart> ::= (
    <alphabetic> |
    "_" |
    "$"
)
<identifierPart> ::= (
    <identifierStart> |
    <digit>
)
<alphabetic> ::= (
    "a" |
    "b" |
    "c" |
    "d" |
    "e" |
    "f" |
    "g" |
    "h" |
    "i" |
    "j" |
    "k" |
    "l" |
    "m" |
    "n" |
    "o" |
    "p" |
    "q" |
    "r" |
    "s" |
    "t" |
    "u" |
    "v" |
    "w" |
    "x" |
    "y" |
    "z" |
    "A" |
    "B" |
    "C" |
    "D" |
    "E" |
    "F" |
    "G" |
    "H" |
    "I" |
    "J" |
    "K" |
    "L" |
    "M" |
    "N" |
    "O" |
    "P" |
    "Q" |
    "R" |
    "S" |
    "T" |
    "U" |
    "V" |
    "W" |
    "X" |
    "Y" |
    "Z"
)
<stringLiteral> ::= (
    "\"\"" |
    "\"" <stringChars> "\"" |
    "''" |
    "'" <stringChars> "'"
)
<stringChars> ::= (
    <stringChar> |
    <stringChar> <stringChars>
)
<stringChar> ::= (
    <alphabetic> |
    <digit> |
    " " |
    "_" |
    "-" |
    "." |
    "," |
    ":" |
    ";" |
    "!" |
    "?" |
    "(" |
    ")" |
    "[" |
    "]" |
    "{" |
    "}" |
    "=" |
    "+" |
    "*" |
    "/" |
    "@" |
    "#" |
    "$" |
    "%" |
    "&" |
    "|" |
    "<" |
    ">"
)
<templateChars> ::= (
    <templateChar> |
    <templateChar> <templateChars>
)
<templateChar> ::= (
    <alphabetic> |
    <digit> |
    " " |
    "_" |
    "-" |
    "." |
    "," |
    ":" |
    ";" |
    "!" |
    "?" |
    "(" |
    ")" |
    "[" |
    "]" |
    "{" |
    "}" |
    "=" |
    "+" |
    "*" |
    "/" |
    "@" |
    "#" |
    "%" |
    "&" |
    "|" |
    "<" |
    ">"
)
<commentChars> ::= (
    <commentChar> |
    <commentChar> <commentChars>
)
<commentChar> ::= (
    <alphabetic> |
    <digit> |
    " " |
    "_" |
    "-" |
    "." |
    "," |
    ":" |
    ";" |
    "!" |
    "?" |
    "(" |
    ")" |
    "[" |
    "]" |
    "{" |
    "}" |
    "=" |
    "+" |
    "@" |
    "#" |
    "$" |
    "%" |
    "&" |
    "|" |
    "<" |
    ">"
)
<newline> ::= "\n"

# ============================================================================
#  CONSTRAINTS — Rhino declaration/use safety (Fandango set-membership form)
#
#  Fandango selectors validate derivation-tree membership, not source order.
#  These rules therefore require a name to be declared somewhere in the
#  generated program. The Rhino harness remains the authority for runtime
#  acceptance and temporal declaration-before-use probes.
# ============================================================================

# Reserved and harness-provided spellings cannot be generated as identifiers.
where all(
  str(v) not in {"var", "let", "const", "if", "else", "for", "while",
                 "do", "function", "return", "switch", "case", "break",
                 "default", "try", "catch", "finally", "throw", "new",
                 "typeof", "void", "delete", "in", "of", "true", "false",
                 "null", "undefined", "this", "print", "console", "Object",
                 "Array", "Error", "TypeError", "ReferenceError", "RangeError"}
  for v in *<identifier>
)

# Keep names unique across unambiguous declaration sites. This deliberately
# forbids otherwise legal shadowing so generated `let`/`const` bindings cannot
# collide in the same generated scope.
where len({str(v) for v in [*<variableStatement>.<identifier>, *<declarator>.<identifier>, *<destructuringStatement>.<identifier>, *<functionDeclaration>.<identifier>, *<generatorDeclaration>.<identifier>, *<parameter>.<identifier>, *<tryStatement>.<identifier>]}) == len([*<variableStatement>.<identifier>, *<declarator>.<identifier>, *<destructuringStatement>.<identifier>, *<functionDeclaration>.<identifier>, *<generatorDeclaration>.<identifier>, *<parameter>.<identifier>, *<tryStatement>.<identifier>])

# Values used directly as primary expressions must be introduced by a variable,
# destructuring binding, function, parameter, loop, or catch declaration.
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<primaryExpression>.<identifier>
)

# Direct assignment targets must use an introduced name.
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<assignmentTarget>.<identifier>
)

# `x++;` and `x--;` place the name as a direct child of <expressionStatement>,
# not of <assignmentTarget>, so the clause above never saw them. Measured on a
# 30-input sample: 6 of 30 programs failed with ReferenceError from exactly
# this hole. The other <expressionStatement> alternatives route their names
# through <assignmentTarget> or <callExpression>, so this selector picks up the
# increment/decrement targets only.
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<expressionStatement>.<identifier>
)

# Object-literal shorthand `{b}` and object spread `{...b, ...}` are reads of
# `b`, not property names. 3 of the same 30 programs emitted an unbound
# shorthand name. Property keys sit under <property> and are deliberately not
# constrained here.
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<objectLiteral>.<identifier>
)

# Object/array bases and optional-member bases must be introduced values.
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<memberBase>.<identifier>
)
where all(
     (v in *<variableStatement>.<identifier>)
  or (v in *<declarator>.<identifier>)
  or (v in *<destructuringStatement>.<identifier>)
  or (v in *<functionDeclaration>.<identifier>)
  or (v in *<generatorDeclaration>.<identifier>)
  or (v in *<parameter>.<identifier>)
  or (v in *<forStatement>.<identifier>)
  or (v in *<tryStatement>.<identifier>)
  for v in *<optionalMemberExpression>.<identifier>
)

# A simple call or custom `new Name(...)` must name a declared function.
where all(
  (f in *<functionDeclaration>.<identifier>) or (f in *<generatorDeclaration>.<identifier>)
  for f in *<callExpression>.<identifier>
)
where all(
  (f in *<functionDeclaration>.<identifier>) or (f in *<generatorDeclaration>.<identifier>)
  for f in *<constructor>.<identifier>
)
