function* fibGen(n) {
  var a = 0n, b = 1n;
  for (let i = 0; i < n; i++) {
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
     
    fibObj[SYM.toString() + num] = num + '';  
    if (typeof num === 'bigint' && Number(num) > 50)
      throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  print('Caught:', e.message || e);
}
for (let k in fibObj) {
  console.log(k + ' => ' + fibObj[k]);
}
