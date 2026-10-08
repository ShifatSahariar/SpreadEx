function* fib() {
  let a = 0n, b = 1n;
  while (true) {
    yield a;
    [a, b] = [b, a + b];
  }
}

 
{
  let x = 10;
  const y = 20;  
  try {
     
     
  } catch (e) {
    print('Error:', e);
  }
}

 
let sum = 0n;
let count = 10;
const gen = fib();
while (count--) {
  sum += gen.next().value;  
}

console.log('Sum of first 10 Fibonacci numbers (BigInt):', sum.toString());
console.log('const y visible here:', y);
