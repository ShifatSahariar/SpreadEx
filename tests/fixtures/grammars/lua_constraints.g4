// LuaJ Lua 5.1-core Grammarinator grammar profile -- WITH semantic constraints.
//
// Constrained counterpart of lua.g4. Same language surface, but identifiers are
// driven by a generation-time binding pool instead of being sampled
// character-by-character, so every name in a read position is guaranteed to
// have an earlier (or enclosing) binding.
//
// Constraint source of record:
//   subjects/luaj/constraints/semantic_constraints.md
//   subjects/luaj/grammars/isla/constraints.isla        (forall/before profile)
//   subjects/luaj/grammars/fandango/lua.fan             (where blocks)
//
// WHY THIS FILE WAS REWRITTEN
//
// The previous version of this profile was an 18-rule operational subset: it
// could emit only `local vN = <literal>`, `vN = <literal>`, `print(vN)`,
// `for vN = 1, 3 do end`, and `while false do end`. 97 of the shared grammar's
// 108 rules were unreachable -- no functions, tables, comparisons,
// concatenation, arithmetic, if/repeat/do, comments, or return -- and both
// loop forms were fixed skeletons with empty bodies (`while false` never even
// executes). Measured on 300 generated inputs: 0/300 contained any of those
// constructs. That is a different language from the one every other generator
// receives, so it could not support a fair diversity comparison.
//
// This file keeps all 108 shared rules and enforces the constraints with
// actions instead, matching what karatejs_constraints.g4 already does.
//
// HOW THIS DIFFERS FROM ISLa / FANDANGO
//
// ISLa and Fandango state constraints declaratively and let a solver reject
// violating trees. Grammarinator has no constraint language; it has ANTLR
// actions and semantic predicates, copied into the generated Python. So
// constraints here hold *by construction* -- a read position can only ever
// emit a name already in scope, so no violating tree is built.
//
// Because Grammarinator generates left to right, this yields true
// declared-BEFORE-use, matching ISLa's before()/inside() and stronger than the
// Fandango profile's declared-somewhere set membership.
//
// GOTCHAS baked into this file (each cost real debugging; do not "clean up"):
//   * current.src only takes effect on LEXER rules (UPPERCASE). Setting it on
//     a parser rule is silently ignored and emits an empty string.
//   * Action text is copied verbatim into Python, so `{ code }` with a leading
//     space becomes an IndentationError. Always write `{code}`.
//   * Semantic predicates `{expr}?` compile to *alternative weights*, so a
//     false predicate means weight 0. Every guarded alternation below keeps at
//     least one unguarded alternative, otherwise generation would dead-end.
//     `{0}?` is therefore how an alternative is disabled while keeping the rule
//     present, which is how the shared rule count is preserved.
//
// Reserved words and host names (catalog rule 1, and the ISLa/Fandango name
// bans) are satisfied by construction: every generated name is a prefix plus a
// counter (v1, p2, f3, k4), so no keyword or host spelling is reachable.
//
// Deliberately disabled with `{0}?`, matching what ISLa and Fandango already
// omit rather than adding a restriction they do not have:
//   * <functionDeclaration> -- catalog rule 1 requires `local function`;
//     ISLa uses count(...,"0") and Fandango `len([*<functionDeclaration>]) == 0`.
//   * `break` -- catalog rule 6 allows it only as a loop's final statement, and
//     no profile can prove that position from this block grammar.
//   * `...` as a primary expression -- catalog rule 6 requires an enclosing
//     vararg function, which is likewise unprovable here.
//
// Left to runtime validation, as in every other LuaJ profile: catalog rule 5
// (relational/arithmetic operand types), rule 4's "the indexed value is really
// a table", rule 7's loop-progress argument, and initialization of a bare
// `local x` (handled conservatively below by not publishing that binding).

grammar lua_constraints;

@header {
import random
}

