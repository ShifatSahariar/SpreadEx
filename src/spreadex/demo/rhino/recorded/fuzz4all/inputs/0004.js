function* fib(limit) {
  let a = 0n, b = 1n;
  while (a <= limit) {
    yield a;
    [a, b] = [b, a + b];
  }
}

 
{
  let x = 10;
  const y = 20;  
  console.log('Inside block:', x, y);
}
 
console.log('Outside block:', typeof y !== 'undefined' ? y : 'y undefined');

 
const limit = 100n;
let sum = 0n;
for (const n of fib(limit)) {
  sum += n;
}
console.log('Sum of fib up to', limit, '=', sum);

 
console.log('z before declaration:', typeof z !== 'undefined' ? z : 'z undefined');
var z = 42;
console.log('z after initialization:', z);

 
try {
  throw new ReferenceError('Rhino custom error');
} catch (e) {
  console.log('Caught error:', e.name, e.message);
}
