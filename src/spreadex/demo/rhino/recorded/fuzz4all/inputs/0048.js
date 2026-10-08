function* fibGen(n) {
  var a = 0n, b = 1n;  
  for (var i = 0; i < n; i++) {
    yield a;
    a = a + b;
    b = a - b;  
  }
}
const SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  for (var num of fibGen(count)) {
     
    var key = SYM.toString() + ':' + num.toString(); 
    fibObj[key] = num + '';
    if (typeof num === 'bigint' && num > 50n) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
 
for (var k in fibObj) {
  let k2 = k;  
  console.log(k2 + ' -> ' + fibObj[k2]);
}