@members {
def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._n = 0
    self._scopes = [[]]            # stack of value scopes; index 0 is the chunk
    self._function_scopes = [[]]   # stack of local-function scopes
    self._pending = []    # names declared by the statement being generated

# -- name minting -------------------------------------------------------
def _next(self, prefix):
    self._n += 1
    return prefix + str(self._n)

# -- binding positions --------------------------------------------------
def _declare(self):
    # Staged, not yet visible: published by the statement's @after. This is
    # what makes "declared BEFORE use" hold -- the initializer expression of
    # `local v1 = <expr>` cannot reference v1 itself, and a numeric for's
    # bounds cannot reference its own loop variable.
    n = self._next('v')
    self._pending.append(n)
    return n

def _commit(self):
    self._scopes[-1].extend(self._pending)
    self._pending = []

def _drop_pending(self):
    # `local x` with no initializer: catalog rule 2 forbids reading it before
    # a later assignment, and this profile cannot prove that assignment
    # happens, so the binding is minted but never published.
    self._pending = []

def _bind_now(self):
    # Parameters: visible immediately for the rest of the enclosing scope.
    n = self._next('p')
    self._scopes[-1].append(n)
    return n

def _declare_fn(self):
    # Bound before its own body so direct recursion is derivable, which
    # catalog rule 3 explicitly permits.
    n = self._next('f')
    self._function_scopes[-1].append(n)
    return n

# -- scope handling -----------------------------------------------------
def _push(self):
    self._scopes.append([])
    self._function_scopes.append([])

def _pop(self):
    if len(self._scopes) > 1:
        self._scopes.pop()
        self._function_scopes.pop()

# -- read positions -----------------------------------------------------
def _visible(self):
    out = []
    for s in self._scopes:
        out.extend(s)
    return out

def _has(self):
    return 1 if self._visible() else 0

def _use(self):
    v = self._visible()
    return random.choice(v) if v else self._next('v')

def _hasfn(self):
    return 1 if self._visible_functions() else 0

def _usefn(self):
    v = self._visible_functions()
    return random.choice(v) if v else self._next('f')

def _visible_functions(self):
    out = []
    for s in self._function_scopes:
        out.extend(s)
    return out

# -- table keys and method names (never bindable) -----------------------
def _prop(self):
    return self._next('k')

# -- catalog rule 3: the only permitted global reads --------------------
def _builtin(self):
    return random.choice(
        ['print', 'pairs', 'ipairs', 'type', 'tostring', 'tonumber']
    )
}

start : chunk EOF ;
chunk : block ;
block : lastStatementLine | statementList | statementList lineGap lastStatementLine
      | blockTail ;
// A block's final return/break may carry a trailing comment, exactly as an
// ordinary statement may inside statementList.
lastStatementLine : lastStatement
                  | lastStatement horizontalWhitespace comment
                  | lastStatement comment ;
blockTail : statement semicolonSeparator lastStatementLine
          | statement semicolonSeparator blockTail
          | statement lineGap blockTail
          | statement horizontalWhitespace lastStatementLine
          | statement horizontalWhitespace blockTail
          | comment lineGap blockTail ;
statementList : statement | statement terminatingSemicolon
                 | statement lineGap statementList
                 | statement semicolonSeparator statementList
                 | statement terminatingSemicolon lineGap statementList
                 | comment
                 | comment lineGap statementList
                 | statement horizontalWhitespace statementList
                 | statement comment
                 | statement comment lineGap statementList ;
comment : lineComment | longComment ;
semicolonSeparator : ';' | '; ' | ' ;' | ' ; ' ;
terminatingSemicolon : ';' | ' ;' ;

assign : '=' | ' = ' | '= ' | ' =' ;
comma : ',' | ', ' | ' ,' | ' , ' ;
addOperator : '+' | ' + ' | '+ ' | ' +' ;
mulOperator : '*' | ' * ' | '* ' | ' *' ;
divOperator : '/' | ' / ' | '/ ' | ' /' ;
modOperator : '%' | ' % ' | '% ' | ' %' ;
powOperator : '^' | ' ^ ' | '^ ' | ' ^' ;
spacedSubOperator : ' - ' | '- ' ;
tightSubOperator : '-' | ' -' ;
newline : '\n' ;
// Match the shared compact layout policy: line-oriented constructs receive
// one newline with optional following indentation, never blank-line runs.
lineGap : newlineRun ;
newlineRun : newline | newline horizontalWhitespace ;
horizontalWhitespace : ' ' | '\t' | ' ' horizontalWhitespace | '\t' horizontalWhitespace ;

