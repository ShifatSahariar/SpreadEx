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
  for (var f of fibGen(count)) {
    var key = SYM.toString() + ':' + f;
    fibObj[key] = f.toString();
    if (typeof f === 'bigint' && +f > 50) throw new Error('BigFibTooBig:' + f);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}

var keys = Object.keys(fibObj);
for (var j = 0; j < keys.length; j++) {
  console.log(keys[j] + ' -> ' + fibObj[keys[j]]);
}
