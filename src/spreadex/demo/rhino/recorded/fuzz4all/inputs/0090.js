function* fibGen(n) {
  var a = 0n, b = 1n;
  var i = 0;
  while (i < n) {
    yield a;
    var next = a + b;
    a = b;
    b = next;
    i++;
  }
}

var SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  var iterator = fibGen(count);
  for (;;) {
    var res = iterator.next();
    if (res.done) break;
    var val = res.value;
    var key = SYM.toString() + ':' + val;
    fibObj[key] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}

var keys = Object.keys(fibObj);
var i = 0;
while (i < keys.length) {
  console.log(keys[i] + ' -> ' + fibObj[keys[i]]);
  i++;
}
