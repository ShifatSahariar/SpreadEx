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
     
    fibObj[SYM] = fibObj[SYM] || [];
    fibObj[SYM].push(num.toString());
     
    if (typeof num === 'bigint' && num > 50n) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message);
}
 
var syms = Object.getOwnPropertySymbols(fibObj);
for (var i = 0; i < syms.length; i++) {
  var sym = syms[i];
  console.log(sym.toString() + ' -> ' + fibObj[sym].join(','));
}
