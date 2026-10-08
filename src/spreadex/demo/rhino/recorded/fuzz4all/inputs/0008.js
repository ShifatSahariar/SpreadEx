const sym = Symbol('x');
var x = 10;
function* gen() {
  var x = yield BigInt(100) + BigInt(23);  
  let y = x ?? 42;                         
 
  y = (x === null || x === undefined) ? 42 : x;
  for (let i = 0; i < y; i++) {
    if (i % 2 === 0) yield i + x;
  }
}
console.log(typeof sym, sym.toString());

var result = [];   
var g = gen();
result.push(g.next().value.toString());     
var input = 5;
result.push(g.next(input).value);            
 
 
 
 

 
while (true) {
  var next = g.next();
  if (next.done) break;
  result.push(next.value);
}

var let = 1;                    
try {
  let let = 2;                  
} catch(e) {
  result.push(String(e.constructor.name));
}

const c = 1;
const c = 2;                    
result.push(c);

var x = null;                   
function foo() {
  if (x == null) var x = 'hoisted';  
  return x;
}
result.push(foo(), x);

console.log(result.join('|'));
