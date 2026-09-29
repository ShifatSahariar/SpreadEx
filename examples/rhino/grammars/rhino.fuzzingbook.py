from fuzzingbook.Grammars import crange

def get_rhino_grammar():
    rhino_grammar = {

        "<start>": ["<program>"],

        # === Program ===
        "<program>": ["<sourceElements>"],
        "<sourceElements>": [
            "<statement>\n",
            "<statement>\n<sourceElements>"
        ],

        # === Statements ===
        "<statement>": [
            "<variableStatement>",
            "<arrayDeclaration>",
            "<objectDeclaration>",
            "<expressionStatement>",
            "<ifStatement>",
            "<iterationStatement>",
            "<switchStatement>",
            "<tryStatement>",
            "<printStatement>",
            "<functionDeclaration>"
        ],

        # === Declarations ===
        "<variableStatement>": [
            "var <identifier> = <expression> ;",
            "var <identifier> = <numericLiteral> ;",
            "var <identifier> = <stringLiteral> ;"
        ],

        "<arrayDeclaration>": [
            "var <identifier> = [ <expressionList> ] ;"
        ],
        "<expressionList>": [
            "<expression>",
            "<expression> , <expressionList>"
        ],

        "<objectDeclaration>": [
            "var <identifier> = { <propertyList> } ;"
        ],
        "<propertyList>": [
            "<property> : <expression>",
            "<property> : <expression> , <propertyList>"
        ],

        # === Expressions ===
        "<expressionStatement>": [
            "<identifier> = <expression> ;",
            "<identifier> ++ ;",
            "<identifier> -- ;"
        ],

        "<expression>": [
            "<numericLiteral>",
            "<identifier>",
            "<identifier> + <identifier>",
            "<identifier> - <identifier>",
            "<identifier> * <identifier>",
            "<identifier> / <identifier>",
            "<identifier> > <identifier>",
            "<identifier> < <identifier>",
            "<identifier> == <identifier>",
            "typeof <identifier>",
            "<identifier> [ <expression> ]",
            "<identifier> . <property>",
            "<identifier> . <property> = <expression>",
            "new Array ( <expression> )",
            "<identifier> ( <argumentList> )",
            "<identifier> . <property> ( <argumentList> )"
        ],

        "<argumentList>": ["", "<expression>", "<expression>, <argumentList>"],

        # === Control flow ===
        "<ifStatement>": [
            "if ( <expression> ) { <simpleStatementList> }",
            "if ( <expression> ) { <simpleStatementList> } else { <simpleStatementList> }"
        ],

        "<iterationStatement>": [
            "while ( <expression> ) { <simpleStatementList> }",
            "for ( var <identifier> = <numericLiteral> ; <expression> ; <identifier> ++ ) { <simpleStatementList> }"
        ],

        "<switchStatement>": [
            "switch ( <identifier> ) { case <numericLiteral> : <simpleStatementList> break ; default : <simpleStatementList> }"
        ],

        "<tryStatement>": [
            "try { <simpleStatementList> } catch ( <identifier> ) { <simpleStatementList> }",
            "try { <simpleStatementList> } catch ( <identifier> ) { <simpleStatementList> } finally { <simpleStatementList> }"
        ],

        "<throwStatement>": [
            "throw new Error ( <stringLiteral> ) ;",
            "throw new TypeError ( <stringLiteral> ) ;",
            "throw new ReferenceError ( <stringLiteral> ) ;"
        ],

        "<printStatement>": [
            "print(<identifier>) ;",
            "print(<numericLiteral>) ;",
            "print(<stringLiteral>) ;"
        ],

        # === Functions ===
        "<functionDeclaration>": [
            "function <identifier> ( <formalParameterList> ) { <functionBody> }"
        ],
        "<formalParameterList>": ["", "<identifier>", "<identifier> , <identifier>"],
        "<functionBody>": [
            "<simpleStatementList>\nreturn <expression> ;",
            "<simpleStatementList>\nreturn ;"
        ],

        "<simpleStatementList>": [
            "<simpleStatement>",
            "<simpleStatement>\n<simpleStatementList>"
        ],
        "<simpleStatement>": [
            "<variableStatement>",
            "<expressionStatement>",
            "<printStatement>",
            "<throwStatement>"
        ],

        # === Tokens ===
        "<numericLiteral>": crange('0', '9'),
        "<identifier>": [
            "x","y","z","i","j","k","count","sum","total","result","temp","flag"
        ],
        "<stringLiteral>": [
            '"ok"','"error"','"done"','"test"','"loop"','"TypeError"'
        ],
        "<property>": ["length","value","name","x","y","z"]
    }

    return rhino_grammar
