function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
  }
}
const SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  var threshold = 30;
  for (let num of fibGen(count)) {
     
    fibObj[SYM.description + (num ** 2n)] = String(num);
    if (typeof num === 'bigint' && +num > threshold) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
for (let k in fibObj) {
   
  console.log(k + ' -> ' + fibObj[k].split('').reverse().join(''));
}
