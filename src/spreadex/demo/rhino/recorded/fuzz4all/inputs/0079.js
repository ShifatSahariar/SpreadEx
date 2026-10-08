function* fibGen(n) {
  var a = 0n, b = 1n, i = 0;
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
  var iter = fibGen(count);
  var step = iter.next();
  while (!step.done) {
    var val = step.value;
    var key = SYM.toString() + ':' + val;
    fibObj[key] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
    step = iter.next();
  }
} catch (ex) {
  console.log('Caught:', ex.message || ex);
}
var keys = Object.keys(fibObj);
for (var i = 0; i < keys.length; i++) {
  console.log(keys[i] + ' -> ' + fibObj[keys[i]]);
}
