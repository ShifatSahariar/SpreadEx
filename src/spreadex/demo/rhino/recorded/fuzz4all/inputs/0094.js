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
var count = 15;

try {
  for (var val of fibGen(count)) {
    var key = SYM.toString() + ':' + val;
    fibObj[key] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}

var keys = Object.keys(fibObj);
for (var i = 0; i < keys.length; i++) {
  console.log(keys[i] + ' -> ' + fibObj[keys[i]]);
}
