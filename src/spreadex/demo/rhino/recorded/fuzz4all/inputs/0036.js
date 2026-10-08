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
const fibObj = {};
try {
  var count = 15;
  for (var num of fibGen(count)) {
     
    fibObj[SYM.toString() + String(num).split('').reverse().join('')] = num + '';
    if (typeof num === 'bigint' && +num > 50) throw new Error('TooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
 
for (var k in fibObj) {
  if (fibObj[k].length % 2 === 0) continue;
  console.log(k + ' => ' + fibObj[k]);
}
