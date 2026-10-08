function* genPowers(base) {
  let exp = 0n;
  while (exp < 5n) {
    yield base ** exp++;        
  }
}

 
function makeAdder(x) {
  let y = 1;
   
  const y = 2;   
  return function(z) { return x + y + z; };
}

try {
  let a = 1;
   
} catch (e) {print('Error:', e);}


 
const base = 2n;
const powers = genPowers(base);
const add10 = makeAdder(10);

for (let val of powers) {
  let n = Number(val);    
   
  const sym = Symbol('p');
  const res = add10(n) + sym.toString().length;  
  print('2^' + val + '=' + val + ', add10+sym:', res);
}

 
function fact(n) {
  if (n === 0 || n === 1) return 1n;
  var f = fact(n - 1);
  return BigInt(n) * f;
}

print('fact(5):', fact(5));   

 
print('hoisted x:', x);
var x = 42;

 
try {
  throw new Error('Rhino test error');
} catch (e) {
  print('Caught error:', e.message);
}
