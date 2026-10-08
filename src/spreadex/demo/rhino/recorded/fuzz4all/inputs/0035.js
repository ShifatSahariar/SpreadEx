function* fibGen(n) {
  var a = 0n, b = 1n;  
  for (var i = 0; i < n; i++) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
  }
}
const SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;  
  for (var num of fibGen(count)) {
    var key = SYM.toString() + num;  
    fibObj[key] = num + '';           
    if (typeof num === 'bigint' && num > 20n) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  print('Caught:', e.message || e);
}
for (var k in fibObj) {
  console.log(k + ' -> ' + fibObj[k]);
}
