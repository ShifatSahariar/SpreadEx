function* fibonacci(n) {
  var x = 0n, y = 1n, i = 0;
  while (i < n) {
    yield x;
    var z = x + y;
    x = y;
    y = z;
    i++;
  }
}

var SYMBOL = Symbol('key');
var fibMap = {};
try {
  var limit = 15;
  var iterator = fibonacci(limit);
  for (;;) {
    var next = iterator.next();
    if (next.done) break;
    var val = next.value;
    var prop = SYMBOL.toString() + ':' + val;
    fibMap[prop] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
var fibKeys = Object.keys(fibMap);
var idx = 0;
while (idx < fibKeys.length) {
  console.log(fibKeys[idx] + ' -> ' + fibMap[fibKeys[idx]]);
  idx++;
}
