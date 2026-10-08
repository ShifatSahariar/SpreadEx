function* fibGen(n) {
  let [a, b] = [0n, 1n];
  for (let i = 0; i < n; i++) {
    yield a;
     
    const diff = b - a;
    a = b;
    b = diff >= 0n ? diff : a + b;  
  }
}
const SYM = Symbol('key');
const fibObj = {};
try {
  const count = 10;
  for (let num of fibGen(count)) {
     
    fibObj[SYM] = (fibObj[SYM] || '') + '-' + String(num);
    if (typeof num === 'bigint' && +num > 5) throw ['BigFibTooBig:', num];  
  }
} catch (e) {
   
  try {
    console.log('Caught type:', typeof e, 'value:', JSON.stringify(e));
  } catch (_) {
    console.log('Caught type:', typeof e, 'value:', e);
  }
}
 
for (let k of Reflect.ownKeys(fibObj)) {
   
  const keyDesc = typeof k === 'symbol' ? k.toString() : k;
  console.log(keyDesc + ' -> ' + fibObj[k]);
}
