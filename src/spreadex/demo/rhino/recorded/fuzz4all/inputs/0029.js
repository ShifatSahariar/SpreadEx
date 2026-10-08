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
try {
  var count = 12;  
  for (var num of fibGen(count)) {
     
    var key = SYM.toString() + '-' + String(num);
    fibObj[key] = num + '';  

     
    if (typeof num === 'bigint' && +num > 50) throw {error: 'BigFibTooBig', value: num};
  }
} catch (e) {
  if (typeof e === 'object' && e.error) {
    console.log('Caught error:', e.error, 'with value', e.value);
  } else {
    console.log('Caught:', e);
  }
}
 
for (var k in fibObj) {
  var revKey = '';
  for (var j = k.length - 1; j >= 0; j--) revKey += k[j];
  var valBig = BigInt(fibObj[k]);
  console.log(revKey + ' -> ' + (valBig * valBig));
}