// localDeclaration is the one always-available statement: it is what seeds the
// binding pool, so the guarded read alternatives below can never dead-end an
// empty chunk.
statement : {self._has()}? assignment
              | localDeclaration
              | functionCall
              | doStatement
              | whileStatement
              | repeatStatement
              | ifStatement
              | numericForStatement
              | genericForStatement
              | {0}? functionDeclaration
              | localFunctionDeclaration ;
// `break` is disabled here, not deleted: see the header note.
lastStatement : 'return' | 'return ' expressionList
                  | 'return;' | 'return ' expressionList terminatingSemicolon
                  | {0}? 'break' | {0}? 'break;' ;

// Catalog rule 1: an assignment target must already be a local binding,
// otherwise Lua creates an implicit global.
assignment : variableList assign expressionList ;
localDeclaration
@after {self._commit()}
    : 'local ' nameList assign expressionList
    | 'local ' unpublishedNameList
    ;
// A compound statement's block may begin on the header line or the next one,
// and may close after a space or a line break. Replaces the former
// inlineStatement, whose {self._has()}? guard was a duplicate: `statement`
// already gates `assignment` on the same predicate, and blockBody reaches
// assignment only through block -> statementList -> statement.
blockBody : ' ' block | lineGap block ;
blockClose : ' ' | lineGap ;
doStatement : 'do end' | 'do'lineGap'end' | 'do' blockBody blockClose 'end' ;
whileStatement : 'while ' expression ' do end'
                   | 'while ' expression ' do'lineGap'end'
                   | 'while ' expression ' do' blockBody blockClose 'end' ;
repeatStatement : 'repeat'lineGap'until ' expression
                    | 'repeat' blockBody blockClose 'until ' expression ;
ifStatement : 'if ' expression ' then end'
                | 'if ' expression ' then'lineGap'end'
                | 'if ' expression ' then' blockBody blockClose 'end'
                | 'if ' expression ' then' blockBody blockClose 'else' blockBody blockClose 'end'
                | 'if ' expression ' then' blockBody blockClose elseifList 'end'
                | 'if ' expression ' then' blockBody blockClose elseifList 'else' blockBody blockClose 'end' ;
elseifList : 'elseif ' expression ' then' blockBody blockClose
               | 'elseif ' expression ' then' blockBody blockClose elseifList ;
// The loop variable is staged by loopName and published by the {self._commit()}
// placed after the bounds, so the bounds cannot read the variable they define.
numericForStatement
@init {self._push()}
@after {self._pop()}
    : 'for ' loopName assign numericExpression comma numericExpression {self._commit()} ' do end'
    | 'for ' loopName assign numericExpression comma numericExpression {self._commit()} ' do'lineGap'end'
    | 'for ' loopName assign numericExpression comma numericExpression {self._commit()} ' do' blockBody blockClose 'end'
    | 'for ' loopName assign numericExpression comma numericExpression comma numericExpression {self._commit()} ' do end'
    | 'for ' loopName assign numericExpression comma numericExpression comma numericExpression {self._commit()} ' do'lineGap'end'
    | 'for ' loopName assign numericExpression comma numericExpression comma numericExpression {self._commit()} ' do' blockBody blockClose 'end' ;
genericForStatement
@init {self._push()}
@after {self._pop()}
    : 'for ' loopNameList ' in ' expressionList {self._commit()} ' do end'
    | 'for ' loopNameList ' in ' expressionList {self._commit()} ' do'lineGap'end'
    | 'for ' loopNameList ' in ' expressionList {self._commit()} ' do' blockBody blockClose 'end' ;

// Disabled by the {0}? guard in `statement`; kept so the shared rule set and
// its reachable spellings stay identical to lua.g4.
functionDeclaration : 'function ' functionName functionBody ;
localFunctionDeclaration : 'local function ' FN_ID functionBody ;
functionName : USE_ID | USE_ID '.' functionName | USE_ID methodSeparator PROP_ID ;
methodSeparator : ':' | ': ' ;
functionBody
@init {self._push()}
@after {self._pop()}
    : '() end' | '()' lineGap 'end' | '()' blockBody blockClose 'end'
    | '()' block blockClose 'end'
    | '(' parameterList ') end'
    | '(' parameterList ')' lineGap 'end'
    | '(' parameterList ')' blockBody blockClose 'end'
    | '(' parameterList ')' block blockClose 'end' ;
