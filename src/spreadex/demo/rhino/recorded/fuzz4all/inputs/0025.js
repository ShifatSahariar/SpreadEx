function* fibGen(n) {
  let [a, b] = [0n, 1n];
  for (let i = 0; i < n; i++) {
    yield a;
    const sum = a + b;
    a = b;
    b = sum;
  }
}

const SYM = Symbol('key');
const fibObj = {};
try {
  const count = 10;
  for (let num of fibGen(count)) {
    fibObj[SYM + num] = String(num);  
    if (typeof num === 'bigint' && +num > 20) throw 'BigFibTooBig:' + num;
  }
} catch (e) {
  console.log('Caught:', e);
}

for (let k in fibObj) {
   
  console.log(k + ' -> ' + fibObj[k]);
}
