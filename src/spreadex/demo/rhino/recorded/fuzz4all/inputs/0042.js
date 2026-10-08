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
  const count = 15;
  for (let num of fibGen(count)) {
    const key = typeof num === 'bigint' && num % 2n === 0n ? SYM : Symbol('alt');
    fibObj[key + num] = num.toString(16);
    if (typeof num === 'bigint' && +num > 100) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
for (let k in fibObj) {
  console.log(k + ' => ' + fibObj[k]);
}