parameterList : paramNameList | paramNameList ', ...' | '...' ;

variableList : variable | variable comma variableList ;
// Binding-position name lists. nameList publishes through localDeclaration's
// @after; unpublishedNameList is the bare `local x` form (catalog rule 2);
// loopNameList/loopName publish at the loop header's explicit commit.
nameList : DECL_ID | DECL_ID comma nameList ;
unpublishedNameList
@after {self._drop_pending()}
    : DECL_ID | DECL_ID comma unpublishedNameList ;
loopName : DECL_ID ;
loopNameList : DECL_ID | DECL_ID comma loopNameList ;
paramNameList : LOCAL_ID | LOCAL_ID comma paramNameList ;
expressionList : expression | expression comma expressionList ;
variable : USE_ID | USE_ID variableTail ;
variableTail : '.' PROP_ID | '[' expression ']'
                 | '.' PROP_ID variableTail | '[' expression ']' variableTail ;

numericExpression : numericAdditiveExpression ;
numericAdditiveExpression : numericMultiplicativeExpression
                              | numericMultiplicativeExpression addOperator numericAdditiveExpression
                              | numericMultiplicativeExpression spacedSubOperator numericAdditiveExpression
                              | numericMultiplicativeExpression tightSubOperator nonNegatedNumericAdditive ;
nonNegatedNumericAdditive : nonNegatedNumericMultiplicative
                              | nonNegatedNumericMultiplicative addOperator numericAdditiveExpression
                              | nonNegatedNumericMultiplicative spacedSubOperator numericAdditiveExpression
                              | nonNegatedNumericMultiplicative tightSubOperator nonNegatedNumericAdditive ;
numericMultiplicativeExpression : numericUnaryExpression
                                    | numericUnaryExpression mulOperator numericMultiplicativeExpression
                                    | numericUnaryExpression divOperator numericMultiplicativeExpression
                                    | numericUnaryExpression modOperator numericMultiplicativeExpression ;
nonNegatedNumericMultiplicative : nonNegatedNumericUnary
                                    | nonNegatedNumericUnary mulOperator numericMultiplicativeExpression
                                    | nonNegatedNumericUnary divOperator numericMultiplicativeExpression
                                    | nonNegatedNumericUnary modOperator numericMultiplicativeExpression ;
numericUnaryExpression : numericPowerExpression | numericNegation | '#' numericUnaryExpression ;
numericNegation : '-' nonNegatedNumericUnary | '- ' numericUnaryExpression ;
nonNegatedNumericUnary : numericPowerExpression | '#' numericUnaryExpression ;
numericPowerExpression : numericPrimaryExpression | numericPrimaryExpression powOperator numericUnaryExpression ;
numericPrimaryExpression : number | {self._has()}? variable | functionCall | '(' numericExpression ')' ;

expression : orExpression ;
orExpression : andExpression | andExpression ' or ' orExpression ;
andExpression : relationalExpression | relationalExpression ' and ' andExpression ;
relationalExpression : concatenationExpression
                         | concatenationExpression relationalOperator concatenationExpression ;
relationalOperator : '==' | ' == ' | '== ' | ' =='
                   | '~=' | ' ~= ' | '~= ' | ' ~='
                   | '<=' | ' <= ' | '<= ' | ' <='
                   | '>=' | ' >= ' | '>= ' | ' >='
                   | '<' | ' < ' | '< ' | ' <'
                   | '>' | ' > ' | '> ' | ' >' ;
concatenationExpression : additiveExpression | additiveExpression concatOperator concatenationExpression ;
concatOperator : '..' | ' .. ' | '.. ' | ' ..' ;
additiveExpression : multiplicativeExpression
                       | multiplicativeExpression addOperator additiveExpression
                       | multiplicativeExpression spacedSubOperator additiveExpression
                       | multiplicativeExpression tightSubOperator nonNegatedAdditive ;
nonNegatedAdditive : nonNegatedMultiplicative
                       | nonNegatedMultiplicative addOperator additiveExpression
                       | nonNegatedMultiplicative spacedSubOperator additiveExpression
                       | nonNegatedMultiplicative tightSubOperator nonNegatedAdditive ;
