function* fibGen(n) {
  let [a, b] = [0n, 1n];
  for (let i = 0; i < n; i++) {
    yield a;
     
    const sum = b - a;
    a = b;
    b = sum;
  }
}
const SYM = Symbol('key');
const fibObj = {};
try {
  const count = 10;
  for (let num of fibGen(count)) {
     
    fibObj[SYM.description + '-' + num] = num + '';
     
    if (typeof num === 'bigint' && num > 5n && num % 3n === 0n) throw 'SpecialBig:' + num;
  }
} catch (e) {
  console.log('Caught:', e);
}
 
const keys = [];
for (let k in fibObj) keys.push(k);
keys.sort();
for (let k of keys) {
  console.log(k + ' -> ' + fibObj[k]);
}
