function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    var temp = a + b;
    a = b;
    b = temp;
  }
}

var SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  for (var val of fibGen(count)) {
    var key = SYM.toString() + ':' + val;
    fibObj[key] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (error) {
  console.log('Caught:', error.message || error);
}

var keys = Object.keys(fibObj);
for (var idx = 0; idx < keys.length; idx++) {
  console.log(keys[idx] + ' -> ' + fibObj[keys[idx]]);
}
