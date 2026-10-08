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
var keys = [];
try {
  var count = 15;  
  for (var num of fibGen(count)) {
     
    var key = SYM.toString() + (num % 5n);
    fibObj[key] = num.toString();
    keys.push(key);
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught error:', e.message || e);
}
for (var i = keys.length - 1; i >= 0; i--) {
  var k = keys[i];
  console.log(k + ' -> ' + fibObj[k]);
}
