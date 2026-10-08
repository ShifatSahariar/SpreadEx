function* fibGen(n) {
  var a = 0n, b = 1n;   
  var i = 0;
  while (i < n) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
    i++;
  }
}

const SYM = Symbol('key');
const fibObj = {};
try {
  var count = 15;  
  for (var num of fibGen(count)) {
     
    var key = SYM.toString() + String(num);
    fibObj[key] = num.toString();  
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  print('Caught:', e.message || e);  
}

for (var k in fibObj) {
  print(k + ' maps to ' + fibObj[k]);
}
