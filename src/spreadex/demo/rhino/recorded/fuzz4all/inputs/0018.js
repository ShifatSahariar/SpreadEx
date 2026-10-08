function* gen() {
    const sym = Symbol('v');
     
    for (var i = 0n; i < 3n; i++) {
        yield { [sym]: i, val: Number(i) * 2 };  
    }
}

 
console.log('x before var:', x);
var x = 10;

 
let a = 5;
{
    let a = 10;  
    const c = 42;  
    try {
        let a = 20;  
    } catch(e) {
        print('Caught redeclaring let:', e instanceof SyntaxError);
    }
    print('Inner a:', a, ', c:', c);
}
print('Outer a:', a);
print('const c accessible globally?', typeof c !== 'undefined', c);

 
for (var obj of gen()) {
     
    var key = Object.getOwnPropertySymbols(obj)[0];
    print('Yielded', key.toString(), '=', obj[key], ', val =', obj.val);
}

 
try {
    throw 'error string';
} catch(e) {
    print('Caught thrown string:', e);
}

 
try {
    throw { message: 'obj error', code: 123 };
} catch(e) {
    print('Caught object error message:', e.message, 'code:', e.code);
}
