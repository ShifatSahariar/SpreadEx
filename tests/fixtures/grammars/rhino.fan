# -------------------- RHINO  (FOR FANDANGO - NO CONSTRAINTS) --------------------

# === Program Structure ===
<start> ::= <statementSeq>{1,4}
<statementSeq> ::= <statement><newline> | <statement><newline> <statementSeq>

# === Statement Types ===
<statement> ::= (
  <variableStatement> |
  <array_init> |
  <object_init> |
  <expressionStatement> |
  <ifStatement> |
  <iterationStatement> |
  <switchStatement> |
  <tryStatement> |
  <printStatement> |
  <arrayAccessStatement> |
  <objectAccessStatement> |
  <functionDeclaration>
)

# === Declarations ===
<variableStatement> ::= (
  "var " <IDENT_NUM> " = " <numericExp> ";" <newline> |
  "var " <IDENT_STR> " = " <STRING> ";" <newline>
)
<array_init> ::= "var " <IDENT_ARR> " = " "[" <numericExp> (", " <numericExp>)* "]" ";"
<object_init> ::= "var " <IDENT_OBJ> " = " "{" <prop_init> (", " <prop_init>)* "}" ";"
<prop_init> ::= <PROP_NAME> " : " <numericExp>

# === Expressions ===
<numericExp> ::= (<NUMBER> 
  | <IDENT_NUM> 
  | <IDENT_NUM> " + " <IDENT_NUM>
  | <IDENT_NUM> " - " <IDENT_NUM>
  | <IDENT_NUM> " * " <IDENT_NUM>
  | <IDENT_NUM> " / " <IDENT_NUM>
  | "(" <numericExp> ")"
  | "Number(" <STRING> ")"
  | <arrayAccess>
  | <memberAccess_num>)


<booleanExp> ::= (<IDENT_NUM> " > " <IDENT_NUM> | <IDENT_NUM> " < " <IDENT_NUM> |
  <IDENT_NUM> " == " <IDENT_NUM> | <IDENT_NUM> " != " <IDENT_NUM> |
  "(" <booleanExp> ")" | <booleanExp> " && " <booleanExp> | <booleanExp> " || " <booleanExp>)

<stringExp> ::= (<STRING> | <IDENT_STR> | <IDENT_STR> " + " <IDENT_STR> |
  "String(" <numericExp> ")" | "(" <stringExp> ")" | <memberAccess_str>)

<callExp> ::= (<IDENT_FUN> "(" <argList>? ")" | <IDENT_OBJ> "." <IDENT_FUN> "(" <argList>? ")")
<argList> ::= <arg> (", " <arg>)* 
<arg> ::= <numericExp> | <stringExp>

# === Member and Access ===
<memberAccess> ::= <IDENT_OBJ> "." <PROP_NAME>
<memberAccess_num> ::= <IDENT_OBJ> "." <NUM_PROP>
<memberAccess_str> ::= <IDENT_OBJ> "." "name"
<arrayAccess> ::= <IDENT_ARR> "[" (<NUMBER> | <IDENT_NUM>) "]"

# === Statements and Control ===
<expressionStatement> ::= <assignmentStmt> | <callStmt> | <incdecStmt>
<assignmentStmt> ::= <IDENT_NUM> " = " <numericExp> ";" | <IDENT_STR> " = " <stringExp> ";"
<incdecStmt> ::= <IDENT_NUM> "++" ";" | <IDENT_NUM> "--" ";"
<callStmt> ::= <callExp> ";"
<printStatement> ::= "print(" <printable> ")" ";"
<printable> ::= <numericExp> | <stringExp> | <IDENT_NUM> | <IDENT_STR>

<ifStatement> ::= (
  "if" "(" <booleanExp> ")" "{" <simpleStatementList> "}" |
  "if" "(" <booleanExp> ")" "{" <simpleStatementList> "}" "else" "{" <simpleStatementList> "}"
)

<iterationStatement> ::= (
  "while" "(" <booleanExp> ")" "{"<newline> <simpleStatementList> "}" |
  "for" "(" "var " <IDENT_NUM> " = " <NUMBER> "; " <booleanExp> "; " <IDENT_NUM> "++" ")" "{"<newline> <simpleStatementList> "}"
)

<switchStatement> ::= "switch" "(" <IDENT_NUM> ")" "{" <switchBody> "}"
<switchBody> ::= <caseBlock> "default: " <simpleStatementList>
<caseBlock> ::= ("case " <NUMBER> ": " <simpleStatementList> "break;" <newline> |
                 "case " <NUMBER> ": " <simpleStatementList> "break;" <newline> <caseBlock>)


<tryStatement> ::= (
  "try" "{" <simpleStatementList> "}" "catch" "(" <IDENT_ERR> ")" "{" <simpleStatementList> "}" |
  "try" "{" <simpleStatementList> "}" "catch" "(" <IDENT_ERR> ")" "{" <simpleStatementList> "}" "finally" "{" <simpleStatementList> "}"
)

<throwStatement> ::= "throw new " <ERR_TYPE> "(" <STRING> ")" ";"
<objectAccessStatement> ::= <memberAccess> ";"
<arrayAccessStatement> ::= <arrayAccess> ";"

# === Functions ===
<functionDeclaration> ::= "function " <IDENT_FUN> "(" <paramList>? ")" "{" <functionBody> "}"
<paramList> ::= <IDENT_NUM> (", " <IDENT_NUM>){1,4} 
<functionBody> ::= <simpleStatementList> <newline> <returnMaybe>
<returnMaybe> ::= "return " <numericExp> ";" | "return;" | ""
<simpleStatementList> ::= <simpleStatement> | <simpleStatement> <newline> <simpleStatementList>
<simpleStatement> ::= <coreStatements>{1,2} <throwStatement>{0,1}

<coreStatements> ::= (
    <variableStatement> |
    <expressionStatement> |
    <printStatement> |
    <arrayAccessStatement> |
    <objectAccessStatement>
)
# === Tokens ===
<newline> ::= "\n"
<NUMBER>  ::= r'\d{1}'
<STRING> ::= r'"[A-Za-z0-9 ]{5}"'
<IDENT_NUM> ::= r'[A-Za-z]{1,2}'
<IDENT_STR> ::= r'[A-Za-z]{1,2}'
<IDENT_ARR> ::= "arr" | "nums" | "vals" | "data" | "list"
<IDENT_OBJ> ::= "obj" | "record" | "point" | "config" | "state"
<IDENT_FUN> ::= "f" | "g" | "compute" | "process" | "handle"
<IDENT_ERR> ::= "e" | "err"
<PROP_NAME> ::= "length" | "x" | "y" | "z" | "value"
<NUM_PROP> ::= "length" | "x" | "y" | "z" | "value"
<ERR_TYPE> ::= "Error" | "TypeError" | "RangeError" | "ReferenceError"

