// JavaBASIC 1.0 Grammarinator profile.
//
// This is the ANTLR4 rendering of the executable immediate-mode profile.  It
// intentionally models one buffered REPL transcript: a LET initialization,
// zero or more ordinary lines, a final PRINT line, and bye.  Stored program
// lines and RUN are documented by the common BNF but are deferred until the
// harness can submit lines interactively.
grammar basic;

start : immediateSession EOF ;

immediateSession
    : letLine NEWLINE sessionLine* printLine NEWLINE BYE NEWLINE?
    ;

letLine : 'LET ' variableOrArray equals valueExpression ;
printLine : 'PRINT ' printItems | '? ' printItems ;
sessionLine : immediateLine NEWLINE | storedLine NEWLINE ;

// Stored lines.  JavaBASIC loads and fully parses a line-numbered line but
// never executes it under the buffered harness, so this is the only way to
// reach the stored-only statement parsers (GOTO, GOSUB, RETURN, ON, END, STOP,
// INPUT, and the `THEN <line>` form of IF).  Nothing executes them, so they
// carry no runtime obligation: dangling targets, repeated or out-of-order line
// numbers and split FOR/NEXT are all accepted (verified against the
// interpreter).  RUN is still never emitted.
storedLine : lineNumber ' ' storedStatementLine ;
lineNumber : positiveInteger ;
// ON, GOTO, RETURN, END and `IF c THEN <line>` consume the rest of their line
// and may only appear last: `ON e GOTO n : ...` fails with "LINE numbers should
// be separated by commas" and the others with "extra input beyond statement
// end".  GOSUB, STOP, INPUT and NEXT chain normally.
storedStatementLine
    : storedChainStatement
    | storedTailStatement
    | storedChainStatement statementSeparator storedStatementLine
    ;
storedChainStatement
    : ordinaryStatement
    | gosubStatement
    | stopStatement
    | inputStatement
    | forStatement
    | nextStatement
    ;
storedTailStatement
    : storedIfStatement
    | gotoStatement
    | returnStatement
    | onStatement
    | endStatement
    ;
storedIfStatement : 'IF ' booleanExpression ' THEN ' lineTarget ;
gotoStatement : 'GOTO ' lineTarget ;
gosubStatement : 'GOSUB ' lineTarget ;
returnStatement : 'RETURN' ;
onStatement
    : 'ON ' numericExpression ' GOTO ' lineTargetList
    | 'ON ' numericExpression ' GOSUB ' lineTargetList
    ;
lineTargetList : lineTarget | lineTarget comma lineTargetList ;
lineTarget : positiveInteger ;
endStatement : 'END' ;
stopStatement : 'STOP' ;
inputStatement
    : 'INPUT ' variableOrArray ( comma variableOrArray )*
    | 'INPUT ' STRING '; ' variableOrArray ( comma variableOrArray )*
    ;
immediateLine : forLine | ordinaryLine ;

// Spaces around the statement separator are optional in JavaBASIC; all four
// spacings execute identically (verified against the interpreter).
statementSeparator : ' : ' | ':' | ': ' | ' :' ;

ordinaryLine : ordinaryStatement ( statementSeparator ordinaryStatement )* ;

// FOR/NEXT is deliberately a single immediate line.  This keeps the profile
// interaction-safe without pretending that the buffered harness supports
// multiline stored-program state.
forLine : forStatement statementSeparator nextStatement
        | forStatement statementSeparator ordinaryStatement ( statementSeparator ordinaryStatement )* statementSeparator nextStatement ;

ordinaryStatement
    : assignment | printStatement | ifStatement | dimStatement | dataStatement
    | readStatement | restoreStatement | remStatement | apostropheRemStatement
    ;

assignment : 'LET ' variableOrArray equals valueExpression
           | variableOrArray equals valueExpression ;
equals : ' = ' | '=' | ' =' | '= ' ;

printStatement : 'PRINT' | 'PRINT ' printItems | '?' | '? ' printItems ;
// A trailing separator suppresses the newline, as in `PRINT "x";`.
printItems : printItem ( printSeparator printItem )* printSeparator? ;
printItem : valueExpression ;
printSeparator : ', ' | ',' | ' ,' | ' , ' | '; ' | ';' | ' ;' | ' ; ' ;

ifStatement : 'IF ' booleanExpression ' THEN ' ifAction ;
ifAction : assignment | printStatement | remStatement | apostropheRemStatement ;

dimStatement : 'DIM ' arrayDeclaration ( comma arrayDeclaration )* ;
arrayDeclaration : arrayName '(' dimensionList ')' ;
dimensionList : positiveInteger ( comma positiveInteger )* ;

