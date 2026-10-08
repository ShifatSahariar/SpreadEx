function* fibGen(n) {
  var a = 0n, b = 1n;  
  var i = 0;
  while (i < n) {
    yield a;
    var temp = a + b;
    a = b;
    b = temp;
    i++;
  }
}
const SYM = Symbol('key');
const fibObj = {};
try {
  var count = 15;
  for (var num of fibGen(count)) {
     
    fibObj[String(SYM) + "_" + num.toString()] = num < 10n ? 'small-' + num : 'large-' + num;
    if (typeof num === 'bigint' && num > 30n) throw new Error('BigFibExceeded:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
for (var k in fibObj) {
  console.log(k + ' => ' + fibObj[k]);
}