multiplicativeExpression : unaryExpression
                             | unaryExpression mulOperator multiplicativeExpression
                             | unaryExpression divOperator multiplicativeExpression
                             | unaryExpression modOperator multiplicativeExpression ;
nonNegatedMultiplicative : nonNegatedUnary
                             | nonNegatedUnary mulOperator multiplicativeExpression
                             | nonNegatedUnary divOperator multiplicativeExpression
                             | nonNegatedUnary modOperator multiplicativeExpression ;
unaryExpression : powerExpression | negation | 'not ' unaryExpression | '#' unaryExpression ;
negation : '-' nonNegatedUnary | '- ' unaryExpression ;
nonNegatedUnary : powerExpression | 'not ' unaryExpression | '#' unaryExpression ;
powerExpression : primaryExpression | primaryExpression powOperator unaryExpression ;
// `...` is disabled here, not deleted: see the header note.
primaryExpression : 'nil' | 'false' | 'true' | number | string | {0}? '...'
                      | {self._has()}? variable | functionCall | tableConstructor | functionExpression
                      | '(' expression ')' ;
functionExpression : 'function' functionBody | 'function ' functionBody ;

// Catalog rule 3: a call target is a lexically visible local function or one
// of the permitted deterministic builtins. Method calls and arbitrary value
// calls need table/function type tracking, so they are excluded here rather
// than emitting known runtime-invalid candidates.
functionCall : callTarget arguments | {0}? callTarget methodSeparator PROP_ID arguments ;
callTarget : BUILTIN_ID | {self._hasfn()}? USE_FN | {0}? variable
           | {0}? '(' expression ')' | {0}? functionCall ;
arguments : '()' | '(' expressionList ')' | tableConstructor | ' ' tableConstructor
          | string | ' ' string ;

tableConstructor : '{}' | '{ }' | '{' fieldList '}' | '{ ' fieldList ' }'
                    | '{' fieldList ' }' | '{ ' fieldList '}' ;
fieldList : field | field ',' | field ';'
              | field ', ' fieldList | field '; ' fieldList ;
field : '[' expression ']' assign expression | PROP_ID assign expression | expression ;

number : decimalNumber | hexNumber ;
decimalNumber : integer | integer '.' | integer '.' digitSequence | '.' digitSequence
                  | integer exponentPart | integer '.' digitSequence exponentPart
                  | '.' digitSequence exponentPart ;
hexNumber : '0x'hexDigitSequence | '0X'hexDigitSequence
              ;
exponentPart : 'e' signedInteger | 'E' signedInteger ;
signedInteger : integer | '+'integer | '-'integer ;
integer : '0' | nonzeroDigit | nonzeroDigit digitSequence ;
digitSequence : digit | digit digitSequence ;
hexDigitSequence : hexDigit | hexDigit hexDigitSequence ;
digit : '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' ;
nonzeroDigit : '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' ;
hexDigit : digit | 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'A' | 'B' | 'C' | 'D' | 'E' | 'F' ;

string : '""' | '\'\'' | '[[]]' | '[=[]=]'
           | '"' doubleStringChars '"' | '\'' singleStringChars '\'' | '[[' longStringChars ']]'
           | '[=[' longStringChars ']=]' ;
doubleStringChars : doubleStringChar | doubleStringChar doubleStringChars ;
singleStringChars : singleStringChar | singleStringChar singleStringChars ;
longStringChars : longStringChar | longStringChar longStringChars ;
doubleStringChar : safeCharacter | '\'' | '[' | ']' | escapeSequence ;
singleStringChar : safeCharacter | '"' | '[' | ']' | escapeSequence ;
// Long brackets may span lines; the closing delimiter still bounds the span.
longStringChar : safeCharacter | '"' | '\'' | '[' | ']' | newline ;
escapeSequence : '\\\\' | '\\"' | '\\\'' | '\\a' | '\\b' | '\\f'
                   | '\\n' | '\\r' | '\\t' | '\\v' | decimalEscape ;
decimalEscape : '\\' digit | '\\' digit digit | '\\' digit digit digit ;

lineComment : '--' | '--'lineCommentChar | '--'lineCommentChar commentChars ;
longComment : '--[[]]' | '--[=[]=]'
                | '--[[' longStringChars ']]' | '--[=[' longStringChars ']=]' ;
