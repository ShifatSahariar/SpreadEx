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
const fibObj = {};
try {
  var count = 15;  
  for (var num of fibGen(count)) {
    fibObj[SYM + ':' + num] = num.toString();  
    if (typeof num === 'bigint' && +num > 30) throw new Error('Fibonacci Number Too Big: ' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);  
}
for (var k in fibObj) {
  print(k + ' => ' + fibObj[k]);  
}
