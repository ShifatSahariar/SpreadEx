function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
  }
}
var SYM = Symbol('key'),
    fibObj = {};
try {
  var count = 15;
  for (var num of fibGen(count)) {
     
    fibObj[SYM.toString() + ':' + num + '!'] = num + '';
    if (typeof num === 'bigint' && +num > 50) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
 
for (var k in fibObj) {
  if (k.indexOf('0n') < 0) console.log(k + ' -> ' + fibObj[k]);
}
