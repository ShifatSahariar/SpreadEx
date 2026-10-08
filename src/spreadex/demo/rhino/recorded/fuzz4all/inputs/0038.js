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
  for (let num of fibGen(count)) {
     
    var key = String(SYM) + '_' + String(num);  
    fibObj[key] = num.toString();   
    if (typeof num === 'bigint' && +num > 50)  
      throw { error: 'BigFibTooBig', value: num };  
  }
} catch (e) {
   
  if (e && typeof e === 'object') {
    console.log('Caught error:', e.error, 'value:', e.value);
  } else {
    console.log('Caught:', e);
  }
}
for (var k in fibObj) {
  if (k.indexOf('_') !== -1) {  
    console.log(k + ' -> ' + fibObj[k]);
  }
}
