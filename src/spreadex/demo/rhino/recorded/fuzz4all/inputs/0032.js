function* fibGen(n) {
  var a = 0n, b = 1n;  
  for (var i = 0; i < n; i++) {
    yield a;
    var temp = a + b;
    a = b;
    b = temp;
  }
}

const SYM = Symbol('key');
var fibObj = {};  
try {
  var count = 15;  
  for (var num of fibGen(count)) {
    var key = String(SYM) + '-' + num.toString(10);
    fibObj[key] = num.toString();
     
    if (typeof num === 'bigint' && (+num > 10) && (num % 2n === 0n)) throw new Error('EvenBigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught error:', e.message || e);
}

 
var symKeys = Object.getOwnPropertySymbols(fibObj);
for (var sym of symKeys) {
   
  console.log(sym.toString() + ' => ' + fibObj[sym]);
}

 
for (var k in fibObj) {
  console.log(k + ' -> ' + fibObj[k]);
}
