function* fibonacci(n) {
  var x = 0n, y = 1n;
  for (var i = 0; i < n; i++) {
    yield x;
    var next = x + y;
    x = y;
    y = next;
  }
}
var symbolKey = Symbol('key');
var fibMap = {};
try {
  var limit = 15;
  for (var val of fibonacci(limit)) {
    var compositeKey = symbolKey.toString() + ':' + val;
    fibMap[compositeKey] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
var props = Object.keys(fibMap);
for (var j = 0; j < props.length; j++) {
  console.log(props[j] + ' -> ' + fibMap[props[j]]);
}
