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
  var iter = fibGen(count);
  var next;
  while (!(next = iter.next()).done) {
    var num = next.value;
    var key = SYM.toString() + ':' + num;
    fibObj[key] = num.toString();
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
var keys = Object.keys(fibObj);
for (var j = 0; j < keys.length; j++) {
  console.log(keys[j] + ' -> ' + fibObj[keys[j]]);
}