dataStatement : 'DATA ' dataItem ( comma dataItem )* ;
dataItem : NUMBER | '-' NUMBER | '- ' NUMBER | STRING ;
readStatement : 'READ ' variableOrArray ( comma variableOrArray )* ;
restoreStatement : 'RESTORE' ;

forStatement : 'FOR ' numericVariable ' = ' numericExpression ' TO ' numericExpression
             | 'FOR ' numericVariable ' = ' numericExpression ' TO ' numericExpression
               ' STEP ' numericExpression ;
nextStatement : 'NEXT ' numericVariable ;

remStatement : REM_LINE ;
apostropheRemStatement : APOSTROPHE_LINE ;

valueExpression : numericExpression | stringExpression ;
booleanExpression : relationExpression ( booleanOperator relationExpression )* ;
booleanOperator : ' .AND. ' | ' .OR. ' | ' .XOR. ' ;
relationExpression : numericExpression comparisonOperator numericExpression
                   | stringExpression comparisonOperator stringExpression ;
comparisonOperator : ' = ' | ' <> ' | ' < ' | ' <= ' | ' > ' | ' >= ' ;

numericExpression : numericBitwiseExpression ;
numericBitwiseExpression : numericSum ( numericBitwiseOperator numericSum )* ;
numericBitwiseOperator : ' & ' | '&' | ' | ' | '|' | ' ^ ' | '^' ;
numericSum : numericTerm ( additiveOperator numericTerm )* ;
additiveOperator : ' + ' | '+' | ' +' | '+ ' | ' - ' | '-' | ' -' | '- ' ;
numericTerm : numericPower ( multiplicativeOperator numericPower )* ;
multiplicativeOperator : ' * ' | '*' | ' *' | '* ' | ' / ' | '/' | ' /' | '/ ' ;
numericPower : numericUnary ( ' ** ' numericUnary )* ;
numericUnary : numericPrimary | '-' numericUnary | '!' numericUnary | '.NOT. ' numericUnary ;
numericPrimary : NUMBER | numericVariable | arrayReference | numericFunctionCall
               | '(' numericExpression ')' ;

stringExpression : stringPrimary ( ' + ' stringPrimary )* ;
stringPrimary : STRING | stringVariable | arrayReference | stringFunctionCall
              | '(' stringExpression ')' ;

numericFunctionCall : unaryNumericFunction '(' numericExpression ')'
                    | twoNumericFunction '(' numericExpression comma numericExpression ')'
                    | 'LEN(' stringExpression ')' | 'VAL(' stringExpression ')' ;
unaryNumericFunction : 'INT' | 'SIN' | 'COS' | 'TAN' | 'ATN' | 'SQR' | 'ABS' | 'LOG' | 'SGN' ;
twoNumericFunction : 'MAX' | 'MIN' ;
stringFunctionCall : 'CHR$(' numericExpression ')' | 'STR$(' numericExpression ')'
                   | 'SPC$(' numericExpression ')' | 'TAB(' numericExpression ')'
                   | 'LEFT$(' stringExpression comma numericExpression ')'
                   | 'RIGHT$(' stringExpression comma numericExpression ')'
                   | 'MID$(' stringExpression comma numericExpression ')'
                   | 'MID$(' stringExpression comma numericExpression comma numericExpression ')' ;

variableOrArray : variable | arrayReference ;
variable : numericVariable | stringVariable ;
numericVariable : ID ;
stringVariable : ID '$' ;
arrayName : ID | ID '$' ;
arrayReference : arrayName '(' numericExpression ( comma numericExpression )* ')' ;
comma : ',' | ', ' | ' ,' | ' , ' ;
// NUMBER is used here because the lexer intentionally keeps numeric literals
// as one token; positivity is a semantic/bounds check in the shared catalog.
positiveInteger : POSITIVE_INTEGER ;

// The lexer keeps spaces significant because JavaBASIC accepts several
// whitespace spellings around operators.  STRING is intentionally restricted
// to the same printable alphabet as basic.bnf.
NEWLINE : '\n' ;
REM_LINE : 'REM' ~[\r\n]* ;
APOSTROPHE_LINE : '\'' ~[\r\n]* ;
// Grammarinator 26.1 rejects escaped square brackets inside a character set;
// keep the basic.bnf alphabet by spelling those two alternatives separately.
STRING : '"' ( '""' | [A-Za-z0-9 !?.,_:;(){}=+\-*/&|^<>%$#@~`'\\] | '[' | ']' )* '"' ;
POSITIVE_INTEGER : [1-9] [0-9]* ;
NUMBER : [0-9]+ ( '.' [0-9]* )? ( [Ee] [+-]? [0-9]+ )? | '.' [0-9]+ ( [Ee] [+-]? [0-9]+ )? ;
BYE : 'bye' ;
ID : [A-Za-z] [A-Za-z0-9]* ;
