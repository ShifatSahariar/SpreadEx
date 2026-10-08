function* fibGen(n) {
  var a = 0n, b = 1n;  
  for (var i = 0; i < n; i++) {
    yield a;
    a = b;
    b = a + b;  
  }
}
var SYM = Symbol('key');  
var fibObj = {};
try {
  var count = 12;  
  for (var num of fibGen(count)) {
    fibObj[String(SYM) + ':' + num] = num + '';  
    if (typeof num === 'bigint' && num > 50n) throw new Error('BigFibTooBig:' + num);  
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
for (var k in fibObj) {
  console.log(k + ' -> ' + fibObj[k].toString());
}
