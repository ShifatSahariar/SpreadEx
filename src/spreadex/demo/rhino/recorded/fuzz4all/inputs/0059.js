function* fibGen(n) {
  var a = 0n, b = 1n;
  var i = 0;
  while (i < n) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
    i++;
  }
}
var SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  for (var num of fibGen(count)) {
    var key = SYM.toString() + ':' + num;
    fibObj[key] = num.toString();
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
var keys = Object.keys(fibObj);
for (var k = 0; k < keys.length; k++) {
  console.log(keys[k] + ' -> ' + fibObj[keys[k]]);
}
