function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
  }
}

var SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  var iter = fibGen(count);
  var next;
  while (!(next = iter.next()).done) {
    var num = next.value;
    var key = SYM.toString() + ':' + num;
    fibObj[key] = num.toString();
    if (typeof num === 'bigint' && +num > 50) {
      throw new Error('BigFibTooBig:' + num);
    }
  }
} catch (err) {
  console.log('Caught:', err.message || err);
}

var keys = Object.keys(fibObj);
for (var i = 0; i < keys.length; i++) {
  console.log(keys[i] + ' -> ' + fibObj[keys[i]]);
}
