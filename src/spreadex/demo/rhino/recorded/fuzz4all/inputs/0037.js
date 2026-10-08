function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    let temp = a;
    a = b;
    b = temp + b;
  }
}
var SYM = Symbol('key');
var fibObj = {};
var count = 20;
try {
  for (var num of fibGen(count)) {
     
    var key = SYM.description + ':' + String(num);
    fibObj[key] = num + '';
    if (typeof num === 'bigint' && num > 1000n) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
for (var k in fibObj) {
  console.log(k + ' -> ' + fibObj[k]);
}
