function* fibGen(n) {
  var a = 0n, b = 1n;  
  var i = 0;
  while (i++ < n) {
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
     
     
    if (typeof num === 'bigint' && (num > 100n || +num > 10)) throw 'BigFibTooBig:' + num;
    
     
    fibObj[String(SYM) + num.toString()] = num + '';
  }
} catch (e) {
  print('Caught: ' + e);
}
 
var syms = Object.getOwnPropertySymbols(fibObj);
for (var i = 0; i < syms.length; i++) {
  var sym = syms[i];
   
  print(sym.toString() + ' -> ' + fibObj[sym]);
}
