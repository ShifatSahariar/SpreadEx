function* fibGen(n) {
  var a = 0n, b = 1n, i = 0;
  while (i < n) {
    yield a;
    var temp = a + b;
    a = b;
    b = temp;
    i++;
  }
}

var sym = Symbol('key');
var fibMap = {};

try {
  var n = 15;
  for (var val of fibGen(n)) {
    var prop = sym.toString() + ':' + val;
    fibMap[prop] = val.toString();
    if (typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}

var props = Object.keys(fibMap);
for (var j = 0; j < props.length; j++) {
  console.log(props[j] + ' -> ' + fibMap[props[j]]);
}
