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
  var count = 15;
  for (var num of fibGen(count)) {
     
    fibObj[SYM + "@" + num] = num.toString(10);
    if (num > 100n) throw new Error('BigFibOverflow:' + num);
  }
} catch (e) {
   
  console.log('Caught error:', e);
}
 
for (let sym of Object.getOwnPropertySymbols(fibObj)) {
  console.log('symbol-key ->', sym.toString(), ':', fibObj[sym]);
}
for (const key in fibObj) {
  console.log('string-key ->', key, ':', fibObj[key]);
}
