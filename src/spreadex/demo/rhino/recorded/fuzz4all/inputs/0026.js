function* fibGen(n) {
  let [a, b] = [0n, 1n];
  for (let i = 0; i < n; i++) {
    yield a;
     
    [a, b] = [b, a + b];
  }
}
const SYM = Symbol('key');
const fibObj = {};
try {
  const count = 15;  
  for (let num of fibGen(count)) {
     
    fibObj[SYM.description + '_' + num] = typeof num === 'bigint' ? num.toString(10) : num;
    if (typeof num === 'bigint' && num > 50n) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
   
  console.log('Caught:', e && e.message || e);
}
 
for (let k in fibObj) {
  console.log(k + ' -> ' + fibObj[k]);
}