commentChars : commentChar | commentChar commentChars ;
commentChar : safeCharacter | '[' | ']' | '"' | '\'' | '\\' ;
lineCommentChar : safeCharacter | ']' | '"' | '\'' | '\\' ;

letter : 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'g' | 'h' | 'i' | 'j' | 'k' | 'l' | 'm'
           | 'n' | 'o' | 'p' | 'q' | 'r' | 's' | 't' | 'u' | 'v' | 'w' | 'x' | 'y' | 'z'
           | 'A' | 'B' | 'C' | 'D' | 'E' | 'F' | 'G' | 'H' | 'I' | 'J' | 'K' | 'L' | 'M'
           | 'N' | 'O' | 'P' | 'Q' | 'R' | 'S' | 'T' | 'U' | 'V' | 'W' | 'X' | 'Y' | 'Z' ;
// Bounded non-ASCII source policy: whole Unicode blocks (Latin-1 Supplement,
// General Punctuation, Arrows, Mathematical Operators).
nonAsciiCharacter : '¡' | '¢' | '£' | '¤' | '¥' | '¦' | '§' | '¨' | '©' | 'ª' | '«' | '¬'
                  | '®' | '¯' | '°' | '±' | '²' | '³' | '´' | 'µ' | '¶' | '·' | '¸' | '¹'
                  | 'º' | '»' | '¼' | '½' | '¾' | '¿' | 'À' | 'Á' | 'Â' | 'Ã' | 'Ä' | 'Å'
                  | 'Æ' | 'Ç' | 'È' | 'É' | 'Ê' | 'Ë' | 'Ì' | 'Í' | 'Î' | 'Ï' | 'Ð' | 'Ñ'
                  | 'Ò' | 'Ó' | 'Ô' | 'Õ' | 'Ö' | '×' | 'Ø' | 'Ù' | 'Ú' | 'Û' | 'Ü' | 'Ý'
                  | 'Þ' | 'ß' | 'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' | 'æ' | 'ç' | 'è' | 'é'
                  | 'ê' | 'ë' | 'ì' | 'í' | 'î' | 'ï' | 'ð' | 'ñ' | 'ò' | 'ó' | 'ô' | 'õ'
                  | 'ö' | '÷' | 'ø' | 'ù' | 'ú' | 'û' | 'ü' | 'ý' | 'þ' | 'ÿ' | '‐' | '‑'
                  | '‒' | '–' | '—' | '―' | '‖' | '‗' | '‘' | '’' | '‚' | '‛' | '“' | '”'
                  | '„' | '‟' | '†' | '‡' | '•' | '‣' | '․' | '‥' | '…' | '‧' | '‰' | '‱'
                  | '′' | '″' | '‴' | '‵' | '‶' | '‷' | '‸' | '‹' | '›' | '※' | '‼' | '‽'
                  | '‾' | '‿' | '⁀' | '⁁' | '⁂' | '⁃' | '⁄' | '⁅' | '⁆' | '⁇' | '⁈' | '⁉'
                  | '⁊' | '⁋' | '⁌' | '⁍' | '⁎' | '⁏' | '⁐' | '⁑' | '⁒' | '⁓' | '⁔' | '⁕'
                  | '⁖' | '⁗' | '⁘' | '⁙' | '⁚' | '⁛' | '⁜' | '⁝' | '⁞' ;
safeCharacter : letter | digit | ' ' | '!' | '#' | '$' | '%' | '&' | '(' | ')' | '*' | '+' | ','
                  | '-' | '.' | '/' | ':' | ';' | '<' | '=' | '>' | '?' | '@' | '^' | '_' | '`'
                  | '{' | '|' | '}' | '~' | nonAsciiCharacter ;

// --- binding-pool-driven identifier tokens (must be LEXER rules) ---

DECL_ID : {current.src = self._declare()} ;
LOCAL_ID : {current.src = self._bind_now()} ;
FN_ID : {current.src = self._declare_fn()} ;
USE_ID : {current.src = self._use()} ;
USE_FN : {current.src = self._usefn()} ;
PROP_ID : {current.src = self._prop()} ;
BUILTIN_ID : {current.src = self._builtin()} ;
