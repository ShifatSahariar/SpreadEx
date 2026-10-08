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
  var arr = [];
  for each (var num in fibGen(count)) {
    arr.push(num);
  }
  for (var i = 0; i < arr.length; i++) {
    var num = arr[i];
    var key = SYM.toString() + ':' + num;
    fibObj[key] = String(num);
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}

var keys = Object.keys(fibObj);
for (var k = 0; k < keys.length; k++) {
  console.log(keys[k] + ' -> ' + fibObj[keys[k]]);
}
